import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import get_db
from app.main import create_app
from app.models import Base


@pytest.fixture
def session_factory(tmp_path):
    database = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def create_schema():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    yield factory
    asyncio.run(engine.dispose())


@pytest.fixture
def app(session_factory):
    application = create_app()

    async def override_db():
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
