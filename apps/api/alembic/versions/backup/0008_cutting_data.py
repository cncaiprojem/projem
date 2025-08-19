from alembic import op
import sqlalchemy as sa


revision = "0008_cutting_data"
down_revision = "0007_projects_qna"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cutting_data",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("material", sa.String(), nullable=False),
        sa.Column("tool_type", sa.String(), nullable=False),
        sa.Column("tool_dia_min_mm", sa.Float(), nullable=False),
        sa.Column("tool_dia_max_mm", sa.Float(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("rpm", sa.Integer(), nullable=False),
        sa.Column("feed_mm_min", sa.Float(), nullable=False),
        sa.Column("plunge_mm_min", sa.Float(), nullable=False),
        sa.Column("stepdown_mm", sa.Float(), nullable=False),
        sa.Column("stepover_pct", sa.Float(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
    )
    op.create_unique_constraint(
        "uix_cutting",
        "cutting_data",
        [
            "material",
            "tool_type",
            "operation",
            "tool_dia_min_mm",
            "tool_dia_max_mm",
        ],
    )


def downgrade():
    op.drop_constraint("uix_cutting", "cutting_data", type_="unique")
    op.drop_table("cutting_data")
