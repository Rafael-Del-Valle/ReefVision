from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from alembic.util import CommandError
from sqlalchemy import engine_from_config, pool, text

from reefvision.config import get_settings
from reefvision.db import models as _models  # noqa: F401
from reefvision.db.base import Base
from reefvision.db.migration_lineage import LEGACY_NUMERIC_REVISIONS, resolve_legacy_revision

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

if not config.get_main_option("sqlalchemy.url"):
    settings = get_settings()
    settings.ensure_directories()
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url.replace("%", "%%"))
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

    start_revision = context.get_context().opts.get("starting_rev")
    if start_revision in LEGACY_NUMERIC_REVISIONS:
        raise CommandError(
            f"Legacy revision {start_revision} requires an online upgrade "
            "to identify the database history before changing the schema."
        )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.begin() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        migration_context = context.get_context()

        # Alembic uses a string destination for upgrade and downgrade, a
        # tuple for stamp, and no destination for read-only commands.
        if isinstance(migration_context.opts.get("destination_rev"), str):
            # SQLite's legacy transaction control otherwise leaves DDL before
            # the first write outside the transaction. Lock before inspection.
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            heads = migration_context.get_current_heads()
            replacement = resolve_legacy_revision(connection, heads)
            if replacement is not None:
                connection.execute(
                    text("UPDATE alembic_version SET version_num = :new WHERE version_num = :old"),
                    {"new": replacement, "old": heads[0]},
                )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
