"""Administrative command-line interface."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import click
import httpx
import structlog
import uvicorn
from redis.asyncio import Redis
from safir.asyncio import run_with_asyncio
from safir.database import (
    create_database_engine,
    is_database_current,
    stamp_database,
)
from safir.dependencies.db_session import db_session_dependency

from timessquare.dependencies.redis import redis_dependency

from .config import config
from .database import init_database
from .storage.nbhtmlcache import NbHtmlCacheStore
from .worker.servicefactory import create_page_service


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(message="%(version)s")
def main() -> None:
    """times-square.

    Administrative command-line interface for Times Square.
    """


@main.command()
@click.argument("topic", default=None, required=False, nargs=1)
@click.pass_context
def help(ctx: click.Context, topic: str | None) -> None:
    """Show help for any command."""
    # The help command implementation is taken from
    # https://www.burgundywall.com/post/having-click-help-subcommand
    if topic:
        if topic in main.commands:
            click.echo(main.commands[topic].get_help(ctx))
        else:
            raise click.UsageError(f"Unknown help topic {topic}", ctx)
    else:
        if not ctx.parent:
            raise RuntimeError("help called without topic or parent")
        click.echo(ctx.parent.get_help())


@main.command()
@click.option(
    "--port", default=8080, type=int, help="Port to run the application on."
)
def develop(port: int) -> None:
    """Run the application with live reloading (for development only)."""
    uvicorn.run(
        "timessquare.main:app", port=port, reload=True, reload_dirs=["src"]
    )


@main.command()
@click.option(
    "--alembic-config-path",
    envvar="TS_ALEMBIC_CONFIG_PATH",
    type=click.Path(path_type=Path),
    help="Alembic configuration file.",
)
@click.option(
    "--reset", is_flag=True, help="Delete all existing database data."
)
def init(*, alembic_config_path: Path, reset: bool) -> None:
    """Initialize the SQL database storage."""
    logger = structlog.get_logger("timessquare")
    logger.debug("Initializing database")
    asyncio.run(init_database(config, logger, reset=reset))
    stamp_database(alembic_config_path)
    logger.debug("Finished initializing data stores")


@main.command()
@click.option(
    "--alembic-config-path",
    envvar="TS_ALEMBIC_CONFIG_PATH",
    type=click.Path(path_type=Path),
    help="Alembic configuration file.",
)
def update_db_schema(*, alembic_config_path: Path) -> None:
    """Update the SQL database schema."""
    subprocess.run(
        ["alembic", "upgrade", "head"],
        check=True,
        cwd=str(alembic_config_path.parent),
    )


@main.command()
@click.option(
    "--alembic-config-path",
    envvar="TS_ALEMBIC_CONFIG_PATH",
    type=click.Path(path_type=Path),
    help="Alembic configuration file.",
)
@run_with_asyncio
async def validate_db_schema(*, alembic_config_path: Path) -> None:
    """Validate that the SQL database schema is current."""
    engine = create_database_engine(
        config.database_url, config.database_password
    )
    logger = structlog.get_logger("timessquare")
    if not await is_database_current(engine, logger, alembic_config_path):
        raise click.ClickException("Database schema is not current")


@main.command("reset-html")
@run_with_asyncio
async def reset_html() -> None:
    """Reset the Redis-based HTML result cache."""
    redis = Redis.from_url(str(config.redis_url), password=None)
    try:
        html_store = NbHtmlCacheStore(redis)
        html_store.scan("*")
        n = len([r async for r in html_store.scan("*")])
        await html_store.delete_all("*")
        click.echo(f"Deleted {n} HTML records")
    except Exception as e:
        click.echo(str(e))
    finally:
        await redis.close()
        await redis.connection_pool.disconnect()


@main.command("migrate-html-cache")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Perform a dry run without modifying the cache.",
)
@click.option(
    "--page",
    help="Migrate only the cache keys for the specified page.",
)
@run_with_asyncio
async def migrate_html_cache(
    *, dry_run: bool = True, page: str | None = None
) -> None:
    """Migrate the redis cache to the new format."""
    # Create a database session
    engine = create_database_engine(
        config.database_url, config.database_password
    )
    logger = structlog.get_logger("timessquare")
    if not await is_database_current(engine, logger):
        raise RuntimeError("Database schema out of date")
    await engine.dispose()
    await db_session_dependency.initialize(
        str(config.database_url), config.database_password.get_secret_value()
    )
    await redis_dependency.initialize(str(config.redis_url))

    async for db_session in db_session_dependency():
        page_service = await create_page_service(
            http_client=httpx.AsyncClient(),
            logger=structlog.get_logger("timessquare"),
            db_session=db_session,
        )
        key_count = await page_service.migrate_html_cache_keys(
            dry_run=dry_run, for_page_id=page
        )
        logger.info(
            "Finished migrating HTML cache keys",
            key_count=key_count,
            dry_run=dry_run,
        )


@main.command("nbstripout")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Perform a dry run without modifying ipynb sources.",
)
@click.option(
    "--page",
    help="Run nbstripout only for the specified page.",
)
@run_with_asyncio
async def run_nbstripout(
    *, dry_run: bool = True, page: str | None = None
) -> None:
    """Run nbstripout on ipynb sources.

    This is a one-time migration operation to remove outputs and kernelspec
    metadata from the page ipynb sources. New pages have nbstripout run
    automatically.
    """
    # Create a database session
    engine = create_database_engine(
        config.database_url, config.database_password
    )
    logger = structlog.get_logger("timessquare")
    if not await is_database_current(engine, logger):
        raise RuntimeError("Database schema out of date")
    await engine.dispose()
    await db_session_dependency.initialize(
        str(config.database_url), config.database_password.get_secret_value()
    )
    await redis_dependency.initialize(str(config.redis_url))

    async for db_session in db_session_dependency():
        page_service = await create_page_service(
            http_client=httpx.AsyncClient(),
            logger=structlog.get_logger("timessquare"),
            db_session=db_session,
        )
        count = await page_service.migrate_ipynb_with_nbstripout(
            dry_run=dry_run, for_page_id=page, db_session=db_session
        )
        logger.info(
            "Finished running nbstripout",
            count=count,
            dry_run=dry_run,
        )
        await db_session.commit()
