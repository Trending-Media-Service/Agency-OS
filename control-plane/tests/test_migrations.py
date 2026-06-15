import pytest
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from alembic.config import Config
from alembic import command
import os
import tempfile
import pathlib
import shutil

@pytest.mark.asyncio
async def test_alembic_migration_roundtrip(db_file):
    engine = create_async_engine(db_file)
    alembic_cfg = Config("alembic.ini")
    
    def run_upgrade(connection):
        alembic_cfg.attributes['connection'] = connection
        command.upgrade(alembic_cfg, "head")
        
    async with engine.begin() as conn:
        await conn.run_sync(run_upgrade)
        
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = {row[0] for row in res.fetchall()}
        assert "tenants" in tables
        assert "ops" in tables
        assert "audit_events" in tables

    def run_downgrade(connection):
        alembic_cfg.attributes['connection'] = connection
        command.downgrade(alembic_cfg, "base")
        
    async with engine.begin() as conn:
        await conn.run_sync(run_downgrade)
        
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = {row[0] for row in res.fetchall()}
        assert "tenants" not in tables
        assert "ops" not in tables

    async with engine.begin() as conn:
        await conn.run_sync(run_upgrade)
        
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = {row[0] for row in res.fetchall()}
        assert "tenants" in tables
        assert "ops" in tables
        
    await engine.dispose()


@pytest.mark.asyncio
async def test_schema_parity_metadata_vs_alembic():
    """Asserts that schema created via Alembic matches schema created via Base.metadata.create_all."""
    from app.models import Base
    
    temp_dir = tempfile.mkdtemp()
    db_alembic_path = pathlib.Path(temp_dir) / "alembic.db"
    db_metadata_path = pathlib.Path(temp_dir) / "metadata.db"
    
    engine_alembic = create_async_engine(f"sqlite+aiosqlite:///{db_alembic_path}")
    engine_metadata = create_async_engine(f"sqlite+aiosqlite:///{db_metadata_path}")
    
    # 1. Bootstrap metadata DB
    async with engine_metadata.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # 2. Bootstrap alembic DB
    alembic_cfg = Config("alembic.ini")
    def run_upgrade(connection):
        alembic_cfg.attributes['connection'] = connection
        command.upgrade(alembic_cfg, "head")
    async with engine_alembic.begin() as conn:
        await conn.run_sync(run_upgrade)
        
    # 3. Compare schemas
    def get_schema_summary(connection):
        insp = inspect(connection)
        summary = {}
        # Get tables
        for table_name in insp.get_table_names():
            if table_name == "alembic_version":
                continue
            columns = {}
            for col in insp.get_columns(table_name):
                # Save name, type name, and nullability
                columns[col["name"]] = {
                    "type": str(col["type"]),
                    "nullable": col["nullable"]
                }
            summary[table_name] = {
                "columns": columns,
                "primary_keys": insp.get_pk_constraint(table_name).get("constrained_columns", [])
            }
        return summary

    async with engine_metadata.connect() as conn:
        schema_metadata = await conn.run_sync(get_schema_summary)
        
    async with engine_alembic.connect() as conn:
        schema_alembic = await conn.run_sync(get_schema_summary)
        
    # Clean up DB connections
    await engine_metadata.dispose()
    await engine_alembic.dispose()
    shutil.rmtree(temp_dir)
    
    # Assert schemas are identical
    assert schema_metadata.keys() == schema_alembic.keys(), f"Tables mismatch: metadata={schema_metadata.keys()}, alembic={schema_alembic.keys()}"
    
    for table in schema_metadata:
        meta_table = schema_metadata[table]
        alembic_table = schema_alembic[table]
        assert meta_table["primary_keys"] == alembic_table["primary_keys"], f"PK mismatch on table {table}"
        assert meta_table["columns"] == alembic_table["columns"], f"Columns mismatch on table {table}:\nMetadata: {meta_table['columns']}\nAlembic: {alembic_table['columns']}"
