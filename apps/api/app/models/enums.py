"""
Database enumerations for type safety and constraints.
"""

import enum


class UserRole(str, enum.Enum):
    """User permission levels."""
    ADMIN = "admin"
    ENGINEER = "engineer"
    OPERATOR = "operator"
    VIEWER = "viewer"


class Locale(str, enum.Enum):
    """Supported UI languages."""
    TR = "tr"  # Turkish (default)
    EN = "en"  # English
    DE = "de"  # German


class LicenseType(str, enum.Enum):
    """Software license tiers."""
    TRIAL = "trial"
    BASIC = "basic"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class LicenseStatus(str, enum.Enum):
    """License lifecycle states."""
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class JobType(str, enum.Enum):
    """Types of processing jobs."""
    CAD_GENERATE = "cad_generate"
    CAD_IMPORT = "cad_import"
    CAD_EXPORT = "cad_export"
    CAM_PROCESS = "cam_process"
    CAM_OPTIMIZE = "cam_optimize"
    SIM_RUN = "sim_run"
    SIM_COLLISION = "sim_collision"
    GCODE_POST = "gcode_post"
    GCODE_VERIFY = "gcode_verify"
    REPORT_GENERATE = "report_generate"
    MODEL_REPAIR = "model_repair"


class JobStatus(str, enum.Enum):
    """Job execution states."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class ModelType(str, enum.Enum):
    """3D model categories."""
    PART = "part"
    ASSEMBLY = "assembly"
    DRAWING = "drawing"
    SKETCH = "sketch"
    MESH = "mesh"


class FileFormat(str, enum.Enum):
    """Supported file formats."""
    # Native
    FCSTD = "FCStd"
    # CAD Exchange
    STEP = "STEP"
    IGES = "IGES"
    BREP = "BREP"
    # Mesh
    STL = "STL"
    OBJ = "OBJ"
    PLY = "PLY"
    # Drawing
    DXF = "DXF"
    SVG = "SVG"
    PDF = "PDF"
    # Other
    GCODE = "GCODE"
    JSON = "JSON"


class CamStrategy(str, enum.Enum):
    """CAM processing strategies."""
    # 2.5D
    FACE_MILL = "face_mill"
    POCKET_2D = "pocket_2d"
    CONTOUR_2D = "contour_2d"
    DRILL = "drill"
    THREAD_MILL = "thread_mill"
    ENGRAVE = "engrave"
    # 3D
    ADAPTIVE_CLEAR = "adaptive_clear"
    POCKET_3D = "pocket_3d"
    CONTOUR_3D = "contour_3d"
    PARALLEL = "parallel"
    RADIAL = "radial"
    SPIRAL = "spiral"
    MORPHED_SPIRAL = "morphed_spiral"
    PROJECT = "project"
    SWARF = "swarf"
    FLOW = "flow"
    # Specialized
    REST_MACHINING = "rest_machining"
    PENCIL = "pencil"
    SCALLOP = "scallop"
    STEEP_SHALLOW = "steep_shallow"


class ToolType(str, enum.Enum):
    """Cutting tool types."""
    # Milling
    ENDMILL_FLAT = "endmill_flat"
    ENDMILL_BALL = "endmill_ball"
    ENDMILL_BULL = "endmill_bull"
    ENDMILL_CHAMFER = "endmill_chamfer"
    ENDMILL_TAPER = "endmill_taper"
    FACE_MILL = "face_mill"
    SLOT_MILL = "slot_mill"
    # Drilling
    DRILL_TWIST = "drill_twist"
    DRILL_CENTER = "drill_center"
    DRILL_SPOT = "drill_spot"
    DRILL_PECK = "drill_peck"
    DRILL_GUN = "drill_gun"
    # Specialized
    REAMER = "reamer"
    TAP = "tap"
    THREAD_MILL = "thread_mill"
    BORING_BAR = "boring_bar"
    COUNTERSINK = "countersink"
    COUNTERBORE = "counterbore"
    ENGRAVER = "engraver"
    PROBE = "probe"


class ToolMaterial(str, enum.Enum):
    """Tool material composition."""
    HSS = "hss"
    CARBIDE = "carbide"
    CARBIDE_COATED = "carbide_coated"
    CERAMIC = "ceramic"
    CBN = "cbn"
    PCD = "pcd"
    COBALT = "cobalt"


class MachineType(str, enum.Enum):
    """CNC machine categories."""
    MILL_3AXIS = "mill_3axis"
    MILL_4AXIS = "mill_4axis"
    MILL_5AXIS = "mill_5axis"
    LATHE = "lathe"
    TURN_MILL = "turn_mill"
    ROUTER = "router"
    PLASMA = "plasma"
    LASER = "laser"
    WATERJET = "waterjet"
    EDM_WIRE = "edm_wire"
    EDM_SINKER = "edm_sinker"
    GRINDER = "grinder"
    SWISS = "swiss"
    PRINTER_3D = "3d_printer"


class MaterialCategory(str, enum.Enum):
    """Material classification."""
    # Metals
    STEEL_CARBON = "steel_carbon"
    STEEL_ALLOY = "steel_alloy"
    STEEL_STAINLESS = "steel_stainless"
    STEEL_TOOL = "steel_tool"
    ALUMINUM = "aluminum"
    TITANIUM = "titanium"
    COPPER = "copper"
    BRASS = "brass"
    BRONZE = "bronze"
    CAST_IRON = "cast_iron"
    NICKEL = "nickel"
    MAGNESIUM = "magnesium"
    # Non-metals
    PLASTIC_SOFT = "plastic_soft"
    PLASTIC_HARD = "plastic_hard"
    PLASTIC_FIBER = "plastic_fiber"
    COMPOSITE = "composite"
    WOOD_SOFT = "wood_soft"
    WOOD_HARD = "wood_hard"
    WOOD_MDF = "wood_mdf"
    FOAM = "foam"
    CERAMIC = "ceramic"
    GRAPHITE = "graphite"


class SimulationType(str, enum.Enum):
    """Simulation analysis types."""
    COLLISION = "collision"
    MATERIAL_REMOVAL = "material_removal"
    CUTTING_FORCE = "cutting_force"
    TOOL_DEFLECTION = "tool_deflection"
    THERMAL = "thermal"
    VIBRATION = "vibration"
    CHIP_FORMATION = "chip_formation"
    SURFACE_FINISH = "surface_finish"


class SimulationStatus(str, enum.Enum):
    """Simulation result status."""
    PASSED = "passed"
    PASSED_WARNINGS = "passed_warnings"
    FAILED = "failed"
    ERROR = "error"


class NotificationType(str, enum.Enum):
    """Notification categories."""
    # Job
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    JOB_WARNING = "job_warning"
    # System
    SYSTEM_UPDATE = "system_update"
    SYSTEM_MAINTENANCE = "system_maintenance"
    SYSTEM_ALERT = "system_alert"
    # License
    LICENSE_EXPIRING = "license_expiring"
    LICENSE_EXPIRED = "license_expired"
    LICENSE_RENEWED = "license_renewed"
    # Billing
    INVOICE_CREATED = "invoice_created"
    PAYMENT_DUE = "payment_due"
    PAYMENT_RECEIVED = "payment_received"
    PAYMENT_FAILED = "payment_failed"
    # Security
    SECURITY_ALERT = "security_alert"
    LOGIN_NEW_DEVICE = "login_new_device"
    PASSWORD_RESET = "password_reset"


class NotificationSeverity(str, enum.Enum):
    """Notification importance levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class InvoiceType(str, enum.Enum):
    """Invoice categories."""
    SUBSCRIPTION = "subscription"
    USAGE = "usage"
    ONE_TIME = "one_time"
    CREDIT = "credit"
    ADJUSTMENT = "adjustment"


class InvoiceStatus(str, enum.Enum):
    """Invoice lifecycle states."""
    DRAFT = "draft"
    SENT = "sent"
    VIEWED = "viewed"
    PAID = "paid"
    PARTIAL = "partial"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentMethod(str, enum.Enum):
    """Payment method types."""
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    BANK_TRANSFER = "bank_transfer"
    ACH = "ach"
    PAYPAL = "paypal"
    STRIPE = "stripe"
    IYZICO = "iyzico"
    CRYPTO = "crypto"
    CHECK = "check"
    CASH = "cash"
    INVOICE = "invoice"


class PaymentStatus(str, enum.Enum):
    """Payment transaction states - Task 4.6 specification."""
    REQUIRES_ACTION = "requires_action"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


class PaidStatus(str, enum.Enum):
    """Invoice payment status - Task 4.4 specification."""
    UNPAID = "unpaid"
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class Currency(str, enum.Enum):
    """Supported currencies."""
    TRY = "TRY"
    USD = "USD"
    EUR = "EUR"


class AuditAction(str, enum.Enum):
    """Auditable actions."""
    # Authentication
    AUTH_LOGIN = "auth_login"
    AUTH_LOGOUT = "auth_logout"
    AUTH_FAILED = "auth_failed"
    AUTH_TOKEN_REFRESH = "auth_token_refresh"
    # User management
    USER_CREATE = "user_create"
    USER_UPDATE = "user_update"
    USER_DELETE = "user_delete"
    USER_PASSWORD_CHANGE = "user_password_change"
    # Data operations
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    EXPORT = "export"
    IMPORT = "import"
    # Job operations
    JOB_START = "job_start"
    JOB_CANCEL = "job_cancel"
    JOB_RETRY = "job_retry"
    # System operations
    CONFIG_CHANGE = "config_change"
    BACKUP_CREATE = "backup_create"
    BACKUP_RESTORE = "backup_restore"


class SecurityEventType(str, enum.Enum):
    """Security event categories."""
    # Authentication
    LOGIN_FAILED = "login_failed"
    LOGIN_SUSPICIOUS = "login_suspicious"
    BRUTE_FORCE = "brute_force"
    ACCOUNT_LOCKED = "account_locked"
    # Authorization
    ACCESS_DENIED = "access_denied"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    # Data security
    DATA_BREACH = "data_breach"
    SQL_INJECTION = "sql_injection"
    XSS_ATTEMPT = "xss_attempt"
    FILE_UPLOAD_BLOCKED = "file_upload_blocked"
    # System security
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    DDOS_DETECTED = "ddos_detected"
    VULNERABILITY_SCAN = "vulnerability_scan"


class SecuritySeverity(str, enum.Enum):
    """Security event severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErpSystem(str, enum.Enum):
    """Supported ERP/MES systems."""
    SAP = "sap"
    ORACLE = "oracle"
    MICROSOFT_D365 = "microsoft_d365"
    NETSUITE = "netsuite"
    ODOO = "odoo"
    LOGO = "logo"
    NETSIS = "netsis"
    MIKRO = "mikro"
    CUSTOM = "custom"


class SyncDirection(str, enum.Enum):
    """Data synchronization direction."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    BIDIRECTIONAL = "bidirectional"


class SyncStatus(str, enum.Enum):
    """Synchronization status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SYNCED = "synced"
    FAILED = "failed"
    CONFLICT = "conflict"
    SKIPPED = "skipped"