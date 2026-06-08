from pathlib import Path

from sqlalchemy import create_engine, inspect

from meeting_assistant.db.session import initialize_database


def test_alembic_upgrade_creates_initial_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'meeting_assistant.db'}"

    initialize_database(database_url)

    engine = create_engine(database_url)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    assert "alembic_version" in table_names
    assert {
        "users",
        "meetings",
        "workflow_runs",
        "tool_executions",
        "agent_steps",
    }.issubset(table_names)
    assert "iteration_count" in {column["name"] for column in inspector.get_columns("workflow_runs")}
