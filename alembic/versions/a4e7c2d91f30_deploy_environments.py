"""deploy environments

Revision ID: a4e7c2d91f30
Revises: 9c1e5a7d2b40
Create Date: 2026-09-29 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'a4e7c2d91f30'
down_revision: Union[str, Sequence[str], None] = '9c1e5a7d2b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = "fk_model_deployments_environment_id_environments"


def upgrade() -> None:
    """환경 테이블 추가, 배포 이력 환경 FK, 기존 이력은 dev"""
    environments = op.create_table('environments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
    sa.Column('created_at', sqlmodel.sql.sqltypes.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('environments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_environments_name'), ['name'], unique=True)
    if op.get_bind().dialect.name == "mysql":
        op.execute("ALTER TABLE environments MODIFY created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)")
    op.bulk_insert(environments, [{"name": "dev"}, {"name": "prod"}])

    with op.batch_alter_table('model_deployments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('environment_id', sa.Integer(), nullable=True))
    op.execute("UPDATE model_deployments SET environment_id = (SELECT id FROM environments WHERE name = 'dev')")
    with op.batch_alter_table('model_deployments', schema=None) as batch_op:
        batch_op.alter_column('environment_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(batch_op.f('ix_model_deployments_environment_id'), ['environment_id'], unique=False)
        batch_op.create_foreign_key(FK_NAME, 'environments', ['environment_id'], ['id'])

    with op.batch_alter_table('phase_models', schema=None) as batch_op:
        batch_op.drop_column('deployed_at')


def downgrade() -> None:
    """환경 FK 와 테이블 제거, deployed_at 은 빈 값으로 복구"""
    with op.batch_alter_table('phase_models', schema=None) as batch_op:
        batch_op.add_column(sa.Column('deployed_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True))

    with op.batch_alter_table('model_deployments', schema=None) as batch_op:
        batch_op.drop_constraint(FK_NAME, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_model_deployments_environment_id'))
        batch_op.drop_column('environment_id')

    with op.batch_alter_table('environments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_environments_name'))
    op.drop_table('environments')
