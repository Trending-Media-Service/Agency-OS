"""add_rls_to_outbox

Revision ID: 3f3d806d45c4
Revises: 0c06f3a7b210
Create Date: 2026-06-18 14:09:27.778692

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f3d806d45c4'
down_revision: Union[str, Sequence[str], None] = '0c06f3a7b210'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE outbox ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE outbox FORCE ROW LEVEL SECURITY;")
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON outbox;")
        op.execute("""
            CREATE POLICY tenant_isolation ON outbox
              USING (tenant_id = current_setting('app.current_tenant_id', true));
        """)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON outbox;")
        op.execute("ALTER TABLE outbox DISABLE ROW LEVEL SECURITY;")
