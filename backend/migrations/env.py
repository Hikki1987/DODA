import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from doda.config import get_settings
from doda.domain.action import approval as action_approval_models  # noqa: F401
from doda.domain.action import models as action_models  # noqa: F401
from doda.domain.audit import models as audit_models  # noqa: F401
from doda.domain.base import Base
from doda.domain.conversation import models as conversation_models  # noqa: F401
from doda.domain.customer import models as customer_models  # noqa: F401

# Import every domain's models so Base.metadata is complete for autogenerate.
from doda.domain.identity import models as identity_models  # noqa: F401
from doda.domain.notification import models as notification_models  # noqa: F401
from doda.domain.outbox import models as outbox_models  # noqa: F401
from doda.domain.security import kill_switch as security_kill_switch_models  # noqa: F401
from doda.domain.task import models as task_models  # noqa: F401
from doda.domain.workspace import models as workspace_models  # noqa: F401

# Note: doda.domain.security.roles/decisions hold only enums, no ORM
# models, so there is nothing to import from them for autogenerate.

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().migration_database_url.get_secret_value())
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
