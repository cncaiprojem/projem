from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_m18_multi_setup"
down_revision = "0009_tooling_and_reports"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fixtures",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("model_path", sa.Text, nullable=True),
        sa.Column("jaw_open_mm", sa.Float, nullable=True),
        sa.Column("clamp_height_mm", sa.Float, nullable=True),
        sa.Column("safety_clear_mm", sa.Float, nullable=False, server_default="10"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "setups",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("orientation_rx_deg", sa.Float, nullable=False, server_default="0"),
        sa.Column("orientation_ry_deg", sa.Float, nullable=False, server_default="0"),
        sa.Column("orientation_rz_deg", sa.Float, nullable=False, server_default="0"),
        sa.Column("wcs", sa.Text, nullable=False, server_default="G54"),
        sa.Column(
            "fixture_id",
            sa.Integer,
            sa.ForeignKey("fixtures.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stock_override_json", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "ops_3d",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "setup_id", sa.Integer, sa.ForeignKey("setups.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("op_type", sa.Text, nullable=False),
        sa.Column("target_faces_json", postgresql.JSONB, nullable=True),
        sa.Column("tool_id", sa.Integer, nullable=True),
        sa.Column("params_json", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "collisions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "setup_id", sa.Integer, sa.ForeignKey("setups.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("phase", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False, server_default="warn"),
        sa.Column("details_json", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "posts_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "setup_id", sa.Integer, sa.ForeignKey("setups.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("processor", sa.Text, nullable=False),
        sa.Column("nc_path", sa.Text, nullable=False),
        sa.Column("line_count", sa.Integer, nullable=False),
        sa.Column("lint_json", postgresql.JSONB, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ok", sa.Boolean, nullable=False, server_default=sa.sql.expression.false()),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    # shop_packages setups_json ekle (varsa)
    try:
        op.add_column("shop_packages", sa.Column("setups_json", postgresql.JSONB, nullable=True))
    except Exception:
        pass


def downgrade():
    try:
        op.drop_column("shop_packages", "setups_json")
    except Exception:
        pass
    op.drop_table("posts_runs")
    op.drop_table("collisions")
    op.drop_table("ops_3d")
    op.drop_table("setups")
    op.drop_table("fixtures")
