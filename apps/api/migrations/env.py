from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from reefvision.config import get_settings
from reefvision.db import models as _models  # noqa: F401
from reefvision.db.base import Base
from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038

config = context.config
# Desktop supplies its own rotating JSON logger before Alembic runs. Reapplying
# alembic.ini's fileConfig would remove that handler and hide migration failures.
# Preserve normal CLI logging unless the caller explicitly disables it.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

# The desktop verifies its database before and after upgrading. Alembic must
# migrate that *same* database rather than resolving a second Settings instance
# (which can differ in a frozen sidecar or test environment).
desktop_database_url = config.attributes.get("desktop_database_url")
if desktop_database_url is not None:
    if not isinstance(desktop_database_url, str) or not desktop_database_url.strip():
        raise RuntimeError("Invalid pinned desktop Alembic database URL")
    database_url = desktop_database_url
else:
    settings = get_settings()
    settings.ensure_directories()
    database_url = settings.resolved_database_url
config.set_main_option("sqlalchemy.url", database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # SQLAlchemy 2 starts an implicit transaction even on SQLite, while
    # Alembic's SQLite context.begin_transaction() is a no-op for DDL.
    # Closing a bare Connection therefore rolls back the alembic_version
    # INSERT/UPDATE although schema changes have already taken effect.
    # Own the outer transaction so revision bookkeeping is committed only
    # after a successful migration (and rolled back on failure).
    with connectable.begin() as connection:
        assert_compatible_revision_0038(connection)
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
