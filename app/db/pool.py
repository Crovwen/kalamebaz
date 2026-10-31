from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


async def create_pool(dsn: str) -> asyncpg.Pool:
    # statement_cache_size=0 با pgbouncer (Neon/Supabase pooler) سازگار است.
    return await asyncpg.create_pool(
        dsn, min_size=1, max_size=5, statement_cache_size=0, command_timeout=30
    )


async def migrate(pool: asyncpg.Pool, directory: Path = MIGRATIONS_DIR) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())"
        )
        done = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}
        for f in sorted(directory.glob("*.sql")):
            if f.name in done:
                continue
            log.info("اجرای migration: %s", f.name)
            async with conn.transaction():
                await conn.execute(f.read_text(encoding="utf-8"))
                await conn.execute("INSERT INTO schema_migrations(name) VALUES($1)", f.name)
