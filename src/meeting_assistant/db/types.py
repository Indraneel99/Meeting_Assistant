from __future__ import annotations

import json
from typing import Any

from sqlalchemy.types import TypeDecorator, UserDefinedType

EMBEDDING_DIMENSIONS = 1536


class EmbeddingVector(TypeDecorator[list[float]]):
    """Store embeddings as JSON text on SQLite and pgvector on Postgres."""

    impl = UserDefinedType
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(EMBEDDING_DIMENSIONS))
        from sqlalchemy import Text

        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: list[float] | None, dialect: Any) -> list[float] | str | None:
        if value is None or value == []:
            if dialect.name == "postgresql":
                return None
            return "[]"
        if dialect.name == "postgresql":
            return value
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Any) -> list[float]:
        if value is None:
            return []
        if isinstance(value, list):
            return [float(item) for item in value]
        if isinstance(value, str):
            if not value or value == "[]":
                return []
            return [float(item) for item in json.loads(value)]
        return [float(item) for item in value]
