"""Add user accounts and tenant ownership."""
import os
from alembic import op
import sqlalchemy as sa
from werkzeug.security import generate_password_hash

revision = "b93e7f4a2c11"
down_revision = "a847e0cd812f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    bind = op.get_bind()
    username = (os.getenv("ADMIN_USERNAME") or "admin").strip() or "admin"
    password = os.getenv("ADMIN_PASSWORD")
    if not password:
        raise RuntimeError("Set ADMIN_PASSWORD before upgrading to user workspaces.")
    result = bind.execute(sa.text(
        "INSERT INTO users (username, password_hash, created_at) VALUES (:u, :p, CURRENT_TIMESTAMP)"
    ), {"u": username, "p": generate_password_hash(password)})
    admin_id = result.lastrowid
    if admin_id is None:
        admin_id = bind.execute(sa.text("SELECT id FROM users WHERE username=:u"), {"u": username}).scalar_one()

    for table in ("kaggle_accounts", "schedules", "generation_jobs"):
        op.add_column(table, sa.Column("user_id", sa.Integer(), nullable=True))
        bind.execute(sa.text(f"UPDATE {table} SET user_id=:uid"), {"uid": admin_id})
        with op.batch_alter_table(table) as batch:
            batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
            batch.create_foreign_key(f"fk_{table}_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE")
            batch.create_index(f"ix_{table}_user_id", ["user_id"])

    # Account names and kernel IDs only need to be unique within a user's workspace.
    convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    with op.batch_alter_table("kaggle_accounts", naming_convention=convention) as batch:
        for name in ("label", "username", "kernel_id"):
            old_name = f"{name}_key" if bind.dialect.name == "postgresql" else f"uq_kaggle_accounts_{name}"
            batch.drop_constraint(old_name, type_="unique")
        batch.create_unique_constraint("uq_kaggle_user_label", ["user_id", "label"])
        batch.create_unique_constraint("uq_kaggle_user_kernel", ["user_id", "kernel_id"])


def downgrade():
    with op.batch_alter_table("kaggle_accounts") as batch:
        batch.drop_constraint("uq_kaggle_user_label", type_="unique")
        batch.drop_constraint("uq_kaggle_user_kernel", type_="unique")
        batch.create_unique_constraint("kaggle_accounts_label_key", ["label"])
        batch.create_unique_constraint("kaggle_accounts_username_key", ["username"])
        batch.create_unique_constraint("kaggle_accounts_kernel_id_key", ["kernel_id"])
    for table in ("generation_jobs", "schedules", "kaggle_accounts"):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_user_id")
            batch.drop_constraint(f"fk_{table}_user_id_users", type_="foreignkey")
            batch.drop_column("user_id")
    op.drop_table("users")
