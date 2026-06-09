from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from meeting_assistant.core.config import Settings

settings = Settings()

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


def _engine_options(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}

    return {
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        "pool_pre_ping": True,
    }


engine = create_engine(settings.database_url, **_engine_options(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def initialize_database(database_url: str | None = None) -> None:
    target_url = database_url or settings.database_url
    target_engine = engine if target_url == settings.database_url else create_engine(target_url, **_engine_options(target_url))

    if _has_application_tables_without_alembic_version(target_engine):
        _apply_sqlite_compat_migrations(target_engine, target_url)
        _stamp_database(target_url, revision="0001_initial_schema")

    _upgrade_database(target_url)


def _alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["database_url"] = database_url
    return config


def _upgrade_database(database_url: str) -> None:
    command.upgrade(_alembic_config(database_url), "head")


def _stamp_database(database_url: str, revision: str = "head") -> None:
    command.stamp(_alembic_config(database_url), revision)


def _has_application_tables_without_alembic_version(target_engine) -> bool:
    inspector = inspect(target_engine)
    table_names = set(inspector.get_table_names())
    return "users" in table_names and "alembic_version" not in table_names


def _apply_sqlite_compat_migrations(target_engine, database_url: str) -> None:
    if not database_url.startswith("sqlite"):
        return

    inspector = inspect(target_engine)
    table_names = set(inspector.get_table_names())
    with target_engine.begin() as connection:
        if "workflow_runs" in table_names:
            workflow_columns = {column["name"] for column in inspector.get_columns("workflow_runs")}
            if "iteration_count" not in workflow_columns:
                connection.execute(
                    text("ALTER TABLE workflow_runs ADD COLUMN iteration_count INTEGER DEFAULT 0 NOT NULL")
                )
