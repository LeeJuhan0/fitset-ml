import pytest
from sqlmodel import SQLModel
from fastapi.testclient import TestClient

from app.core import db
from app.core.config import settings
from app.main import app as admin_app

ADMIN_AUTH = ("admin", "admin-test-pw")


@pytest.fixture(scope="session", autouse=True)
def _test_database(tmp_path_factory):
    settings.database_url = f"sqlite+aiosqlite:///{tmp_path_factory.mktemp('db') / 'fitset_ml_test.db'}"
    db.reset()

    async def create_all():
        async with db.get_engine().begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    db.run(create_all())
    yield
    db.reset()


@pytest.fixture
def fresh_db():
    from sqlmodel import SQLModel

    async def recreate():
        async with db.get_engine().begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
            await conn.run_sync(SQLModel.metadata.create_all)

    db.run(recreate())
    yield


@pytest.fixture
def client():
    return TestClient(admin_app)


@pytest.fixture
def admin_client(monkeypatch):
    monkeypatch.setattr(settings, "mlflow_ui_user", ADMIN_AUTH[0])
    monkeypatch.setattr(settings, "mlflow_ui_password", ADMIN_AUTH[1])
    c = TestClient(admin_app)
    c.auth = ADMIN_AUTH
    return c


def async_(fn):
    """동기 mock 을 코루틴 함수로 감싼다, await 되는 repository 자리에 쓴다"""
    async def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper
