"""
Add 3d_printer to machine_type enum - Gemini Code Assist Fix

Adds '3d_printer' value to the machine_type enum to properly categorize
3D printing machines instead of incorrectly using 'mill_3axis'.

Revision ID: 20250817_2000_add_3d_printer
Revises: 20250817_1900-task_28_seed_data_migration
Create Date: 2025-08-17 20:00:00.000000

GEMINI CODE ASSIST FIX:
- FIXED: 3D Printer Machine Type Semantic Error
- Added proper '3d_printer' enum value for semantic correctness
- Updated seed data to use correct machine type for Prusa i3 MK3S+
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250817_2000_3d_printer'
down_revision = '20250817_1900_task_28'
branch_labels = None
depends_on = None


def upgrade():
    """Add 3d_printer to machine_type enum."""
    
    print("🔧 Adding 3d_printer to machine_type enum (Gemini Fix)")
    
    # Add new enum value to machine_type
    op.execute(sa.text("ALTER TYPE machine_type ADD VALUE '3d_printer'"))
    
    print("   ✅ Added '3d_printer' to machine_type enum")
    print("   🔧 Gemini Code Assist fix applied: Proper 3D printer machine type")


def downgrade():
    """Remove 3d_printer from machine_type enum."""
    
    print("⚠️ Removing 3d_printer from machine_type enum")
    
    # Note: PostgreSQL doesn't support removing enum values directly
    # This would require recreating the enum and all dependent objects
    print("   ⚠️ Cannot remove enum values in PostgreSQL without recreating enum")
    print("   ⚠️ Manual intervention required if downgrade is necessary")