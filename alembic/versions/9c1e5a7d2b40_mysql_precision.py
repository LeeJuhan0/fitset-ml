"""mysql precision

Revision ID: 9c1e5a7d2b40
Revises: 43f01e4c225f
Create Date: 2026-09-27 19:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '9c1e5a7d2b40'
down_revision: Union[str, Sequence[str], None] = '43f01e4c225f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STAMPED = {
    "platforms": ["created_at"],
    "devices": ["created_at"],
    "exercises": ["created_at", "updated_at"],
    "dataset_files": ["created_at", "updated_at"],
    "collect_files": ["created_at", "updated_at"],
    "phase_labels": ["created_at", "updated_at"],
    "phase_models": ["created_at", "updated_at"],
    "model_deployments": ["created_at"],
    "training_runs": ["created_at", "updated_at"],
}
NULLABLE_TIMES = [("collect_files", "promoted_at"), ("phase_models", "deployed_at"), ("training_runs", "finished_at")]
REQUIRED_TIMES = [("phase_labels", "labeled_at")]
DOUBLES = [("collect_files", "video_start", "NULL"), ("phase_models", "lr", "NOT NULL"), ("training_runs", "lr", "NOT NULL")]


def upgrade() -> None:
    """MySQL 만 DATETIME(6), DOUBLE 로, FLOAT 정밀도와 마이크로초 손실 방지"""
    if op.get_bind().dialect.name != "mysql":
        return
    for table, columns in STAMPED.items():
        for column in columns:
            op.execute(f"ALTER TABLE {table} MODIFY {column} DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)")
    for table, column in NULLABLE_TIMES:
        op.execute(f"ALTER TABLE {table} MODIFY {column} DATETIME(6) NULL")
    for table, column in REQUIRED_TIMES:
        op.execute(f"ALTER TABLE {table} MODIFY {column} DATETIME(6) NOT NULL")
    for table, column, null in DOUBLES:
        op.execute(f"ALTER TABLE {table} MODIFY {column} DOUBLE {null}")


def downgrade() -> None:
    """되돌리지 않음, 정밀도만 넓힌 변경"""
