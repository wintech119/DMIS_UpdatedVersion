"""init db

Revision ID: bcca0c27d71b
Revises: 
Create Date: 2025-12-09 10:37:00.439111

"""
from alembic import op
import sqlalchemy as sa
import app.migrations.runner as runner


# revision identifiers, used by Alembic.
revision = 'bcca0c27d71b'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    runner.trigger("001_init_db.sql")
    runner.trigger("002_add_user_uuid.sql")
    runner.trigger("003_admin_seed.sql")


def downgrade():
    pass
