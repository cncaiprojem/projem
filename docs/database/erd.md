# Entity Relationship Diagram (ERD) Documentation

## Overview
This document defines the complete database schema for the FreeCAD-based CNC/CAM/CAD Production Platform. The schema is designed for PostgreSQL 17.6 with a focus on scalability, security, and production readiness.

## Core Tables

### users
User accounts and authentication information.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Unique user identifier |
| email | VARCHAR(255) | UNIQUE, NOT NULL, INDEX | User email address |
| phone | VARCHAR(20) | UNIQUE, INDEX | User phone number (Turkish format) |
| password_hash | VARCHAR(255) | | Bcrypt password hash |
| role | VARCHAR(50) | NOT NULL, DEFAULT 'engineer' | User role (enum: admin, engineer, operator, viewer) |
| company_name | VARCHAR(255) | | Company/organization name |
| tax_no | VARCHAR(20) | INDEX | Turkish tax number (VKN/TCKN) |
| address | TEXT | | Billing address |
| locale | VARCHAR(10) | NOT NULL, DEFAULT 'tr' | User interface language |
| timezone | VARCHAR(50) | DEFAULT 'Europe/Istanbul' | User timezone |
| is_active | BOOLEAN | DEFAULT true | Account active status |
| is_verified | BOOLEAN | DEFAULT false | Email verification status |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Account creation timestamp |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Last update timestamp |
| last_login_at | TIMESTAMP | | Last successful login |
| metadata | JSONB | | Additional user metadata (GIN indexed) |

**Indexes:**
- `idx_users_email` on (email)
- `idx_users_phone` on (phone) WHERE phone IS NOT NULL
- `idx_users_tax_no` on (tax_no) WHERE tax_no IS NOT NULL
- `idx_users_created_at` on (created_at DESC)
- `idx_users_metadata` GIN index on (metadata) WHERE metadata IS NOT NULL

### sessions
User authentication sessions with JWT refresh tokens.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Session identifier |
| user_id | INTEGER | FOREIGN KEY (users.id) ON DELETE CASCADE, NOT NULL | User reference |
| refresh_token_hash | VARCHAR(255) | UNIQUE, NOT NULL | SHA256 hash of refresh token |
| access_token_jti | VARCHAR(255) | INDEX | JWT ID of current access token |
| ip_address | INET | | Client IP address |
| user_agent | TEXT | | Client user agent string |
| device_id | VARCHAR(255) | INDEX | Optional device identifier |
| expires_at | TIMESTAMP | NOT NULL, INDEX | Session expiration |
| revoked_at | TIMESTAMP | INDEX | Revocation timestamp if revoked |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Session creation |

**Indexes:**
- `idx_sessions_user_id` on (user_id)
- `idx_sessions_refresh_token_hash` on (refresh_token_hash)
- `idx_sessions_expires_at` on (expires_at) WHERE revoked_at IS NULL
- `idx_sessions_device_id` on (device_id) WHERE device_id IS NOT NULL

### licenses
Software licensing and subscription management.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | License identifier |
| user_id | INTEGER | FOREIGN KEY (users.id) ON DELETE RESTRICT, NOT NULL | License owner |
| type | VARCHAR(50) | NOT NULL | License type (enum: trial, basic, professional, enterprise) |
| status | VARCHAR(50) | NOT NULL | Status (enum: active, expired, suspended, cancelled) |
| seats | INTEGER | DEFAULT 1, CHECK (seats > 0) | Number of seats/users |
| features | JSONB | NOT NULL | Enabled features configuration |
| starts_at | TIMESTAMP | NOT NULL | License validity start |
| ends_at | TIMESTAMP | NOT NULL, INDEX | License expiration |
| auto_renew | BOOLEAN | DEFAULT false | Auto-renewal flag |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Last update |

**Indexes:**
- `idx_licenses_user_id` on (user_id)
- `idx_licenses_status` on (status) WHERE status = 'active'
- `idx_licenses_ends_at` on (ends_at) WHERE status = 'active'
- `idx_licenses_features` GIN index on (features)

### models
3D CAD model storage and versioning.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Model identifier |
| user_id | INTEGER | FOREIGN KEY (users.id) ON DELETE RESTRICT, NOT NULL | Model owner |
| project_id | INTEGER | FOREIGN KEY (projects.id) ON DELETE CASCADE | Associated project |
| name | VARCHAR(255) | NOT NULL | Model name |
| description | TEXT | | Model description |
| type | VARCHAR(50) | NOT NULL | Model type (enum: part, assembly, drawing) |
| file_format | VARCHAR(20) | NOT NULL | Format (STEP, FCStd, STL, etc.) |
| s3_key | VARCHAR(1024) | UNIQUE, NOT NULL | S3 storage key |
| file_size | BIGINT | NOT NULL | File size in bytes |
| sha256_hash | CHAR(64) | NOT NULL, INDEX | File content hash |
| version | INTEGER | NOT NULL, DEFAULT 1 | Version number |
| parent_model_id | INTEGER | FOREIGN KEY (models.id) ON DELETE SET NULL | Parent for versioning |
| metadata | JSONB | | Model metadata (dimensions, materials, etc.) |
| thumbnail_s3_key | VARCHAR(1024) | | Thumbnail image S3 key |
| is_deleted | BOOLEAN | DEFAULT false | Soft delete flag |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Last update |

**Indexes:**
- `idx_models_user_id` on (user_id)
- `idx_models_project_id` on (project_id) WHERE project_id IS NOT NULL
- `idx_models_sha256_hash` on (sha256_hash)
- `idx_models_created_at` on (created_at DESC)
- `idx_models_metadata` GIN index on (metadata) WHERE metadata IS NOT NULL

### jobs
Asynchronous job queue and processing.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Job identifier |
| idempotency_key | VARCHAR(255) | UNIQUE, INDEX | Idempotency key for deduplication |
| user_id | INTEGER | FOREIGN KEY (users.id) ON DELETE RESTRICT | Job owner |
| type | VARCHAR(50) | NOT NULL, INDEX | Job type (enum: cad_generate, cam_process, sim_run, gcode_post) |
| status | VARCHAR(50) | NOT NULL, INDEX | Status (enum: pending, queued, running, completed, failed, cancelled) |
| priority | INTEGER | DEFAULT 0 | Job priority (higher = more important) |
| task_id | VARCHAR(255) | INDEX | Celery task ID |
| input_params | JSONB | NOT NULL | Input parameters |
| output_data | JSONB | | Output/result data |
| progress | INTEGER | DEFAULT 0, CHECK (progress >= 0 AND progress <= 100) | Progress percentage |
| started_at | TIMESTAMP | INDEX | Processing start time |
| finished_at | TIMESTAMP | INDEX | Processing end time |
| error_code | VARCHAR(100) | | Error code if failed |
| error_message | TEXT | | Error details |
| retry_count | INTEGER | DEFAULT 0 | Number of retries |
| max_retries | INTEGER | DEFAULT 3 | Maximum retry attempts |
| timeout_seconds | INTEGER | DEFAULT 3600 | Job timeout |
| metrics | JSONB | | Performance metrics |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW(), INDEX | Creation timestamp |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Last update |

**Indexes:**
- `idx_jobs_idempotency_key` on (idempotency_key) WHERE idempotency_key IS NOT NULL
- `idx_jobs_user_id` on (user_id) WHERE user_id IS NOT NULL
- `idx_jobs_type_status` on (type, status)
- `idx_jobs_status` on (status) WHERE status IN ('pending', 'queued', 'running')
- `idx_jobs_task_id` on (task_id) WHERE task_id IS NOT NULL
- `idx_jobs_created_at` on (created_at DESC)
- `idx_jobs_started_at` on (started_at DESC) WHERE started_at IS NOT NULL

## Operational Tables

### cam_runs
CAM (Computer-Aided Manufacturing) processing runs.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | CAM run identifier |
| job_id | INTEGER | FOREIGN KEY (jobs.id) ON DELETE RESTRICT, NOT NULL | Associated job |
| model_id | INTEGER | FOREIGN KEY (models.id) ON DELETE RESTRICT, NOT NULL | Input model |
| setup_id | INTEGER | FOREIGN KEY (setups.id) ON DELETE RESTRICT | Setup configuration |
| strategy | VARCHAR(100) | NOT NULL | CAM strategy |
| tool_paths | JSONB | | Generated tool paths |
| cutting_params | JSONB | NOT NULL | Cutting parameters |
| estimated_time_seconds | INTEGER | | Estimated machining time |
| material_removal_cc | NUMERIC(10,2) | | Material removal volume |
| output_s3_key | VARCHAR(1024) | | Output file S3 key |
| status | VARCHAR(50) | NOT NULL | Processing status |
| error_details | TEXT | | Error information if failed |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Creation timestamp |
| completed_at | TIMESTAMP | | Completion timestamp |

**Indexes:**
- `idx_cam_runs_job_id` on (job_id)
- `idx_cam_runs_model_id` on (model_id)
- `idx_cam_runs_setup_id` on (setup_id) WHERE setup_id IS NOT NULL
- `idx_cam_runs_status` on (status) WHERE status != 'completed'

### sim_runs
Simulation runs for collision detection and verification.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Simulation run identifier |
| job_id | INTEGER | FOREIGN KEY (jobs.id) ON DELETE RESTRICT, NOT NULL | Associated job |
| cam_run_id | INTEGER | FOREIGN KEY (cam_runs.id) ON DELETE CASCADE | CAM run reference |
| type | VARCHAR(50) | NOT NULL | Simulation type (collision, material_removal, etc.) |
| machine_id | INTEGER | FOREIGN KEY (machines.id) ON DELETE RESTRICT | Machine configuration |
| collision_count | INTEGER | DEFAULT 0 | Number of collisions detected |
| collision_details | JSONB | | Detailed collision information |
| material_removal_accuracy | NUMERIC(5,2) | | Accuracy percentage |
| simulation_time_ms | INTEGER | | Simulation execution time |
| video_s3_key | VARCHAR(1024) | | Simulation video S3 key |
| report_s3_key | VARCHAR(1024) | | Report file S3 key |
| status | VARCHAR(50) | NOT NULL | Status (passed, failed, warnings) |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Creation timestamp |
| completed_at | TIMESTAMP | | Completion timestamp |

**Indexes:**
- `idx_sim_runs_job_id` on (job_id)
- `idx_sim_runs_cam_run_id` on (cam_run_id) WHERE cam_run_id IS NOT NULL
- `idx_sim_runs_machine_id` on (machine_id) WHERE machine_id IS NOT NULL
- `idx_sim_runs_status` on (status)

### artefacts
File artifacts generated by jobs.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Artifact identifier |
| job_id | INTEGER | FOREIGN KEY (jobs.id) ON DELETE CASCADE, NOT NULL | Parent job |
| type | VARCHAR(50) | NOT NULL | Artifact type (model, gcode, report, etc.) |
| name | VARCHAR(255) | NOT NULL | Display name |
| s3_key | VARCHAR(1024) | UNIQUE, NOT NULL | S3 storage key |
| file_size | BIGINT | NOT NULL | File size in bytes |
| mime_type | VARCHAR(100) | | MIME type |
| sha256 | CHAR(64) | INDEX | Content hash |
| metadata | JSONB | | Additional metadata |
| expires_at | TIMESTAMP | | Expiration for temporary files |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Creation timestamp |

**Indexes:**
- `idx_artefacts_job_id` on (job_id)
- `idx_artefacts_s3_key` on (s3_key)
- `idx_artefacts_sha256` on (sha256) WHERE sha256 IS NOT NULL
- `idx_artefacts_expires_at` on (expires_at) WHERE expires_at IS NOT NULL

### notifications
User notifications and alerts.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Notification identifier |
| user_id | INTEGER | FOREIGN KEY (users.id) ON DELETE CASCADE, NOT NULL | Recipient user |
| type | VARCHAR(50) | NOT NULL | Notification type |
| severity | VARCHAR(20) | NOT NULL, DEFAULT 'info' | Severity (info, warning, error, critical) |
| title | VARCHAR(255) | NOT NULL | Notification title |
| message | TEXT | NOT NULL | Notification content |
| data | JSONB | | Additional data/context |
| is_read | BOOLEAN | DEFAULT false, INDEX | Read status |
| read_at | TIMESTAMP | | Read timestamp |
| action_url | VARCHAR(1024) | | Optional action URL |
| expires_at | TIMESTAMP | INDEX | Expiration timestamp |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW(), INDEX | Creation timestamp |

**Indexes:**
- `idx_notifications_user_id_unread` on (user_id, created_at DESC) WHERE is_read = false
- `idx_notifications_expires_at` on (expires_at) WHERE expires_at IS NOT NULL
- `idx_notifications_created_at` on (created_at DESC)

### erp_mes_sync
ERP/MES system synchronization tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Sync record identifier |
| external_system | VARCHAR(100) | NOT NULL | System name (SAP, Oracle, etc.) |
| entity_type | VARCHAR(50) | NOT NULL | Entity type (order, material, etc.) |
| entity_id | INTEGER | NOT NULL | Internal entity ID |
| external_id | VARCHAR(255) | NOT NULL, INDEX | External system ID |
| sync_direction | VARCHAR(20) | NOT NULL | Direction (inbound, outbound) |
| sync_status | VARCHAR(50) | NOT NULL | Status (pending, synced, failed) |
| sync_data | JSONB | | Synchronized data |
| error_message | TEXT | | Error details if failed |
| retry_count | INTEGER | DEFAULT 0 | Sync retry attempts |
| synced_at | TIMESTAMP | | Successful sync timestamp |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Last update |

**Indexes:**
- `idx_erp_mes_sync_external` on (external_system, external_id)
- `idx_erp_mes_sync_entity` on (entity_type, entity_id)
- `idx_erp_mes_sync_status` on (sync_status) WHERE sync_status != 'synced'

## Billing Tables

### invoices
Customer invoices and billing.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Invoice identifier |
| user_id | INTEGER | FOREIGN KEY (users.id) ON DELETE RESTRICT, NOT NULL | Customer |
| invoice_number | VARCHAR(50) | UNIQUE, NOT NULL | Invoice number |
| type | VARCHAR(50) | NOT NULL | Invoice type (subscription, usage, one_time) |
| status | VARCHAR(50) | NOT NULL | Status (draft, sent, paid, overdue, cancelled) |
| currency | CHAR(3) | NOT NULL, DEFAULT 'TRY', CHECK (currency IN ('TRY', 'USD', 'EUR')) | Currency code |
| subtotal | NUMERIC(12,2) | NOT NULL | Subtotal amount |
| tax_rate | NUMERIC(5,2) | NOT NULL, DEFAULT 20.00 | Tax rate (KDV) |
| tax_amount | NUMERIC(12,2) | NOT NULL | Tax amount |
| total | NUMERIC(12,2) | NOT NULL | Total amount |
| line_items | JSONB | NOT NULL | Invoice line items |
| billing_period_start | DATE | | Billing period start |
| billing_period_end | DATE | | Billing period end |
| due_date | DATE | NOT NULL, INDEX | Payment due date |
| paid_at | TIMESTAMP | | Payment timestamp |
| payment_method | VARCHAR(50) | | Payment method used |
| notes | TEXT | | Invoice notes |
| pdf_s3_key | VARCHAR(1024) | | Invoice PDF S3 key |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Last update |

**Indexes:**
- `idx_invoices_user_id` on (user_id)
- `idx_invoices_number` on (invoice_number)
- `idx_invoices_status` on (status) WHERE status != 'paid'
- `idx_invoices_due_date` on (due_date) WHERE status IN ('sent', 'overdue')

### payments
Payment transactions and records.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Payment identifier |
| invoice_id | INTEGER | FOREIGN KEY (invoices.id) ON DELETE RESTRICT | Related invoice |
| user_id | INTEGER | FOREIGN KEY (users.id) ON DELETE RESTRICT, NOT NULL | Payer |
| provider | VARCHAR(50) | NOT NULL | Payment provider (stripe, iyzico, etc.) |
| provider_ref | VARCHAR(255) | UNIQUE, NOT NULL | Provider transaction ID |
| method | VARCHAR(50) | NOT NULL | Payment method (card, transfer, etc.) |
| currency | CHAR(3) | NOT NULL, CHECK (currency IN ('TRY', 'USD', 'EUR')) | Currency |
| amount | NUMERIC(12,2) | NOT NULL | Payment amount |
| fee | NUMERIC(10,2) | DEFAULT 0 | Transaction fee |
| status | VARCHAR(50) | NOT NULL | Status (pending, completed, failed, refunded) |
| metadata | JSONB | | Provider-specific metadata |
| refund_amount | NUMERIC(12,2) | DEFAULT 0 | Refunded amount if any |
| refund_reason | TEXT | | Refund reason |
| processed_at | TIMESTAMP | | Processing timestamp |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Creation timestamp |

**Indexes:**
- `idx_payments_invoice_id` on (invoice_id) WHERE invoice_id IS NOT NULL
- `idx_payments_user_id` on (user_id)
- `idx_payments_provider_ref` on (provider_ref)
- `idx_payments_status` on (status) WHERE status = 'pending'

## Security & Audit Tables

### audit_logs
Comprehensive audit trail with hash-chain integrity.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Audit entry identifier |
| user_id | INTEGER | FOREIGN KEY (users.id) ON DELETE SET NULL | Acting user |
| action | VARCHAR(100) | NOT NULL, INDEX | Action performed |
| entity_type | VARCHAR(50) | NOT NULL, INDEX | Entity type affected |
| entity_id | INTEGER | INDEX | Entity ID affected |
| entity_data | JSONB | | Entity state snapshot |
| changes | JSONB | | Field-level changes |
| ip_address | INET | | Client IP |
| user_agent | TEXT | | Client user agent |
| session_id | INTEGER | FOREIGN KEY (sessions.id) ON DELETE SET NULL | Session reference |
| chain_hash | CHAR(64) | UNIQUE, NOT NULL | Hash chain value |
| prev_chain_hash | CHAR(64) | NOT NULL | Previous entry hash |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW(), INDEX | Entry timestamp |

**Indexes:**
- `idx_audit_logs_user_id` on (user_id) WHERE user_id IS NOT NULL
- `idx_audit_logs_action` on (action)
- `idx_audit_logs_entity` on (entity_type, entity_id)
- `idx_audit_logs_created_at` on (created_at DESC)
- `idx_audit_logs_chain_hash` on (chain_hash)

**Note:** chain_hash = SHA256(prev_chain_hash || canonical_json(record))

### security_events
Security-related events and incidents.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Event identifier |
| event_type | VARCHAR(100) | NOT NULL, INDEX | Event type |
| severity | VARCHAR(20) | NOT NULL, INDEX | Severity level |
| user_id | INTEGER | FOREIGN KEY (users.id) ON DELETE SET NULL | Related user |
| ip_address | INET | INDEX | Source IP |
| details | JSONB | NOT NULL | Event details |
| resolved | BOOLEAN | DEFAULT false, INDEX | Resolution status |
| resolved_at | TIMESTAMP | | Resolution timestamp |
| resolved_by | INTEGER | FOREIGN KEY (users.id) ON DELETE SET NULL | Resolver user |
| notes | TEXT | | Resolution notes |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW(), INDEX | Event timestamp |

**Indexes:**
- `idx_security_events_type` on (event_type)
- `idx_security_events_severity` on (severity) WHERE resolved = false
- `idx_security_events_user_id` on (user_id) WHERE user_id IS NOT NULL
- `idx_security_events_ip_address` on (ip_address)
- `idx_security_events_unresolved` on (created_at DESC) WHERE resolved = false

## Reference Tables

### machines
CNC machine configurations.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Machine identifier |
| name | VARCHAR(255) | NOT NULL | Machine name |
| manufacturer | VARCHAR(100) | | Manufacturer |
| model | VARCHAR(100) | | Model number |
| type | VARCHAR(50) | NOT NULL | Machine type (mill, lathe, router, etc.) |
| axes | INTEGER | NOT NULL, CHECK (axes >= 3 AND axes <= 9) | Number of axes |
| work_envelope_x_mm | NUMERIC(10,2) | NOT NULL | X-axis travel |
| work_envelope_y_mm | NUMERIC(10,2) | NOT NULL | Y-axis travel |
| work_envelope_z_mm | NUMERIC(10,2) | NOT NULL | Z-axis travel |
| spindle_max_rpm | INTEGER | NOT NULL | Maximum spindle speed |
| spindle_power_kw | NUMERIC(10,2) | | Spindle power |
| tool_capacity | INTEGER | | Tool changer capacity |
| controller | VARCHAR(100) | | Controller type (Fanuc, Siemens, etc.) |
| post_processor | VARCHAR(100) | NOT NULL | Post-processor name |
| hourly_rate | NUMERIC(10,2) | | Operating cost per hour |
| specifications | JSONB | | Additional specifications |
| is_active | BOOLEAN | DEFAULT true | Active status |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Last update |

**Indexes:**
- `idx_machines_type` on (type)
- `idx_machines_active` on (is_active, name) WHERE is_active = true

### materials
Material database for machining.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Material identifier |
| category | VARCHAR(50) | NOT NULL, INDEX | Category (metal, plastic, wood, etc.) |
| name | VARCHAR(100) | NOT NULL | Material name |
| grade | VARCHAR(50) | | Material grade/alloy |
| density_g_cm3 | NUMERIC(10,3) | | Density |
| hardness_hb | INTEGER | | Brinell hardness |
| tensile_strength_mpa | INTEGER | | Tensile strength |
| machinability_rating | INTEGER | CHECK (machinability_rating >= 0 AND machinability_rating <= 100) | Machinability (0-100) |
| cutting_speed_m_min | NUMERIC(10,2) | | Recommended cutting speed |
| feed_rate_mm_tooth | NUMERIC(10,4) | | Recommended feed rate |
| properties | JSONB | | Additional properties |
| cost_per_kg | NUMERIC(10,2) | | Material cost |
| supplier | VARCHAR(255) | | Preferred supplier |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Last update |

**Indexes:**
- `idx_materials_category` on (category)
- `idx_materials_name` on (name)
- `idx_materials_properties` GIN index on (properties) WHERE properties IS NOT NULL

### tools
Cutting tool inventory.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | SERIAL | PRIMARY KEY | Tool identifier |
| name | VARCHAR(200) | NOT NULL | Tool name |
| type | VARCHAR(50) | NOT NULL, INDEX | Tool type (enum) |
| material | VARCHAR(50) | INDEX | Tool material (enum) |
| coating | VARCHAR(100) | | Coating type |
| manufacturer | VARCHAR(100) | | Manufacturer |
| part_number | VARCHAR(100) | INDEX | Manufacturer part number |
| diameter_mm | NUMERIC(10,3) | | Tool diameter |
| flute_count | INTEGER | | Number of flutes |
| flute_length_mm | NUMERIC(10,2) | | Flute/cutting length |
| overall_length_mm | NUMERIC(10,2) | | Overall length |
| shank_diameter_mm | NUMERIC(10,2) | | Shank diameter |
| corner_radius_mm | NUMERIC(10,3) | | Corner radius |
| helix_angle_deg | NUMERIC(5,2) | | Helix angle |
| max_depth_of_cut_mm | NUMERIC(10,2) | | Maximum cutting depth |
| specifications | JSONB | | Additional specifications |
| tool_life_minutes | INTEGER | | Expected tool life |
| cost | NUMERIC(10,2) | | Tool cost |
| quantity_available | INTEGER | DEFAULT 0 | Current inventory |
| minimum_stock | INTEGER | DEFAULT 0 | Minimum stock level |
| location | VARCHAR(100) | | Storage location |
| is_active | BOOLEAN | DEFAULT true | Active status |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Last update |

**Indexes:**
- `idx_tools_type` on (type)
- `idx_tools_material` on (material) WHERE material IS NOT NULL
- `idx_tools_part_number` on (part_number) WHERE part_number IS NOT NULL
- `idx_tools_diameter` on (diameter_mm) WHERE diameter_mm IS NOT NULL
- `idx_tools_inventory` on (quantity_available) WHERE quantity_available < minimum_stock

## Relationships Summary

### Foreign Key Relationships
- sessions → users (CASCADE on delete)
- licenses → users (RESTRICT on delete)
- models → users (RESTRICT on delete)
- models → projects (CASCADE on delete)
- models → models (SET NULL on delete for parent)
- jobs → users (RESTRICT on delete)
- cam_runs → jobs (RESTRICT on delete)
- cam_runs → models (RESTRICT on delete)
- cam_runs → setups (RESTRICT on delete)
- sim_runs → jobs (RESTRICT on delete)
- sim_runs → cam_runs (CASCADE on delete)
- sim_runs → machines (RESTRICT on delete)
- artefacts → jobs (CASCADE on delete)
- notifications → users (CASCADE on delete)
- invoices → users (RESTRICT on delete)
- payments → invoices (RESTRICT on delete)
- payments → users (RESTRICT on delete)
- audit_logs → users (SET NULL on delete)
- audit_logs → sessions (SET NULL on delete)
- security_events → users (SET NULL on delete)

## Performance Considerations

1. **JSONB Indexing**: All JSONB columns that are frequently queried have GIN indexes
2. **Partial Indexes**: Used for filtering common query patterns (e.g., active records only)
3. **Composite Indexes**: Created for multi-column queries (type + status combinations)
4. **Timestamp Indexes**: DESC ordering for recent record queries
5. **Conditional Indexes**: WHERE clauses to reduce index size for nullable columns

## Data Integrity Rules

1. **Unique Constraints**: Enforced at database level for critical fields
2. **Check Constraints**: Range validations for numeric fields
3. **Foreign Key Constraints**: Appropriate CASCADE/RESTRICT rules
4. **Not Null Constraints**: Required fields enforced
5. **Default Values**: Sensible defaults for optional fields

## Security Features

1. **Audit Trail**: Hash-chain protected audit logs
2. **Password Storage**: Bcrypt hashed passwords only
3. **Token Storage**: SHA256 hashed refresh tokens
4. **PII Protection**: Sensitive data in separate columns for encryption
5. **Row-Level Security**: Can be implemented via PostgreSQL RLS policies