import asyncio
import os
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Ensure we can import app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from alembic.config import Config
from alembic import command
from app.database import DATABASE_URL

def run_upgrade(connection, cfg):
    cfg.attributes['connection'] = connection
    command.upgrade(cfg, "head")

async def migrate(engine=None):
    if engine is None:
        print(f"Connecting to {DATABASE_URL}...")
        engine = create_async_engine(DATABASE_URL, echo=True)
        should_dispose = True
    else:
        should_dispose = False

    print("Running database migrations via Alembic...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ini_path = os.path.join(base_dir, "alembic.ini")
    alembic_cfg = Config(ini_path)
    async with engine.begin() as conn:

        await conn.run_sync(run_upgrade, alembic_cfg)

    print("Migration complete.")
    if should_dispose:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(migrate())
