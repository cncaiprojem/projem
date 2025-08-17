# Database Enumerations Documentation

## Overview
This document defines all enumeration types used in the database schema. These enums ensure data consistency and provide clear constraints for categorical data. All enums are implemented both as PostgreSQL ENUM types and Python Enum classes for full-stack type safety.

## Implementation
- **Database**: PostgreSQL ENUM types for constraint enforcement
- **Backend**: Python Enum classes in `apps/api/app/models/enums.py`
- **Frontend**: TypeScript enums/unions in `apps/web/src/types/`
- **Migration**: Created in `0011_complete_schema.py`

## User & Authentication Enums

### UserRole
Defines user permission levels and access control.

```sql
CREATE TYPE user_role AS ENUM (
    'admin',        -- Full system administration
    'engineer',     -- CAD/CAM design and engineering
    'operator',     -- Machine operation and job execution
    'viewer'        -- Read-only access
);
```

### Locale
Supported user interface languages.

```sql
CREATE TYPE locale AS ENUM (
    'tr',          -- Turkish (default)
    'en',          -- English
    'de'           -- German
);
```

## License & Subscription Enums

### LicenseType
Software license tiers.

```sql
CREATE TYPE license_type AS ENUM (
    'trial',       -- 30-day trial license
    'basic',       -- Basic features, single user
    'professional',-- Advanced features, team collaboration
    'enterprise'   -- Full features, unlimited users
);
```

### LicenseStatus
License lifecycle states.

```sql
CREATE TYPE license_status AS ENUM (
    'active',      -- Currently valid and usable
    'expired',     -- Past expiration date
    'suspended',   -- Temporarily disabled (payment issue)
    'cancelled'    -- Permanently terminated
);
```

## Job Processing Enums

### JobType
Types of processing jobs.

```sql
CREATE TYPE job_type AS ENUM (
    'cad_generate',    -- CAD model generation from parameters
    'cad_import',      -- CAD file import and conversion
    'cad_export',      -- CAD file export to different format
    'cam_process',     -- CAM toolpath generation
    'cam_optimize',    -- Toolpath optimization
    'sim_run',         -- Simulation execution
    'sim_collision',   -- Collision detection only
    'gcode_post',      -- G-code post-processing
    'gcode_verify',    -- G-code verification
    'report_generate', -- Report generation
    'model_repair'     -- Model repair and validation
);
```

### JobStatus
Job execution states.

```sql
CREATE TYPE job_status AS ENUM (
    'pending',     -- Created but not queued
    'queued',      -- In queue waiting for worker
    'running',     -- Currently being processed
    'completed',   -- Successfully completed
    'failed',      -- Failed with error
    'cancelled',   -- Cancelled by user
    'timeout'      -- Exceeded time limit
);
```

### JobPriority
Job queue priority levels.

```sql
CREATE TYPE job_priority AS ENUM (
    'low',         -- Priority value: -10
    'normal',      -- Priority value: 0 (default)
    'high',        -- Priority value: 10
    'critical'     -- Priority value: 20
);
```

## Model & Design Enums

### ModelType
3D model categories.

```sql
CREATE TYPE model_type AS ENUM (
    'part',        -- Single component
    'assembly',    -- Multiple components
    'drawing',     -- 2D technical drawing
    'sketch',      -- 2D sketch/profile
    'mesh'         -- Mesh/STL model
);
```

### FileFormat
Supported file formats.

```sql
CREATE TYPE file_format AS ENUM (
    -- Native formats
    'FCStd',       -- FreeCAD native
    
    -- CAD exchange formats
    'STEP',        -- ISO 10303 STEP
    'IGES',        -- Initial Graphics Exchange
    'BREP',        -- Boundary Representation
    
    -- Mesh formats
    'STL',         -- Stereolithography
    'OBJ',         -- Wavefront Object
    'PLY',         -- Polygon File Format
    
    -- Drawing formats
    'DXF',         -- Drawing Exchange Format
    'SVG',         -- Scalable Vector Graphics
    'PDF',         -- Portable Document Format
    
    -- Other formats
    'GCODE',       -- G-code/NC code
    'JSON'         -- Parameter-based definition
);
```

## CAM & Machining Enums

### CamStrategy
CAM processing strategies.

```sql
CREATE TYPE cam_strategy AS ENUM (
    -- 2.5D strategies
    'face_mill',       -- Face milling
    'pocket_2d',       -- 2D pocket clearing
    'contour_2d',      -- 2D profile contouring
    'drill',           -- Drilling cycles
    'thread_mill',     -- Thread milling
    'engrave',         -- Engraving/marking
    
    -- 3D strategies
    'adaptive_clear',  -- Adaptive clearing
    'pocket_3d',       -- 3D pocket clearing
    'contour_3d',      -- 3D contouring
    'parallel',        -- Parallel finishing
    'radial',          -- Radial machining
    'spiral',          -- Spiral machining
    'morphed_spiral',  -- Morphed spiral
    'project',         -- Projected curves
    'swarf',           -- 5-axis swarf milling
    'flow',            -- Flow machining
    
    -- Specialized
    'rest_machining',  -- Rest material removal
    'pencil',          -- Pencil/corner cleanup
    'scallop',         -- Constant scallop
    'steep_shallow'    -- Steep and shallow
);
```

### ToolType
Cutting tool types.

```sql
CREATE TYPE tool_type AS ENUM (
    -- Milling tools
    'endmill_flat',    -- Flat end mill
    'endmill_ball',    -- Ball nose end mill
    'endmill_bull',    -- Bull nose end mill
    'endmill_chamfer', -- Chamfer mill
    'endmill_taper',   -- Tapered end mill
    'face_mill',       -- Face milling cutter
    'slot_mill',       -- Slot milling cutter
    
    -- Drilling tools
    'drill_twist',     -- Twist drill
    'drill_center',    -- Center drill
    'drill_spot',      -- Spot drill
    'drill_peck',      -- Peck drilling
    'drill_gun',       -- Gun drill
    
    -- Specialized tools
    'reamer',          -- Reamer
    'tap',             -- Threading tap
    'thread_mill',     -- Thread milling cutter
    'boring_bar',      -- Boring bar
    'countersink',     -- Countersink
    'counterbore',     -- Counterbore
    'engraver',        -- Engraving tool
    'probe'            -- Touch probe
);
```

### ToolMaterial
Tool material composition.

```sql
CREATE TYPE tool_material AS ENUM (
    'hss',             -- High Speed Steel
    'carbide',         -- Tungsten Carbide
    'carbide_coated',  -- Coated Carbide
    'ceramic',         -- Ceramic
    'cbn',             -- Cubic Boron Nitride
    'pcd',             -- Polycrystalline Diamond
    'cobalt'           -- Cobalt Steel
);
```

### ToolCoating
Tool coating types.

```sql
CREATE TYPE tool_coating AS ENUM (
    'uncoated',        -- No coating
    'tin',             -- Titanium Nitride
    'ticn',            -- Titanium Carbonitride
    'tialn',           -- Titanium Aluminum Nitride
    'altin',           -- Aluminum Titanium Nitride
    'dlc',             -- Diamond-Like Carbon
    'diamond',         -- CVD Diamond
    'alcrn',           -- Aluminum Chromium Nitride
    'zrn'              -- Zirconium Nitride
);
```

## Machine & Equipment Enums

### MachineType
CNC machine categories.

```sql
CREATE TYPE machine_type AS ENUM (
    'mill_3axis',      -- 3-axis milling machine
    'mill_4axis',      -- 4-axis milling machine
    'mill_5axis',      -- 5-axis milling machine
    'lathe',           -- CNC lathe
    'turn_mill',       -- Turn-mill center
    'router',          -- CNC router
    'plasma',          -- Plasma cutter
    'laser',           -- Laser cutter
    'waterjet',        -- Waterjet cutter
    'edm_wire',        -- Wire EDM
    'edm_sinker',      -- Sinker EDM
    'grinder',         -- CNC grinder
    'swiss'            -- Swiss-type lathe
);
```

### ControllerType
Machine controller types.

```sql
CREATE TYPE controller_type AS ENUM (
    'fanuc',           -- FANUC
    'siemens',         -- Siemens SINUMERIK
    'heidenhain',      -- Heidenhain TNC
    'haas',            -- Haas
    'mazak',           -- Mazatrol
    'okuma',           -- Okuma OSP
    'mitsubishi',      -- Mitsubishi MELDAS
    'fagor',           -- Fagor
    'num',             -- NUM
    'linuxcnc',        -- LinuxCNC
    'mach3',           -- Mach3/4
    'grbl'             -- GRBL
);
```

## Material Enums

### MaterialCategory
Material classification.

```sql
CREATE TYPE material_category AS ENUM (
    -- Metals
    'steel_carbon',    -- Carbon steels
    'steel_alloy',     -- Alloy steels
    'steel_stainless', -- Stainless steels
    'steel_tool',      -- Tool steels
    'aluminum',        -- Aluminum alloys
    'titanium',        -- Titanium alloys
    'copper',          -- Copper alloys
    'brass',           -- Brass alloys
    'bronze',          -- Bronze alloys
    'cast_iron',       -- Cast irons
    'nickel',          -- Nickel alloys
    'magnesium',       -- Magnesium alloys
    
    -- Non-metals
    'plastic_soft',    -- Soft plastics (PE, PP, etc.)
    'plastic_hard',    -- Hard plastics (PC, POM, etc.)
    'plastic_fiber',   -- Fiber-reinforced plastics
    'composite',       -- Composite materials
    'wood_soft',       -- Softwoods
    'wood_hard',       -- Hardwoods
    'wood_mdf',        -- MDF/Particleboard
    'foam',            -- Foam materials
    'ceramic',         -- Ceramics
    'graphite'         -- Graphite
);
```

## Simulation Enums

### SimulationType
Simulation analysis types.

```sql
CREATE TYPE simulation_type AS ENUM (
    'collision',       -- Collision detection
    'material_removal',-- Material removal simulation
    'cutting_force',   -- Cutting force analysis
    'tool_deflection', -- Tool deflection analysis
    'thermal',         -- Thermal analysis
    'vibration',       -- Vibration/chatter analysis
    'chip_formation',  -- Chip formation simulation
    'surface_finish'   -- Surface finish prediction
);
```

### SimulationStatus
Simulation result status.

```sql
CREATE TYPE simulation_status AS ENUM (
    'passed',          -- No issues detected
    'passed_warnings', -- Passed with warnings
    'failed',          -- Critical issues found
    'error'            -- Simulation error
);
```

### CollisionSeverity
Collision severity levels.

```sql
CREATE TYPE collision_severity AS ENUM (
    'info',            -- Informational
    'warning',         -- Potential issue
    'error',           -- Definite collision
    'critical'         -- Catastrophic collision
);
```

## Notification Enums

### NotificationType
Notification categories.

```sql
CREATE TYPE notification_type AS ENUM (
    -- Job notifications
    'job_completed',   -- Job finished successfully
    'job_failed',      -- Job failed with error
    'job_warning',     -- Job completed with warnings
    
    -- System notifications
    'system_update',   -- System update available
    'system_maintenance', -- Maintenance window
    'system_alert',    -- System alert
    
    -- License notifications
    'license_expiring',-- License expiring soon
    'license_expired', -- License has expired
    'license_renewed', -- License renewed
    
    -- Billing notifications
    'invoice_created', -- New invoice generated
    'payment_due',     -- Payment due reminder
    'payment_received',-- Payment confirmed
    'payment_failed',  -- Payment failed
    
    -- Security notifications
    'security_alert',  -- Security issue detected
    'login_new_device',-- Login from new device
    'password_reset'   -- Password reset requested
);
```

### NotificationSeverity
Notification importance levels.

```sql
CREATE TYPE notification_severity AS ENUM (
    'info',            -- Informational
    'warning',         -- Warning/attention needed
    'error',           -- Error occurred
    'critical'         -- Critical/urgent
);
```

## Billing & Payment Enums

### InvoiceType
Invoice categories.

```sql
CREATE TYPE invoice_type AS ENUM (
    'subscription',    -- Recurring subscription
    'usage',           -- Usage-based billing
    'one_time',        -- One-time charge
    'credit',          -- Credit note
    'adjustment'       -- Adjustment invoice
);
```

### InvoiceStatus
Invoice lifecycle states.

```sql
CREATE TYPE invoice_status AS ENUM (
    'draft',           -- Being prepared
    'sent',            -- Sent to customer
    'viewed',          -- Viewed by customer
    'paid',            -- Payment received
    'partial',         -- Partially paid
    'overdue',         -- Past due date
    'cancelled',       -- Cancelled
    'refunded'         -- Refunded
);
```

### PaymentMethod
Payment method types.

```sql
CREATE TYPE payment_method AS ENUM (
    'credit_card',     -- Credit card
    'debit_card',      -- Debit card
    'bank_transfer',   -- Bank wire transfer
    'ach',             -- ACH transfer
    'paypal',          -- PayPal
    'stripe',          -- Stripe
    'iyzico',          -- Iyzico (Turkish)
    'crypto',          -- Cryptocurrency
    'check',           -- Check
    'cash',            -- Cash
    'invoice'          -- On invoice/account
);
```

### PaymentStatus
Payment transaction states.

```sql
CREATE TYPE payment_status AS ENUM (
    'pending',         -- Awaiting processing
    'processing',      -- Being processed
    'completed',       -- Successfully completed
    'failed',          -- Payment failed
    'cancelled',       -- Cancelled by user
    'refunded',        -- Refunded
    'partial_refund',  -- Partially refunded
    'disputed'         -- Under dispute
);
```

### Currency
Supported currencies.

```sql
CREATE TYPE currency AS ENUM (
    'TRY',             -- Turkish Lira (default)
    'USD',             -- US Dollar
    'EUR'              -- Euro
);
```

## Audit & Security Enums

### AuditAction
Auditable actions.

```sql
CREATE TYPE audit_action AS ENUM (
    -- Authentication
    'auth_login',      -- User login
    'auth_logout',     -- User logout
    'auth_failed',     -- Failed login attempt
    'auth_token_refresh', -- Token refresh
    
    -- User management
    'user_create',     -- User account created
    'user_update',     -- User account updated
    'user_delete',     -- User account deleted
    'user_password_change', -- Password changed
    
    -- Data operations
    'create',          -- Entity created
    'read',            -- Entity accessed
    'update',          -- Entity updated
    'delete',          -- Entity deleted
    'export',          -- Data exported
    'import',          -- Data imported
    
    -- Job operations
    'job_start',       -- Job started
    'job_cancel',      -- Job cancelled
    'job_retry',       -- Job retried
    
    -- System operations
    'config_change',   -- Configuration changed
    'backup_create',   -- Backup created
    'backup_restore'   -- Backup restored
);
```

### SecurityEventType
Security event categories.

```sql
CREATE TYPE security_event_type AS ENUM (
    -- Authentication events
    'login_failed',        -- Failed login attempt
    'login_suspicious',    -- Suspicious login
    'brute_force',         -- Brute force detected
    'account_locked',      -- Account locked
    
    -- Authorization events
    'access_denied',       -- Access denied
    'privilege_escalation',-- Privilege escalation attempt
    
    -- Data security events
    'data_breach',         -- Potential data breach
    'sql_injection',       -- SQL injection attempt
    'xss_attempt',         -- XSS attempt
    'file_upload_blocked', -- Malicious file blocked
    
    -- System security events
    'rate_limit_exceeded', -- Rate limit exceeded
    'ddos_detected',       -- DDoS attack detected
    'vulnerability_scan'   -- Vulnerability scan detected
);
```

### SecuritySeverity
Security event severity levels.

```sql
CREATE TYPE security_severity AS ENUM (
    'low',             -- Low severity
    'medium',          -- Medium severity
    'high',            -- High severity
    'critical'         -- Critical severity
);
```

## ERP/MES Integration Enums

### ErpSystem
Supported ERP/MES systems.

```sql
CREATE TYPE erp_system AS ENUM (
    'sap',             -- SAP ERP
    'oracle',          -- Oracle ERP
    'microsoft_d365',  -- Microsoft Dynamics 365
    'netsuite',        -- NetSuite
    'odoo',            -- Odoo
    'logo',            -- Logo (Turkish)
    'netsis',          -- Netsis (Turkish)
    'mikro',           -- Mikro (Turkish)
    'custom'           -- Custom integration
);
```

### SyncDirection
Data synchronization direction.

```sql
CREATE TYPE sync_direction AS ENUM (
    'inbound',         -- From ERP to system
    'outbound',        -- From system to ERP
    'bidirectional'    -- Two-way sync
);
```

### SyncStatus
Synchronization status.

```sql
CREATE TYPE sync_status AS ENUM (
    'pending',         -- Awaiting sync
    'in_progress',     -- Currently syncing
    'synced',          -- Successfully synced
    'failed',          -- Sync failed
    'conflict',        -- Data conflict
    'skipped'          -- Skipped (not needed)
);
```

## Project Status Enums

### ProjectStatus
Project lifecycle states.

```sql
CREATE TYPE project_status AS ENUM (
    'draft',           -- Initial creation
    'planning',        -- Planning phase
    'design',          -- Design in progress
    'cad_ready',       -- CAD model ready
    'cam_ready',       -- CAM programming done
    'sim_verified',    -- Simulation verified
    'post_ready',      -- G-code generated
    'queued',          -- Queued for production
    'in_production',   -- Currently in production
    'completed',       -- Production completed
    'delivered',       -- Delivered to customer
    'archived',        -- Archived
    'cancelled',       -- Cancelled
    'on_hold'          -- On hold
);
```

## Implementation Notes

### PostgreSQL Enum Creation
```sql
-- Example: Creating user_role enum
CREATE TYPE user_role AS ENUM ('admin', 'engineer', 'operator', 'viewer');

-- Using in table definition
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    role user_role NOT NULL DEFAULT 'engineer'
);
```

### SQLAlchemy Enum Usage
```python
from sqlalchemy import Enum
import enum

class UserRole(str, enum.Enum):
    admin = "admin"
    engineer = "engineer"
    operator = "operator"
    viewer = "viewer"

# In model definition
class User(Base):
    __tablename__ = "users"
    
    role = Column(Enum(UserRole), nullable=False, default=UserRole.engineer)
```

### Migration Considerations
1. Adding new enum values requires ALTER TYPE in PostgreSQL
2. Removing enum values requires careful data migration
3. Renaming enum values requires UPDATE statements
4. Consider using VARCHAR with CHECK constraints for frequently changing values

### Best Practices
1. Use enums for stable, finite sets of values
2. Document each enum value clearly
3. Consider internationalization for display values
4. Map enum values to display strings in application layer
5. Version enum changes in migrations