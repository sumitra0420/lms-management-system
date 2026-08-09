"""add canvas sync columns to upload_jobs

Revision ID: b7090e8ba0eb
Revises: 
Create Date: 2026-08-09 20:09:21.540063

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7090e8ba0eb'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('upload_jobs', sa.Column('canvas_quiz_id', sa.Integer(), nullable=True))
    op.add_column('upload_jobs', sa.Column('canvas_course_id', sa.Integer(), nullable=True))
    op.add_column('upload_jobs', sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True))
    # NOTE: autogenerate also detected a TEXT()->String() type change on
    # error_message here — a false positive (Postgres has no meaningful
    # difference between unbounded VARCHAR and TEXT), not an intended
    # change, so left out of this migration.


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('upload_jobs', 'synced_at')
    op.drop_column('upload_jobs', 'canvas_course_id')
    op.drop_column('upload_jobs', 'canvas_quiz_id')
