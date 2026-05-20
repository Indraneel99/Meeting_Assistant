from dataclasses import dataclass

from meeting_assistant.core.config import Settings
from meeting_assistant.repositories import Repository
from meeting_assistant.services.orchestrator import BatchOrchestrator
from meeting_assistant.services.query import QueryService


@dataclass(slots=True)
class Container:
    settings: Settings
    repository: Repository
    orchestrator: BatchOrchestrator
    query_service: QueryService
