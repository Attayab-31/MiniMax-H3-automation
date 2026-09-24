"""Add durable video object references to generation jobs.

Revision ID: a847e0cd812f
Revises: 611f37e3e0e7
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa


revision = "a847e0cd812f"
down_revision = "611f37e3e0e7"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("generation_jobs")}
    indexes = {index["name"] for index in inspector.get_indexes("generation_jobs")}

    # The initial revision may already include this field on a fresh deployment.
    if "video_storage_path" not in columns:
        op.add_column(
            "generation_jobs",
            sa.Column("video_storage_path", sa.String(length=512), nullable=True),
        )
    if "ix_generation_jobs_video_storage_path" not in indexes:
        op.create_index(
            "ix_generation_jobs_video_storage_path",
            "generation_jobs",
            ["video_storage_path"],
            unique=False,
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("generation_jobs")}
    indexes = {index["name"] for index in inspector.get_indexes("generation_jobs")}
    if "ix_generation_jobs_video_storage_path" in indexes:
        op.drop_index("ix_generation_jobs_video_storage_path", table_name="generation_jobs")
    if "video_storage_path" in columns:
        op.drop_column("generation_jobs", "video_storage_path")
