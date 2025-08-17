from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_projects_qna"
down_revision = "0006_design_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.Enum("part", "assembly", name="projecttype"), nullable=False, server_default="part"),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "planning",
                "cad_ready",
                "cam_ready",
                "sim_ok",
                "post_ok",
                "queued",
                "running",
                "done",
                "error",
                name="projectstatus",
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("owner_id", sa.Integer, nullable=True),
        sa.Column("summary_json", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_projects_idempotency_key", "projects", ["idempotency_key"], unique=False)

    op.create_table(
        "project_files",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Enum("cad", "cam", "sim", "gcode", "package", "doc", name="filekind"), nullable=False),
        sa.Column("s3_key", sa.String(512), nullable=False),
        sa.Column("size", sa.Integer, nullable=True),
        sa.Column("sha256", sa.String(128), nullable=True),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "ai_qna",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=True),
        sa.Column("missing_fields", postgresql.JSONB, nullable=True),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
    )


def downgrade():
    op.drop_table("ai_qna")
    op.drop_table("project_files")
    op.drop_index("ix_projects_idempotency_key", table_name="projects")
    op.drop_table("projects")
    op.execute("DROP TYPE IF EXISTS projecttype")
    op.execute("DROP TYPE IF EXISTS projectstatus")
    op.execute("DROP TYPE IF EXISTS filekind")


