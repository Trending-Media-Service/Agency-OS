"""connections_lifecycle

Revision ID: a6d046e08cb8
Revises: 5cb046e08cb8
Create Date: 2026-06-19 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a6d046e08cb8'
down_revision: Union[str, Sequence[str], None] = '5cb046e08cb8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    with op.batch_alter_table('connections') as batch_op:
        # Make secret_ref nullable to support revocation (no rename!)
        batch_op.alter_column('secret_ref', nullable=True, existing_type=sa.String(255))
        # Add new columns
        batch_op.add_column(sa.Column('status', sa.String(16), nullable=False, server_default='unverified'))
        batch_op.add_column(sa.Column('last_verified_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('last_error', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('revoked_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('expires_at', sa.DateTime(), nullable=True))

def downgrade() -> None:
    with op.batch_alter_table('connections') as batch_op:
        batch_op.alter_column('secret_ref', nullable=False, existing_type=sa.String(255))
        batch_op.drop_column('status')
        batch_op.drop_column('last_verified_at')
        batch_op.drop_column('last_error')
        batch_op.drop_column('revoked_at')
        batch_op.drop_column('expires_at')
