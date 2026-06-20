"""add_leads_table

Revision ID: 99fb80ecf5ad
Revises: 09694bdcb7b8
Create Date: 2026-06-20 23:17:15.123456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '99fb80ecf5ad'
down_revision: Union[str, Sequence[str], None] = '09694bdcb7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('leads',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('tenant_id', sa.String(length=32), nullable=False),
    sa.Column('brand_id', sa.String(length=32), nullable=False),
    sa.Column('lead_id', sa.String(length=64), nullable=False),
    sa.Column('email_hashed', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('deal_value_minor', sa.Integer(), nullable=True),
    sa.Column('gclid', sa.String(length=120), nullable=True),
    sa.Column('placed_at', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lead_id')
    )
    op.create_index(op.f('ix_leads_tenant_id'), 'leads', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_leads_brand_id'), 'leads', ['brand_id'], unique=False)
    op.create_index(op.f('ix_leads_email_hashed'), 'leads', ['email_hashed'], unique=False)

    # Enable PostgreSQL Row-Level Security (RLS) for tenant isolation
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE leads ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE leads FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON leads;")
        op.execute("""
            CREATE POLICY tenant_isolation ON leads
              USING (tenant_id = current_setting('app.current_tenant_id', true));
        """)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON leads;")
        op.execute("ALTER TABLE leads DISABLE ROW LEVEL SECURITY;")

    op.drop_index(op.f('ix_leads_email_hashed'), table_name='leads')
    op.drop_index(op.f('ix_leads_brand_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_tenant_id'), table_name='leads')
    op.drop_table('leads')
