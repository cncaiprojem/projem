from alembic import op
import sqlalchemy as sa


revision = "0009_tooling_and_reports"
down_revision = "0008_cutting_data"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tools",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("diameter_mm", sa.Float, nullable=True),
        sa.Column("flute_count", sa.Integer, nullable=True),
        sa.Column("flute_len_mm", sa.Float, nullable=True),
        sa.Column("overall_len_mm", sa.Float, nullable=True),
        sa.Column("shank_dia_mm", sa.Float, nullable=True),
        sa.Column("stickout_mm", sa.Float, nullable=True),
        sa.Column("material", sa.String(20), nullable=True),
        sa.Column("coating", sa.String(100), nullable=True),
        sa.Column("toolbit_json_path", sa.String(1024), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tools_type_dia", "tools", ["type", "diameter_mm"])

    op.create_table(
        "holders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.String(100), nullable=True),
        sa.Column("gauge_len_mm", sa.Float, nullable=True),
        sa.Column("collision_model_path", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "tool_presets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("machine_id", sa.Integer, nullable=False),
        sa.Column(
            "tool_id", sa.Integer, sa.ForeignKey("tools.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "holder_id", sa.Integer, sa.ForeignKey("holders.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("pocket_no", sa.Integer, nullable=False),
        sa.Column("length_offset", sa.Float, nullable=True),
        sa.Column("diameter_offset", sa.Float, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_unique_constraint(
        "uix_tool_presets_machine_pocket", "tool_presets", ["machine_id", "pocket_no"]
    )

    op.create_table(
        "shop_packages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pdf_path", sa.String(1024), nullable=False),
        sa.Column("pdf_sha256", sa.String(64), nullable=False),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=True),
    )


def downgrade():
    op.drop_table("shop_packages")
    op.drop_constraint("uix_tool_presets_machine_pocket", "tool_presets", type_="unique")
    op.drop_table("tool_presets")
    op.drop_table("holders")
    op.drop_index("ix_tools_type_dia", table_name="tools")
    op.drop_table("tools")
