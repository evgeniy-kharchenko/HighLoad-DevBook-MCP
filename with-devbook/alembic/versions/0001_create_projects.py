"""Create the projects table."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gitlab_project_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("path_with_namespace", sa.String(), nullable=False),
        sa.Column("web_url", sa.String(), nullable=False),
        sa.Column("default_branch", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "gitlab_project_id > 0", name="ck_projects_gitlab_id_positive"
        ),
        sqlite_autoincrement=True,
    )


def downgrade() -> None:
    op.drop_table("projects")
