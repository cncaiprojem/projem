"""task_47_notification_service_email_sms_provider_fallback

Revision ID: task_47_notification_service
Revises: 20250818_add_idempotency_records_table
Create Date: 2025-08-19 00:00:00.000000

Task 4.7: Ultra-enterprise notification service for email/SMS with provider fallback
- notifications_delivery: Core notification delivery tracking
- notification_templates: Reusable templates for D-7/3/1 reminders  
- notification_attempts: Audit trail of all send attempts including fallbacks
- ENUMs for channels, status, template types
- Banking-grade constraints and Turkish KVKK compliance
"""
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB


# revision identifiers, used by Alembic.
revision = 'task_47_notification_service'
down_revision = '20250818_add_idempotency_records_table'
branch_labels = None
depends_on = None


# ENUMs for notification service - create_type=False because we explicitly call create()
notification_channel_enum = ENUM(
    'email', 'sms',
    name='notification_channel_enum',
    create_type=False
)

notification_status_enum = ENUM(
    'queued', 'sent', 'failed', 'bounced', 'delivered',
    name='notification_status_enum', 
    create_type=False
)

notification_template_type_enum = ENUM(
    'license_reminder_d7', 'license_reminder_d3', 'license_reminder_d1', 
    'license_expired', 'payment_success', 'payment_failed', 'welcome',
    'password_reset', 'account_locked', 'mfa_enabled',
    name='notification_template_type_enum',
    create_type=False
)

notification_provider_enum = ENUM(
    'postmark_api', 'smtp_primary', 'smtp_fallback', 
    'twilio_sms', 'vonage_sms', 'mock_provider',
    name='notification_provider_enum',
    create_type=False
)


def upgrade() -> None:
    """Create notification service tables and ENUMs."""
    
    # Create ENUMs first
    notification_channel_enum.create(op.get_bind(), checkfirst=True)
    notification_status_enum.create(op.get_bind(), checkfirst=True)
    notification_template_type_enum.create(op.get_bind(), checkfirst=True)
    notification_provider_enum.create(op.get_bind(), checkfirst=True)
    
    # notification_templates table
    op.create_table(
        'notification_templates',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('type', notification_template_type_enum, nullable=False, index=True),
        sa.Column('channel', notification_channel_enum, nullable=False, index=True),
        sa.Column('language', sa.String(5), nullable=False, server_default='tr-TR'),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        
        # Template content
        sa.Column('subject_template', sa.Text(), nullable=True, comment='Email subject template (null for SMS)'),
        sa.Column('body_template', sa.Text(), nullable=False, comment='Email HTML or SMS text template'),
        sa.Column('plain_text_template', sa.Text(), nullable=True, comment='Email plain text fallback'),
        
        # Template variables and validation
        sa.Column('variables', JSONB, nullable=False, server_default='{}', 
                  comment='Required template variables as JSON schema'),
        sa.Column('max_length', sa.Integer(), nullable=True, 
                  comment='Max rendered length (160 for SMS)'),
        
        # Metadata and versioning
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, 
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, 
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        
        # Constraints
        sa.CheckConstraint("(channel = 'sms' AND subject_template IS NULL) OR channel = 'email'", 
                           name='ck_notification_templates_sms_no_subject'),
        sa.CheckConstraint("(channel = 'sms' AND max_length = 160) OR (channel = 'email' AND max_length IS NULL)", 
                           name='ck_notification_templates_sms_max_length'),
        sa.CheckConstraint("length(name) >= 3", name='ck_notification_templates_name_length'),
        sa.CheckConstraint("version >= 1", name='ck_notification_templates_version_positive'),
        
        # Partial unique index: one active template per type+channel+language (when is_active=true)
        sa.Index('uq_notification_templates_active', 
                 'type', 'channel', 'language',
                 unique=True,
                 postgresql_where=sa.text("is_active = true")),
        
        # Performance indexes
        sa.Index('idx_notification_templates_type_channel', 'type', 'channel'),
        sa.Index('idx_notification_templates_active_lang', 'is_active', 'language'),
        sa.Index('idx_notification_templates_variables', 'variables', postgresql_using='gin'),
    )
    
    # notifications_delivery table  
    op.create_table(
        'notifications_delivery',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        
        # Foreign keys with RESTRICT behavior
        sa.Column('user_id', sa.BigInteger(), 
                  sa.ForeignKey('users.id', ondelete='RESTRICT'), 
                  nullable=False, index=True),
        sa.Column('license_id', sa.BigInteger(), 
                  sa.ForeignKey('licenses.id', ondelete='RESTRICT'), 
                  nullable=True, index=True, comment='Null for non-license notifications'),
        sa.Column('template_id', sa.BigInteger(), 
                  sa.ForeignKey('notification_templates.id', ondelete='RESTRICT'), 
                  nullable=False, index=True),
        
        # Notification metadata
        sa.Column('channel', notification_channel_enum, nullable=False, index=True),
        sa.Column('recipient', sa.String(255), nullable=False, index=True,
                  comment='Email address or phone number'),
        sa.Column('days_out', sa.Integer(), nullable=True, 
                  comment='Days remaining for license reminders (7, 3, 1)'),
        
        # Content and rendering
        sa.Column('subject', sa.String(255), nullable=True, comment='Rendered subject (null for SMS)'),
        sa.Column('body', sa.Text(), nullable=False, comment='Rendered message body'),
        sa.Column('variables', JSONB, nullable=False, server_default='{}',
                  comment='Template variables used for rendering'),
        
        # Delivery tracking
        sa.Column('status', notification_status_enum, nullable=False, 
                  server_default='queued', index=True),
        sa.Column('priority', sa.String(10), nullable=False, server_default='normal',
                  comment='Priority: low, normal, high, urgent'),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True,
                  comment='When to send (null for immediate)'),
        
        # Provider and external tracking
        sa.Column('primary_provider', notification_provider_enum, nullable=False),
        sa.Column('actual_provider', notification_provider_enum, nullable=True, 
                  comment='Provider that actually sent (may differ due to fallback)'),
        sa.Column('provider_message_id', sa.String(255), nullable=True, index=True,
                  comment='Provider-specific message ID for tracking'),
        sa.Column('provider_response', JSONB, nullable=True, 
                  comment='Full provider response for debugging'),
        
        # Error handling
        sa.Column('error_code', sa.String(50), nullable=True, index=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, 
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True, index=True),
        
        # Ultra-enterprise constraints
        sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", 
                           name='ck_notifications_delivery_valid_priority'),
        sa.CheckConstraint("days_out IN (1, 3, 7) OR days_out IS NULL", 
                           name='ck_notifications_delivery_valid_days_out'),
        sa.CheckConstraint("retry_count <= max_retries", 
                           name='ck_notifications_delivery_retry_limit'),
        sa.CheckConstraint("(channel = 'sms' AND subject IS NULL) OR channel = 'email'", 
                           name='ck_notifications_delivery_sms_no_subject'),
        sa.CheckConstraint("(status = 'sent' AND sent_at IS NOT NULL) OR status != 'sent'", 
                           name='ck_notifications_delivery_sent_has_timestamp'),
        sa.CheckConstraint("(status = 'failed' AND failed_at IS NOT NULL) OR status != 'failed'", 
                           name='ck_notifications_delivery_failed_has_timestamp'),
        
        # Performance and analytics indexes
        sa.Index('idx_notifications_delivery_user_status', 'user_id', 'status'),
        sa.Index('idx_notifications_delivery_license_channel', 'license_id', 'channel'),
        sa.Index('idx_notifications_delivery_scheduled', 'scheduled_at', 
                 postgresql_where=sa.text("status = 'queued' AND scheduled_at IS NOT NULL")),
        sa.Index('idx_notifications_delivery_failed_retry', 'status', 'retry_count', 
                 postgresql_where=sa.text("status = 'failed' AND retry_count < max_retries")),
        sa.Index('idx_notifications_delivery_provider_tracking', 'provider_message_id', 'actual_provider'),
        sa.Index('idx_notifications_delivery_analytics', 'channel', 'status', 'created_at'),
        sa.Index('idx_notifications_delivery_variables', 'variables', postgresql_using='gin'),
    )
    
    # notification_attempts table for audit trail
    op.create_table(
        'notification_attempts',
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        
        # Foreign key to main notification
        sa.Column('notification_id', sa.BigInteger(), 
                  sa.ForeignKey('notifications_delivery.id', ondelete='CASCADE'), 
                  nullable=False, index=True),
        
        # Attempt details
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('provider', notification_provider_enum, nullable=False),
        sa.Column('status', notification_status_enum, nullable=False, index=True),
        
        # Provider interaction
        sa.Column('provider_request', JSONB, nullable=True, 
                  comment='Request payload sent to provider'),
        sa.Column('provider_response', JSONB, nullable=True,
                  comment='Response received from provider'),
        sa.Column('provider_message_id', sa.String(255), nullable=True, index=True),
        
        # Error details
        sa.Column('error_code', sa.String(50), nullable=True, index=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('http_status_code', sa.Integer(), nullable=True),
        
        # Timing
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, 
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True, 
                  comment='Attempt duration in milliseconds'),
        
        # Constraints
        sa.CheckConstraint("attempt_number >= 1", name='ck_notification_attempts_positive_attempt'),
        sa.CheckConstraint("(completed_at IS NOT NULL AND duration_ms IS NOT NULL) OR "
                           "(completed_at IS NULL AND duration_ms IS NULL)", 
                           name='ck_notification_attempts_completion_consistency'),
        sa.CheckConstraint("http_status_code >= 100 AND http_status_code < 600 OR http_status_code IS NULL", 
                           name='ck_notification_attempts_valid_http_status'),
        
        # Unique constraint: one attempt per notification + attempt_number
        sa.UniqueConstraint('notification_id', 'attempt_number', 
                            name='uq_notification_attempts_number'),
        
        # Performance indexes
        sa.Index('idx_notification_attempts_provider_status', 'provider', 'status'),
        sa.Index('idx_notification_attempts_timing', 'started_at', 'completed_at'),
        sa.Index('idx_notification_attempts_errors', 'error_code', 
                 postgresql_where=sa.text("error_code IS NOT NULL")),
    )
    
    # Insert default notification templates
    insert_default_templates()


def insert_default_templates():
    """Insert default Turkish notification templates."""
    from sqlalchemy.sql import text
    
    templates = [
        # License reminder templates - Email
        {
            'type': 'license_reminder_d7',
            'channel': 'email',
            'name': 'Lisans Süresi 7 Gün Kaldı',
            'subject_template': 'FreeCAD Lisansınız 7 Gün İçinde Sona Eriyor',
            'body_template': '''
<html>
<body>
    <h2>Merhaba {user_name},</h2>
    <p><strong>FreeCAD lisansınızın süresi {days_remaining} gün sonra sona erecek.</strong></p>
    <p>Lisans bitiş tarihi: <strong>{ends_at}</strong></p>
    <p>Kesintisiz hizmet almaya devam etmek için lütfen lisansınızı yenileyin:</p>
    <p><a href="{renewal_link}" style="background-color: #007cba; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Lisansı Yenile</a></p>
    <p>Sorularınız için destek ekibimizle iletişime geçebilirsiniz.</p>
    <p>FreeCAD Ekibi</p>
</body>
</html>''',
            'plain_text_template': '''Merhaba {user_name},

FreeCAD lisansınızın süresi {days_remaining} gün sonra sona erecek.
Lisans bitiş tarihi: {ends_at}

Kesintisiz hizmet almaya devam etmek için lütfen lisansınızı yenileyin:
{renewal_link}

Sorularınız için destek ekibimizle iletişime geçebilirsiniz.

FreeCAD Ekibi''',
            'variables': '{"user_name": "string", "days_remaining": "integer", "ends_at": "datetime", "renewal_link": "string"}',
        },
        
        # License reminder - SMS
        {
            'type': 'license_reminder_d7',
            'channel': 'sms',
            'name': 'Lisans Süresi 7 Gün Kaldı (SMS)',
            'body_template': 'Merhaba {user_name}! FreeCAD lisansınız {days_remaining} gün sonra sona eriyor. Yenile: {renewal_link}',
            'max_length': 160,
            'variables': '{"user_name": "string", "days_remaining": "integer", "renewal_link": "string"}',
        },
        
        # D-3 Email
        {
            'type': 'license_reminder_d3',
            'channel': 'email', 
            'name': 'Lisans Süresi 3 Gün Kaldı',
            'subject_template': 'ÖNEMLİ: FreeCAD Lisansınız 3 Gün İçinde Sona Eriyor!',
            'body_template': '''
<html>
<body>
    <h2>Merhaba {user_name},</h2>
    <p><strong style="color: #d32f2f;">FreeCAD lisansınızın süresi sadece {days_remaining} gün sonra sona erecek!</strong></p>
    <p>Lisans bitiş tarihi: <strong>{ends_at}</strong></p>
    <p>Hizmet kesintisi yaşamamak için <u>acilen</u> lisansınızı yenileyin:</p>
    <p><a href="{renewal_link}" style="background-color: #d32f2f; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">HEMEN LİSANSI YENİLE</a></p>
    <p><small>Bu son hatırlatmalardan biridir. Lütfen gecikmeden işlem yapın.</small></p>
    <p>FreeCAD Ekibi</p>
</body>
</html>''',
            'plain_text_template': '''ÖNEMLI: Merhaba {user_name},

FreeCAD lisansınızın süresi sadece {days_remaining} gün sonra sona erecek!
Lisans bitiş tarihi: {ends_at}

Hizmet kesintisi yaşamamak için acilen lisansınızı yenileyin:
{renewal_link}

Bu son hatırlatmalardan biridir. Lütfen gecikmeden işlem yapın.

FreeCAD Ekibi''',
            'variables': '{"user_name": "string", "days_remaining": "integer", "ends_at": "datetime", "renewal_link": "string"}',
        },
        
        # D-3 SMS
        {
            'type': 'license_reminder_d3',
            'channel': 'sms',
            'name': 'Lisans Süresi 3 Gün Kaldı (SMS)',
            'body_template': 'ÖNEMLİ {user_name}! FreeCAD lisansınız {days_remaining} gün sonra sona eriyor. Acilen yenile: {renewal_link}',
            'max_length': 160,
            'variables': '{"user_name": "string", "days_remaining": "integer", "renewal_link": "string"}',
        },
        
        # D-1 Email
        {
            'type': 'license_reminder_d1',
            'channel': 'email',
            'name': 'Lisans Süresi 1 Gün Kaldı',
            'subject_template': 'SON GÜN: FreeCAD Lisansınız Yarın Sona Eriyor!',
            'body_template': '''
<html>
<body style="background-color: #fff3e0;">
    <div style="background-color: #ff5722; color: white; padding: 15px; text-align: center;">
        <h1>SON 24 SAAT!</h1>
    </div>
    <div style="padding: 20px;">
        <h2>Merhaba {user_name},</h2>
        <p><strong style="color: #ff5722; font-size: 18px;">FreeCAD lisansınızın süresi yarın ({ends_at}) sona eriyor!</strong></p>
        <p>Bu son hatırlatmadır. Lisansınız sona erdiğinde:</p>
        <ul>
            <li>Tüm premium özelliklere erişiminiz kesilecek</li>
            <li>Mevcut projeleriniz etkilenebilir</li>
            <li>CAD/CAM işlemleriniz durabilir</li>
        </ul>
        <p><strong>ŞİMDİ YENİLEYİN:</strong></p>
        <p><a href="{renewal_link}" style="background-color: #ff5722; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-size: 18px; font-weight: bold;">ACİL LİSANS YENİLEME</a></p>
        <p><small>7/24 destek ekibimiz yardımınıza hazır.</small></p>
        <p>FreeCAD Ekibi</p>
    </div>
</body>
</html>''',
            'plain_text_template': '''SON GÜN! Merhaba {user_name},

FreeCAD lisansınızın süresi yarın ({ends_at}) sona eriyor!

Bu son hatırlatmadır. Lisansınız sona erdiğinde tüm premium özelliklerinize erişiminiz kesilecek.

ŞİMDİ YENİLEYİN: {renewal_link}

7/24 destek ekibimiz yardımınıza hazır.

FreeCAD Ekibi''',
            'variables': '{"user_name": "string", "days_remaining": "integer", "ends_at": "datetime", "renewal_link": "string"}',
        },
        
        # D-1 SMS
        {
            'type': 'license_reminder_d1',
            'channel': 'sms',
            'name': 'Lisans Süresi 1 Gün Kaldı (SMS)', 
            'body_template': 'SON GÜN {user_name}! Lisansınız yarın bitiyor. Hemen yenile: {renewal_link}',
            'max_length': 160,
            'variables': '{"user_name": "string", "renewal_link": "string"}',
        },
    ]
    
    # Insert templates using parameterized queries to prevent SQL injection
    connection = op.get_bind()
    for template in templates:
        # Use fully parameterized query - NO f-string interpolation for security
        insert_stmt = text("""
            INSERT INTO notification_templates 
            (type, channel, name, subject_template, body_template, plain_text_template, variables, max_length)
            VALUES 
            (:type, :channel, :name, :subject, :body, :plain, :variables::jsonb, :max_length)
        """)
        
        connection.execute(insert_stmt, {
            'type': template['type'],
            'channel': template['channel'],
            'name': template['name'],
            'subject': template.get('subject_template'),
            'body': template['body_template'],
            'plain': template.get('plain_text_template'),
            'variables': template['variables'],
            'max_length': template.get('max_length')
        })


def downgrade() -> None:
    """Drop notification service tables and ENUMs."""
    
    # Drop tables (foreign keys will cascade)
    op.drop_table('notification_attempts')
    op.drop_table('notifications_delivery')
    op.drop_table('notification_templates')
    
    # Drop ENUMs
    notification_provider_enum.drop(op.get_bind(), checkfirst=True)
    notification_template_type_enum.drop(op.get_bind(), checkfirst=True) 
    notification_status_enum.drop(op.get_bind(), checkfirst=True)
    notification_channel_enum.drop(op.get_bind(), checkfirst=True)