"""Add shadow_decisions table

Revision ID: 89123f070704
Revises: e7cb80ecf5ac
Create Date: 2026-06-15 17:35:32.365409

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '89123f070704'
down_revision: Union[str, Sequence[str], None] = 'e7cb80ecf5ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('shadow_decisions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=32), nullable=False),
    sa.Column('op_id', sa.String(length=32), nullable=False),
    sa.Column('human_decision', sa.String(length=16), nullable=False),
    sa.Column('shadow_tier', sa.Integer(), nullable=False),
    sa.Column('shadow_requirement', sa.String(length=60), nullable=True),
    sa.Column('agreed', sa.Boolean(), nullable=False),
    sa.Column('violations', sa.JSON(), nullable=False),
    sa.Column('ts', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_shadow_decisions_tenant_id'), 'shadow_decisions', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_shadow_decisions_op_id'), 'shadow_decisions', ['op_id'], unique=False)

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE shadow_decisions ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE shadow_decisions FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON shadow_decisions;")
        op.execute("""
            CREATE POLICY tenant_isolation ON shadow_decisions
              USING (tenant_id = current_setting('app.current_tenant_id', true));
        """)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON shadow_decisions;")
        op.execute("ALTER TABLE shadow_decisions DISABLE ROW LEVEL SECURITY;")

    op.drop_index(op.f('ix_shadow_decisions_op_id'), table_name='shadow_decisions')
    op.drop_index(op.f('ix_shadow_decisions_tenant_id'), table_name='shadow_decisions')
    op.drop_table('shadow_decisions')
