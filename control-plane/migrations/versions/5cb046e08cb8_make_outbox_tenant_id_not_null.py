"""make_outbox_tenant_id_not_null

Revision ID: 5cb046e08cb8
Revises: d637e98894e7
Create Date: 2026-06-18 21:27:06.858464

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5cb046e08cb8'
down_revision: Union[str, Sequence[str], None] = 'd637e98894e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Backfill legacy null tenant_ids to 'system'
    op.execute("UPDATE outbox SET tenant_id = 'system' WHERE tenant_id IS NULL")
    
    # 2. Alter column to NOT NULL using batch context
    with op.batch_alter_table('outbox') as batch_op:
        batch_op.alter_column('tenant_id',
                   existing_type=sa.String(length=32),
                   nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('outbox') as batch_op:
        batch_op.alter_column('tenant_id',
                   existing_type=sa.String(length=32),
                   nullable=True)
