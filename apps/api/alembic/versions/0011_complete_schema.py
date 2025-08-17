"""Complete database schema with all required tables

Revision ID: 0011_complete_schema
Revises: 0010_m18_multi_setup
Create Date: 2025-08-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_complete_schema"
down_revision = "0010_m18_multi_setup"
branch_labels = None
depends_on = None


def upgrade():
    # Create missing enum types
    op.execute("CREATE TYPE user_role AS ENUM ('admin', 'engineer', 'operator', 'viewer')")
    op.execute("CREATE TYPE locale AS ENUM ('tr', 'en', 'de')")
    op.execute("CREATE TYPE license_type AS ENUM ('trial', 'basic', 'professional', 'enterprise')")
    op.execute("CREATE TYPE license_status AS ENUM ('active', 'expired', 'suspended', 'cancelled')")
    op.execute("CREATE TYPE job_type AS ENUM ('cad_generate', 'cad_import', 'cad_export', 'cam_process', 'cam_optimize', 'sim_run', 'sim_collision', 'gcode_post', 'gcode_verify', 'report_generate', 'model_repair')")
    op.execute("CREATE TYPE job_status AS ENUM ('pending', 'queued', 'running', 'completed', 'failed', 'cancelled', 'timeout')")
    op.execute("CREATE TYPE model_type AS ENUM ('part', 'assembly', 'drawing', 'sketch', 'mesh')")
    op.execute("CREATE TYPE invoice_type AS ENUM ('subscription', 'usage', 'one_time', 'credit', 'adjustment')")
    op.execute("CREATE TYPE invoice_status AS ENUM ('draft', 'sent', 'viewed', 'paid', 'partial', 'overdue', 'cancelled', 'refunded')")
    op.execute("CREATE TYPE payment_status AS ENUM ('pending', 'processing', 'completed', 'failed', 'cancelled', 'refunded', 'partial_refund', 'disputed')")
    op.execute("CREATE TYPE currency AS ENUM ('TRY', 'USD', 'EUR')")
    op.execute("CREATE TYPE notification_type AS ENUM ('job_completed', 'job_failed', 'job_warning', 'system_update', 'system_maintenance', 'system_alert', 'license_expiring', 'license_expired', 'license_renewed', 'invoice_created', 'payment_due', 'payment_received', 'payment_failed', 'security_alert', 'login_new_device', 'password_reset')")
    op.execute("CREATE TYPE notification_severity AS ENUM ('info', 'warning', 'error', 'critical')")
    op.execute("CREATE TYPE audit_action AS ENUM ('auth_login', 'auth_logout', 'auth_failed', 'auth_token_refresh', 'user_create', 'user_update', 'user_delete', 'user_password_change', 'create', 'read', 'update', 'delete', 'export', 'import', 'job_start', 'job_cancel', 'job_retry', 'config_change', 'backup_create', 'backup_restore')")
    op.execute("CREATE TYPE security_event_type AS ENUM ('login_failed', 'login_suspicious', 'brute_force', 'account_locked', 'access_denied', 'privilege_escalation', 'data_breach', 'sql_injection', 'xss_attempt', 'file_upload_blocked', 'rate_limit_exceeded', 'ddos_detected', 'vulnerability_scan')")
    op.execute("CREATE TYPE security_severity AS ENUM ('low', 'medium', 'high', 'critical')")
    op.execute("CREATE TYPE sync_direction AS ENUM ('inbound', 'outbound', 'bidirectional')")
    op.execute("CREATE TYPE sync_status AS ENUM ('pending', 'in_progress', 'synced', 'failed', 'conflict', 'skipped')")
    op.execute("CREATE TYPE machine_type AS ENUM ('mill_3axis', 'mill_4axis', 'mill_5axis', 'lathe', 'turn_mill', 'router', 'plasma', 'laser', 'waterjet', 'edm_wire', 'edm_sinker', 'grinder', 'swiss')")
    op.execute("CREATE TYPE tool_type AS ENUM ('endmill_flat', 'endmill_ball', 'endmill_bull', 'endmill_chamfer', 'endmill_taper', 'face_mill', 'slot_mill', 'drill_twist', 'drill_center', 'drill_spot', 'drill_peck', 'drill_gun', 'reamer', 'tap', 'thread_mill', 'boring_bar', 'countersink', 'counterbore', 'engraver', 'probe')")
    op.execute("CREATE TYPE tool_material AS ENUM ('hss', 'carbide', 'carbide_coated', 'ceramic', 'cbn', 'pcd', 'cobalt')")
    op.execute("CREATE TYPE material_category AS ENUM ('steel_carbon', 'steel_alloy', 'steel_stainless', 'steel_tool', 'aluminum', 'titanium', 'copper', 'brass', 'bronze', 'cast_iron', 'nickel', 'magnesium', 'plastic_soft', 'plastic_hard', 'plastic_fiber', 'composite', 'wood_soft', 'wood_hard', 'wood_mdf', 'foam', 'ceramic', 'graphite')")

    # Update users table (already exists, add missing columns)
    op.add_column('users', sa.Column('phone', sa.String(20), unique=True))
    op.add_column('users', sa.Column('company_name', sa.String(255)))
    op.add_column('users', sa.Column('tax_no', sa.String(20)))
    op.add_column('users', sa.Column('address', sa.Text()))
    op.add_column('users', sa.Column('timezone', sa.String(50), nullable=False, server_default='Europe/Istanbul'))
    op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('users', sa.Column('is_verified', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True)))
    op.add_column('users', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column('users', sa.Column('metadata', postgresql.JSONB()))
    
    # Convert role and locale columns to enum types
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role")
    op.execute("ALTER TABLE users ALTER COLUMN locale TYPE locale USING locale::locale")
    
    # Add indexes for users
    op.create_index('idx_users_phone', 'users', ['phone'], postgresql_where='phone IS NOT NULL')
    op.create_index('idx_users_tax_no', 'users', ['tax_no'], postgresql_where='tax_no IS NOT NULL')
    op.create_index('idx_users_created_at', 'users', ['created_at'])
    op.create_index('idx_users_metadata', 'users', ['metadata'], postgresql_using='gin', postgresql_where='metadata IS NOT NULL')

    # Create sessions table
    op.create_table(
        'sessions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('refresh_token_hash', sa.String(255), unique=True, nullable=False),
        sa.Column('access_token_jti', sa.String(255)),
        sa.Column('ip_address', postgresql.INET()),
        sa.Column('user_agent', sa.String(500)),
        sa.Column('device_id', sa.String(255)),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )
    op.create_index('idx_sessions_user_id', 'sessions', ['user_id'])
    op.create_index('idx_sessions_refresh_token_hash', 'sessions', ['refresh_token_hash'])
    op.create_index('idx_sessions_access_token_jti', 'sessions', ['access_token_jti'], postgresql_where='access_token_jti IS NOT NULL')
    op.create_index('idx_sessions_expires_at', 'sessions', ['expires_at'], postgresql_where='revoked_at IS NULL')
    op.create_index('idx_sessions_device_id', 'sessions', ['device_id'], postgresql_where='device_id IS NOT NULL')

    # Create licenses table
    op.create_table(
        'licenses',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('type', postgresql.ENUM('trial', 'basic', 'professional', 'enterprise', name='license_type'), nullable=False),
        sa.Column('status', postgresql.ENUM('active', 'expired', 'suspended', 'cancelled', name='license_status'), nullable=False),
        sa.Column('seats', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('features', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('auto_renew', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('seats > 0', name='ck_licenses_seats_positive')
    )
    op.create_index('idx_licenses_user_id', 'licenses', ['user_id'])
    op.create_index('idx_licenses_status', 'licenses', ['status'], postgresql_where="status = 'active'")
    op.create_index('idx_licenses_ends_at', 'licenses', ['ends_at'], postgresql_where="status = 'active'")
    op.create_index('idx_licenses_features', 'licenses', ['features'], postgresql_using='gin')

    # Create models table
    op.create_table(
        'models',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('type', postgresql.ENUM('part', 'assembly', 'drawing', 'sketch', 'mesh', name='model_type'), nullable=False),
        sa.Column('file_format', sa.String(20), nullable=False),
        sa.Column('s3_key', sa.String(1024), unique=True, nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=False),
        sa.Column('sha256_hash', sa.String(64), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('parent_model_id', sa.Integer(), sa.ForeignKey('models.id', ondelete='SET NULL')),
        sa.Column('metadata', postgresql.JSONB()),
        sa.Column('thumbnail_s3_key', sa.String(1024)),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )
    op.create_index('idx_models_user_id', 'models', ['user_id'])
    op.create_index('idx_models_project_id', 'models', ['project_id'], postgresql_where='project_id IS NOT NULL')
    op.create_index('idx_models_sha256_hash', 'models', ['sha256_hash'])
    op.create_index('idx_models_created_at', 'models', ['created_at'])
    op.create_index('idx_models_metadata', 'models', ['metadata'], postgresql_using='gin', postgresql_where='metadata IS NOT NULL')

    # Update jobs table (add missing columns)
    op.add_column('jobs', sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT')))
    op.add_column('jobs', sa.Column('priority', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('jobs', sa.Column('task_id', sa.String(255)))
    op.add_column('jobs', sa.Column('input_params', postgresql.JSONB(), nullable=False, server_default='{}'))
    op.add_column('jobs', sa.Column('output_data', postgresql.JSONB()))
    op.add_column('jobs', sa.Column('progress', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('jobs', sa.Column('error_code', sa.String(100)))
    op.add_column('jobs', sa.Column('error_message', sa.String(1000)))
    op.add_column('jobs', sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('jobs', sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'))
    op.add_column('jobs', sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='3600'))
    op.add_column('jobs', sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column('jobs', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    
    # Convert job columns to enum types
    op.execute("ALTER TABLE jobs ALTER COLUMN type TYPE job_type USING type::job_type")
    op.execute("ALTER TABLE jobs ALTER COLUMN status TYPE job_status USING status::job_status")
    
    # Add constraints and indexes for jobs
    op.create_check_constraint('ck_jobs_progress_valid', 'jobs', 'progress >= 0 AND progress <= 100')
    op.create_index('idx_jobs_user_id', 'jobs', ['user_id'], postgresql_where='user_id IS NOT NULL')
    op.create_index('idx_jobs_type_status', 'jobs', ['type', 'status'])
    op.create_index('idx_jobs_status', 'jobs', ['status'], postgresql_where="status IN ('pending', 'queued', 'running')")
    op.create_index('idx_jobs_task_id', 'jobs', ['task_id'], postgresql_where='task_id IS NOT NULL')
    op.create_index('idx_jobs_created_at', 'jobs', ['created_at'])
    op.create_index('idx_jobs_started_at', 'jobs', ['started_at'], postgresql_where='started_at IS NOT NULL')

    # Create cam_runs table
    op.create_table(
        'cam_runs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('jobs.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('model_id', sa.Integer(), sa.ForeignKey('models.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('setup_id', sa.Integer(), sa.ForeignKey('setups.id', ondelete='RESTRICT')),
        sa.Column('strategy', sa.String(100), nullable=False),
        sa.Column('tool_paths', postgresql.JSONB()),
        sa.Column('cutting_params', postgresql.JSONB(), nullable=False),
        sa.Column('estimated_time_seconds', sa.Integer()),
        sa.Column('material_removal_cc', sa.Numeric(10, 2)),
        sa.Column('output_s3_key', sa.String(1024)),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('error_details', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True))
    )
    op.create_index('idx_cam_runs_job_id', 'cam_runs', ['job_id'])
    op.create_index('idx_cam_runs_model_id', 'cam_runs', ['model_id'])
    op.create_index('idx_cam_runs_setup_id', 'cam_runs', ['setup_id'], postgresql_where='setup_id IS NOT NULL')

    # Create sim_runs table
    op.create_table(
        'sim_runs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('jobs.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('cam_run_id', sa.Integer(), sa.ForeignKey('cam_runs.id', ondelete='CASCADE')),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('machine_id', sa.Integer(), sa.ForeignKey('machines.id', ondelete='RESTRICT')),
        sa.Column('collision_count', sa.Integer(), server_default='0'),
        sa.Column('collision_details', postgresql.JSONB()),
        sa.Column('material_removal_accuracy', sa.Numeric(5, 2)),
        sa.Column('simulation_time_ms', sa.Integer()),
        sa.Column('video_s3_key', sa.String(1024)),
        sa.Column('report_s3_key', sa.String(1024)),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True))
    )
    op.create_index('idx_sim_runs_job_id', 'sim_runs', ['job_id'])
    op.create_index('idx_sim_runs_cam_run_id', 'sim_runs', ['cam_run_id'], postgresql_where='cam_run_id IS NOT NULL')
    op.create_index('idx_sim_runs_machine_id', 'sim_runs', ['machine_id'], postgresql_where='machine_id IS NOT NULL')

    # Update artefacts table (add missing columns)
    op.add_column('artefacts', sa.Column('name', sa.String(255), nullable=False, server_default='unnamed'))
    op.add_column('artefacts', sa.Column('file_size', sa.BigInteger(), nullable=False, server_default='0'))
    op.add_column('artefacts', sa.Column('mime_type', sa.String(100)))
    op.add_column('artefacts', sa.Column('metadata', postgresql.JSONB()))
    op.add_column('artefacts', sa.Column('expires_at', sa.DateTime(timezone=True)))
    op.add_column('artefacts', sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    
    # Rename size to file_size if it exists
    op.execute("ALTER TABLE artefacts RENAME COLUMN size TO file_size_old")
    op.execute("UPDATE artefacts SET file_size = file_size_old")
    op.drop_column('artefacts', 'file_size_old')
    
    # Add indexes for artefacts
    op.create_index('idx_artefacts_job_id', 'artefacts', ['job_id'])
    op.create_index('idx_artefacts_s3_key', 'artefacts', ['s3_key'])
    op.create_index('idx_artefacts_sha256', 'artefacts', ['sha256'], postgresql_where='sha256 IS NOT NULL')
    op.create_index('idx_artefacts_expires_at', 'artefacts', ['expires_at'], postgresql_where='expires_at IS NOT NULL')

    # Create machines table
    op.create_table(
        'machines',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('manufacturer', sa.String(100)),
        sa.Column('model', sa.String(100)),
        sa.Column('type', postgresql.ENUM('mill_3axis', 'mill_4axis', 'mill_5axis', 'lathe', 'turn_mill', 'router', 'plasma', 'laser', 'waterjet', 'edm_wire', 'edm_sinker', 'grinder', 'swiss', name='machine_type'), nullable=False),
        sa.Column('axes', sa.Integer(), nullable=False),
        sa.Column('work_envelope_x_mm', sa.Numeric(10, 2), nullable=False),
        sa.Column('work_envelope_y_mm', sa.Numeric(10, 2), nullable=False),
        sa.Column('work_envelope_z_mm', sa.Numeric(10, 2), nullable=False),
        sa.Column('spindle_max_rpm', sa.Integer(), nullable=False),
        sa.Column('spindle_power_kw', sa.Numeric(10, 2)),
        sa.Column('tool_capacity', sa.Integer()),
        sa.Column('controller', sa.String(100)),
        sa.Column('post_processor', sa.String(100), nullable=False),
        sa.Column('hourly_rate', sa.Numeric(10, 2)),
        sa.Column('specifications', postgresql.JSONB()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('axes >= 3 AND axes <= 9', name='ck_machines_axes_valid')
    )
    op.create_index('idx_machines_type', 'machines', ['type'])
    op.create_index('idx_machines_active', 'machines', ['is_active', 'name'], postgresql_where='is_active = true')

    # Create materials table
    op.create_table(
        'materials',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('category', postgresql.ENUM('steel_carbon', 'steel_alloy', 'steel_stainless', 'steel_tool', 'aluminum', 'titanium', 'copper', 'brass', 'bronze', 'cast_iron', 'nickel', 'magnesium', 'plastic_soft', 'plastic_hard', 'plastic_fiber', 'composite', 'wood_soft', 'wood_hard', 'wood_mdf', 'foam', 'ceramic', 'graphite', name='material_category'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('grade', sa.String(50)),
        sa.Column('density_g_cm3', sa.Numeric(10, 3)),
        sa.Column('hardness_hb', sa.Integer()),
        sa.Column('tensile_strength_mpa', sa.Integer()),
        sa.Column('machinability_rating', sa.Integer()),
        sa.Column('cutting_speed_m_min', sa.Numeric(10, 2)),
        sa.Column('feed_rate_mm_tooth', sa.Numeric(10, 4)),
        sa.Column('properties', postgresql.JSONB()),
        sa.Column('cost_per_kg', sa.Numeric(10, 2)),
        sa.Column('supplier', sa.String(255)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('machinability_rating >= 0 AND machinability_rating <= 100', name='ck_materials_machinability_valid')
    )
    op.create_index('idx_materials_category', 'materials', ['category'])
    op.create_index('idx_materials_name', 'materials', ['name'])
    op.create_index('idx_materials_properties', 'materials', ['properties'], postgresql_using='gin', postgresql_where='properties IS NOT NULL')

    # Create tools table
    op.create_table(
        'tools',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('type', postgresql.ENUM('endmill_flat', 'endmill_ball', 'endmill_bull', 'endmill_chamfer', 'endmill_taper', 'face_mill', 'slot_mill', 'drill_twist', 'drill_center', 'drill_spot', 'drill_peck', 'drill_gun', 'reamer', 'tap', 'thread_mill', 'boring_bar', 'countersink', 'counterbore', 'engraver', 'probe', name='tool_type'), nullable=False),
        sa.Column('material', postgresql.ENUM('hss', 'carbide', 'carbide_coated', 'ceramic', 'cbn', 'pcd', 'cobalt', name='tool_material')),
        sa.Column('coating', sa.String(100)),
        sa.Column('manufacturer', sa.String(100)),
        sa.Column('part_number', sa.String(100)),
        sa.Column('diameter_mm', sa.Numeric(10, 3)),
        sa.Column('flute_count', sa.Integer()),
        sa.Column('flute_length_mm', sa.Numeric(10, 2)),
        sa.Column('overall_length_mm', sa.Numeric(10, 2)),
        sa.Column('shank_diameter_mm', sa.Numeric(10, 2)),
        sa.Column('corner_radius_mm', sa.Numeric(10, 3)),
        sa.Column('helix_angle_deg', sa.Numeric(5, 2)),
        sa.Column('max_depth_of_cut_mm', sa.Numeric(10, 2)),
        sa.Column('specifications', postgresql.JSONB()),
        sa.Column('tool_life_minutes', sa.Integer()),
        sa.Column('cost', sa.Numeric(10, 2)),
        sa.Column('quantity_available', sa.Integer(), server_default='0'),
        sa.Column('minimum_stock', sa.Integer(), server_default='0'),
        sa.Column('location', sa.String(100)),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )
    op.create_index('idx_tools_type', 'tools', ['type'])
    op.create_index('idx_tools_material', 'tools', ['material'], postgresql_where='material IS NOT NULL')
    op.create_index('idx_tools_part_number', 'tools', ['part_number'], postgresql_where='part_number IS NOT NULL')
    op.create_index('idx_tools_diameter', 'tools', ['diameter_mm'], postgresql_where='diameter_mm IS NOT NULL')
    op.create_index('idx_tools_inventory', 'tools', ['quantity_available'], postgresql_where='quantity_available < minimum_stock')

    # Create notifications table
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type', postgresql.ENUM('job_completed', 'job_failed', 'job_warning', 'system_update', 'system_maintenance', 'system_alert', 'license_expiring', 'license_expired', 'license_renewed', 'invoice_created', 'payment_due', 'payment_received', 'payment_failed', 'security_alert', 'login_new_device', 'password_reset', name='notification_type'), nullable=False),
        sa.Column('severity', postgresql.ENUM('info', 'warning', 'error', 'critical', name='notification_severity'), nullable=False, server_default='info'),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('data', postgresql.JSONB()),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('read_at', sa.DateTime(timezone=True)),
        sa.Column('action_url', sa.String(1024)),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )
    op.create_index('idx_notifications_user_id_unread', 'notifications', ['user_id', 'created_at'], postgresql_where='is_read = false')
    op.create_index('idx_notifications_expires_at', 'notifications', ['expires_at'], postgresql_where='expires_at IS NOT NULL')
    op.create_index('idx_notifications_created_at', 'notifications', ['created_at'])

    # Create erp_mes_sync table
    op.create_table(
        'erp_mes_sync',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('external_system', sa.String(100), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('external_id', sa.String(255), nullable=False),
        sa.Column('sync_direction', postgresql.ENUM('inbound', 'outbound', 'bidirectional', name='sync_direction'), nullable=False),
        sa.Column('sync_status', postgresql.ENUM('pending', 'in_progress', 'synced', 'failed', 'conflict', 'skipped', name='sync_status'), nullable=False),
        sa.Column('sync_data', postgresql.JSONB()),
        sa.Column('error_message', sa.Text()),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('synced_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )
    op.create_index('idx_erp_mes_sync_external', 'erp_mes_sync', ['external_system', 'external_id'])
    op.create_index('idx_erp_mes_sync_entity', 'erp_mes_sync', ['entity_type', 'entity_id'])
    op.create_index('idx_erp_mes_sync_status', 'erp_mes_sync', ['sync_status'], postgresql_where="sync_status != 'synced'")

    # Create invoices table
    op.create_table(
        'invoices',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('invoice_number', sa.String(50), unique=True, nullable=False),
        sa.Column('type', postgresql.ENUM('subscription', 'usage', 'one_time', 'credit', 'adjustment', name='invoice_type'), nullable=False),
        sa.Column('status', postgresql.ENUM('draft', 'sent', 'viewed', 'paid', 'partial', 'overdue', 'cancelled', 'refunded', name='invoice_status'), nullable=False),
        sa.Column('currency', postgresql.ENUM('TRY', 'USD', 'EUR', name='currency'), nullable=False, server_default='TRY'),
        sa.Column('subtotal', sa.Numeric(12, 2), nullable=False),
        sa.Column('tax_rate', sa.Numeric(5, 2), nullable=False, server_default='20.00'),
        sa.Column('tax_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('total', sa.Numeric(12, 2), nullable=False),
        sa.Column('line_items', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('billing_period_start', sa.Date()),
        sa.Column('billing_period_end', sa.Date()),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True)),
        sa.Column('payment_method', sa.String(50)),
        sa.Column('notes', sa.String(1000)),
        sa.Column('pdf_s3_key', sa.String(1024)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('total >= 0', name='ck_invoices_total_positive'),
        sa.CheckConstraint('tax_rate >= 0 AND tax_rate <= 100', name='ck_invoices_tax_rate_valid')
    )
    op.create_index('idx_invoices_user_id', 'invoices', ['user_id'])
    op.create_index('idx_invoices_number', 'invoices', ['invoice_number'])
    op.create_index('idx_invoices_status', 'invoices', ['status'], postgresql_where="status != 'paid'")
    op.create_index('idx_invoices_due_date', 'invoices', ['due_date'], postgresql_where="status IN ('sent', 'overdue')")

    # Create payments table
    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('invoice_id', sa.Integer(), sa.ForeignKey('invoices.id', ondelete='RESTRICT')),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('provider_ref', sa.String(255), unique=True, nullable=False),
        sa.Column('method', sa.String(50), nullable=False),
        sa.Column('currency', postgresql.ENUM('TRY', 'USD', 'EUR', name='currency'), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('fee', sa.Numeric(10, 2), server_default='0'),
        sa.Column('status', postgresql.ENUM('pending', 'processing', 'completed', 'failed', 'cancelled', 'refunded', 'partial_refund', 'disputed', name='payment_status'), nullable=False),
        sa.Column('metadata', postgresql.JSONB()),
        sa.Column('refund_amount', sa.Numeric(12, 2), server_default='0'),
        sa.Column('refund_reason', sa.Text()),
        sa.Column('processed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )
    op.create_index('idx_payments_invoice_id', 'payments', ['invoice_id'], postgresql_where='invoice_id IS NOT NULL')
    op.create_index('idx_payments_user_id', 'payments', ['user_id'])
    op.create_index('idx_payments_provider_ref', 'payments', ['provider_ref'])
    op.create_index('idx_payments_status', 'payments', ['status'], postgresql_where="status = 'pending'")

    # Create audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('sessions.id', ondelete='SET NULL')),
        sa.Column('action', postgresql.ENUM('auth_login', 'auth_logout', 'auth_failed', 'auth_token_refresh', 'user_create', 'user_update', 'user_delete', 'user_password_change', 'create', 'read', 'update', 'delete', 'export', 'import', 'job_start', 'job_cancel', 'job_retry', 'config_change', 'backup_create', 'backup_restore', name='audit_action'), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', sa.Integer()),
        sa.Column('entity_data', postgresql.JSONB()),
        sa.Column('changes', postgresql.JSONB()),
        sa.Column('ip_address', postgresql.INET()),
        sa.Column('user_agent', sa.Text()),
        sa.Column('chain_hash', sa.String(64), unique=True, nullable=False),
        sa.Column('prev_chain_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )
    op.create_index('idx_audit_logs_user_id', 'audit_logs', ['user_id'], postgresql_where='user_id IS NOT NULL')
    op.create_index('idx_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('idx_audit_logs_entity', 'audit_logs', ['entity_type', 'entity_id'])
    op.create_index('idx_audit_logs_created_at', 'audit_logs', ['created_at'])
    op.create_index('idx_audit_logs_chain_hash', 'audit_logs', ['chain_hash'])

    # Create security_events table
    op.create_table(
        'security_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('event_type', postgresql.ENUM('login_failed', 'login_suspicious', 'brute_force', 'account_locked', 'access_denied', 'privilege_escalation', 'data_breach', 'sql_injection', 'xss_attempt', 'file_upload_blocked', 'rate_limit_exceeded', 'ddos_detected', 'vulnerability_scan', name='security_event_type'), nullable=False),
        sa.Column('severity', postgresql.ENUM('low', 'medium', 'high', 'critical', name='security_severity'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('ip_address', postgresql.INET()),
        sa.Column('details', postgresql.JSONB(), nullable=False),
        sa.Column('resolved', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('resolved_at', sa.DateTime(timezone=True)),
        sa.Column('resolved_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )
    op.create_index('idx_security_events_type', 'security_events', ['event_type'])
    op.create_index('idx_security_events_severity', 'security_events', ['severity'], postgresql_where='resolved = false')
    op.create_index('idx_security_events_user_id', 'security_events', ['user_id'], postgresql_where='user_id IS NOT NULL')
    op.create_index('idx_security_events_ip_address', 'security_events', ['ip_address'])
    op.create_index('idx_security_events_unresolved', 'security_events', ['created_at'], postgresql_where='resolved = false')

    # Create canonical JSON functions
    op.execute("""
        CREATE OR REPLACE FUNCTION canonical_json(data JSONB)
        RETURNS TEXT AS $$
        DECLARE
            result TEXT;
        BEGIN
            result := data::TEXT;
            result := REPLACE(result, ': ', ':');
            result := REPLACE(result, ', ', ',');
            RETURN result;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION compute_json_hash(data JSONB)
        RETURNS TEXT AS $$
        BEGIN
            RETURN encode(
                digest(canonical_json(data), 'sha256'),
                'hex'
            );
        END;
        $$ LANGUAGE plpgsql IMMUTABLE;
    """)

    # Create audit hash chain trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION compute_audit_chain_hash()
        RETURNS TRIGGER AS $$
        DECLARE
            prev_hash TEXT;
            payload JSONB;
            canonical TEXT;
        BEGIN
            -- Get previous entry's hash
            SELECT chain_hash INTO prev_hash
            FROM audit_logs
            WHERE id < NEW.id
            ORDER BY id DESC
            LIMIT 1;
            
            -- Use genesis hash if first entry
            IF prev_hash IS NULL THEN
                prev_hash := REPEAT('0', 64);
            END IF;
            
            -- Build payload
            payload := jsonb_build_object(
                'id', NEW.id,
                'user_id', NEW.user_id,
                'action', NEW.action,
                'entity_type', NEW.entity_type,
                'entity_id', NEW.entity_id,
                'entity_data', NEW.entity_data,
                'changes', NEW.changes,
                'ip_address', COALESCE(NEW.ip_address::TEXT, ''),
                'user_agent', COALESCE(NEW.user_agent, ''),
                'session_id', NEW.session_id,
                'created_at', TO_CHAR(NEW.created_at, 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
            );
            
            -- Get canonical JSON representation
            canonical := canonical_json(payload);
            
            -- Compute chain hash
            NEW.prev_chain_hash := prev_hash;
            NEW.chain_hash := encode(
                digest(prev_hash || canonical, 'sha256'),
                'hex'
            );
            
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER audit_logs_hash_chain
        BEFORE INSERT ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION compute_audit_chain_hash();
    """)


def downgrade():
    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS audit_logs_hash_chain ON audit_logs")
    
    # Drop functions
    op.execute("DROP FUNCTION IF EXISTS compute_audit_chain_hash()")
    op.execute("DROP FUNCTION IF EXISTS compute_json_hash(JSONB)")
    op.execute("DROP FUNCTION IF EXISTS canonical_json(JSONB)")
    
    # Drop tables in reverse order (respecting foreign key dependencies)
    op.drop_table('security_events')
    op.drop_table('audit_logs')
    op.drop_table('payments')
    op.drop_table('invoices')
    op.drop_table('erp_mes_sync')
    op.drop_table('notifications')
    op.drop_table('tools')
    op.drop_table('materials')
    op.drop_table('machines')
    op.drop_table('sim_runs')
    op.drop_table('cam_runs')
    op.drop_table('models')
    op.drop_table('licenses')
    op.drop_table('sessions')
    
    # Remove added columns from existing tables
    op.drop_column('users', 'metadata')
    op.drop_column('users', 'updated_at')
    op.drop_column('users', 'last_login_at')
    op.drop_column('users', 'is_verified')
    op.drop_column('users', 'is_active')
    op.drop_column('users', 'timezone')
    op.drop_column('users', 'address')
    op.drop_column('users', 'tax_no')
    op.drop_column('users', 'company_name')
    op.drop_column('users', 'phone')
    
    op.drop_column('jobs', 'updated_at')
    op.drop_column('jobs', 'created_at')
    op.drop_column('jobs', 'timeout_seconds')
    op.drop_column('jobs', 'max_retries')
    op.drop_column('jobs', 'retry_count')
    op.drop_column('jobs', 'error_message')
    op.drop_column('jobs', 'error_code')
    op.drop_column('jobs', 'progress')
    op.drop_column('jobs', 'output_data')
    op.drop_column('jobs', 'input_params')
    op.drop_column('jobs', 'task_id')
    op.drop_column('jobs', 'priority')
    op.drop_column('jobs', 'user_id')
    
    op.drop_column('artefacts', 'created_at')
    op.drop_column('artefacts', 'expires_at')
    op.drop_column('artefacts', 'metadata')
    op.drop_column('artefacts', 'mime_type')
    op.drop_column('artefacts', 'file_size')
    op.drop_column('artefacts', 'name')
    
    # Drop enum types
    op.execute("DROP TYPE IF EXISTS security_severity")
    op.execute("DROP TYPE IF EXISTS security_event_type")
    op.execute("DROP TYPE IF EXISTS audit_action")
    op.execute("DROP TYPE IF EXISTS notification_severity")
    op.execute("DROP TYPE IF EXISTS notification_type")
    op.execute("DROP TYPE IF EXISTS currency")
    op.execute("DROP TYPE IF EXISTS payment_status")
    op.execute("DROP TYPE IF EXISTS invoice_status")
    op.execute("DROP TYPE IF EXISTS invoice_type")
    op.execute("DROP TYPE IF EXISTS model_type")
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP TYPE IF EXISTS job_type")
    op.execute("DROP TYPE IF EXISTS license_status")
    op.execute("DROP TYPE IF EXISTS license_type")
    op.execute("DROP TYPE IF EXISTS locale")
    op.execute("DROP TYPE IF EXISTS user_role")
    op.execute("DROP TYPE IF EXISTS sync_status")
    op.execute("DROP TYPE IF EXISTS sync_direction")
    op.execute("DROP TYPE IF EXISTS machine_type")
    op.execute("DROP TYPE IF EXISTS tool_type")
    op.execute("DROP TYPE IF EXISTS tool_material")
    op.execute("DROP TYPE IF EXISTS material_category")