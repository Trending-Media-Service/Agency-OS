"""add_consent_gate

Revision ID: e7cb80ecf5ac
Revises: 88fb80ecf5ab
Create Date: 2026-06-15 10:31:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7cb80ecf5ac'
down_revision: Union[str, Sequence[str], None] = '88fb80ecf5ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('consent_bases',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('tenant_id', sa.String(length=32), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('action_or_vendor', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('granted_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('granted_by', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_consent_bases_action_or_vendor'), 'consent_bases', ['action_or_vendor'], unique=False)
    op.create_index(op.f('ix_consent_bases_tenant_id'), 'consent_bases', ['tenant_id'], unique=False)

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE consent_bases ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE consent_bases FORCE ROW LEVEL SECURITY;")
        op.execute("""
            DROP POLICY IF EXISTS tenant_isolation ON consent_bases;
            CREATE POLICY tenant_isolation ON consent_bases
              USING (tenant_id = current_setting('app.current_tenant_id', true));
        """)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON consent_bases;")
        op.execute("ALTER TABLE consent_bases DISABLE ROW LEVEL SECURITY;")
        
    op.drop_index(op.f('ix_consent_bases_tenant_id'), table_name='consent_bases')
    op.drop_index(op.f('ix_consent_bases_action_or_vendor'), table_name='consent_bases')
    op.drop_table('consent_bases')
