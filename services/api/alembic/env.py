from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from careos.config import get_settings
from careos.db.models import Base, assert_every_table_is_classified

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Fail the migration run rather than the security review: a table that is neither
# tenant-scoped nor explicitly global must never reach a database.
assert_every_table_is_classified()


def _url() -> str:
    return get_settings().migration_database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # Server defaults are declared in migrations (so existing rows get a value on an
        # ALTER) while the models declare Python-side defaults (so ORM inserts work without
        # a round-trip). Both are correct, and autogenerate cannot reconcile them — it
        # compares a parsed SQL expression against a Python callable and always reports a
        # difference. Comparing them would make `alembic check` permanently red and train
        # everyone to ignore it, which would defeat the structural drift detection that
        # check exists for: missing tables, columns, indexes, and foreign keys.
        compare_server_default=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_async_engine(_url(), poolclass=None)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
