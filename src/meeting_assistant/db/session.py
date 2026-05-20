from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import Base

settings = Settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    _apply_sqlite_compat_migrations()


def _apply_sqlite_compat_migrations() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    workflow_columns = {column["name"] for column in inspector.get_columns("workflow_runs")}
    with engine.begin() as connection:
        if "iteration_count" not in workflow_columns:
            connection.execute(
                text("ALTER TABLE workflow_runs ADD COLUMN iteration_count INTEGER DEFAULT 0 NOT NULL")
            )
