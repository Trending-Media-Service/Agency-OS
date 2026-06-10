# WIRED. Async engine for issue #2 (Postgres+RLS). Used by main.py and tests.
from contextvars import ContextVar
import os
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

# PostgreSQL connection configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/agency_os",
)

engine = create_async_engine(
    DATABASE_URL, echo=False, pool_pre_ping=True, pool_size=10, max_overflow=20
)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)
Base = declarative_base()

# Safe thread-local context storage for the active request's tenant ID
tenant_context: ContextVar[str | None] = ContextVar("tenant_id", default=None)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
  """FastAPI dependency yielding a transaction-scoped PostgreSQL session.

  Injects app.current_tenant_id at the database level for Row-Level Security.
  """
  async with AsyncSessionLocal() as session:
    async with session.begin():
      tenant_id = tenant_context.get()
      if tenant_id and session.bind.dialect.name == "postgresql":
        # Local variable valid strictly inside the active transaction block
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
      yield session
