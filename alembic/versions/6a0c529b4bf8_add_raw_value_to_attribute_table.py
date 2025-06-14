"""add raw_value to attribute table

Revision ID: 6a0c529b4bf8
Revises: f35826018ede
Create Date: 2025-06-10 16:04:45.444527

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a0c529b4bf8'
down_revision: Union[str, None] = 'f35826018ede'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('city_attributes', sa.Column('raw_value', sa.Float(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('city_attributes', 'raw_value')
    # ### end Alembic commands ###
