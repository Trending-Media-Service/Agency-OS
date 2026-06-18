"""widen_connection_scope

Revision ID: d637e98894e7
Revises: 3f3d806d45c4
Create Date: 2026-06-18 17:17:01.676278

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd637e98894e7'
down_revision: Union[str, Sequence[str], None] = '3f3d806d45c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('connections') as batch_op:
        batch_op.alter_column('scope', type_=sa.String(length=128))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('connections') as batch_op:
        batch_op.alter_column('scope', type_=sa.String(length=16))
