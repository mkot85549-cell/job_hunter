"""initial baseline: processed_items table

Revision ID: 001
Revises: None
Create Date: 2026-10-19 16:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Идемпотентность: проверяем, существует ли таблица в живой БД
    if not context.is_offline_mode():
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        if "processed_items" in inspector.get_table_names():
            # Таблица уже создана (например, через create_all в старой версии)
            return

    op.create_table(
        "processed_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform",
            "item_type",
            "external_id",
            name="uq_platform_item",
        ),
    )
    op.create_index(
        op.f("ix_processed_items_platform"),
        "processed_items",
        ["platform"],
        unique=False,
    )


def downgrade() -> None:
    # Таблица processed_items намеренно не удаляется при откате baseline-миграции,
    # чтобы сохранить историю дедупликации и предотвратить повторные отклики.
    pass
