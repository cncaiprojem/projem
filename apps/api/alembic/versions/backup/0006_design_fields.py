from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0006_design_fields'
down_revision = '0005_jobs_idempotency_unique'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('jobs') as batch:
        batch.add_column(sa.Column('parent_job_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('model_name', sa.String(length=100), nullable=True))
        batch.add_column(sa.Column('token_input', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('token_output', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('escalated', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade():
    with op.batch_alter_table('jobs') as batch:
        batch.drop_column('escalated')
        batch.drop_column('token_output')
        batch.drop_column('token_input')
        batch.drop_column('model_name')
        batch.drop_column('parent_job_id')


