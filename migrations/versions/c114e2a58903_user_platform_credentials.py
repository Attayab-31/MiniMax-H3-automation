"""Scope provider credentials to each workspace."""
import os
from alembic import op
import sqlalchemy as sa

revision = "c114e2a58903"
down_revision = "b93e7f4a2c11"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("platform_credentials")}
    if "user_id" not in columns:
        username = (os.getenv("ADMIN_USERNAME") or "admin").strip() or "admin"
        admin_id = bind.execute(
            sa.text("SELECT id FROM users WHERE username=:username"), {"username": username}
        ).scalar_one()
        op.add_column("platform_credentials", sa.Column("user_id", sa.Integer(), nullable=True))
        bind.execute(sa.text("UPDATE platform_credentials SET user_id=:uid"), {"uid": admin_id})
        with op.batch_alter_table("platform_credentials") as batch:
            batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
            batch.create_foreign_key(
                "fk_platform_credentials_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_index("ix_platform_credentials_user_id", ["user_id"])

    uniques = sa.inspect(bind).get_unique_constraints("platform_credentials")
    desired = {"user_id", "platform", "account_label"}
    if not any(set(constraint.get("column_names") or []) == desired for constraint in uniques):
        convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table("platform_credentials", naming_convention=convention) as batch:
            old = next((c for c in uniques if set(c.get("column_names") or []) == {"platform", "account_label"}), None)
            if old is not None:
                old_name = old.get("name") or "uq_platform_credentials_platform"
                batch.drop_constraint(old_name, type_="unique")
            batch.create_unique_constraint(
                "uq_platform_user_account", ["user_id", "platform", "account_label"]
            )


def downgrade():
    with op.batch_alter_table("platform_credentials") as batch:
        batch.drop_constraint("uq_platform_user_account", type_="unique")
        batch.create_unique_constraint(
            "platform_credentials_platform_account_label_key", ["platform", "account_label"]
        )
        batch.drop_index("ix_platform_credentials_user_id")
        batch.drop_constraint("fk_platform_credentials_user_id_users", type_="foreignkey")
        batch.drop_column("user_id")
