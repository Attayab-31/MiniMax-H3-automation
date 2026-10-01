"""Add admin accounts and user account status fields."""
from alembic import op
import sqlalchemy as sa


revision = "e72c9f4ab601"
down_revision = "c114e2a58903"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "admins" not in tables:
        op.create_table(
            "admins",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("username", sa.String(length=80), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("username"),
        )
        op.create_index("ix_admins_username", "admins", ["username"])

    user_columns = {
        column["name"] for column in inspector.get_columns("users")
    }
    if "status" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'active'"),
            ),
        )
    if "suspension_reason" not in user_columns:
        op.add_column(
            "users",
            sa.Column("suspension_reason", sa.String(
                length=255), nullable=True),
        )
    if "suspended_at" not in user_columns:
        op.add_column(
            "users",
            sa.Column("suspended_at", sa.DateTime(), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {
        column["name"] for column in inspector.get_columns("users")
    }
    for column in ("suspended_at", "suspension_reason", "status"):
        if column in user_columns:
            op.drop_column("users", column)
