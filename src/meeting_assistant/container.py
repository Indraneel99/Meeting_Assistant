from dataclasses import dataclass

from meeting_assistant.core.config import Settings
from meeting_assistant.repositories import Repository
from meeting_assistant.services.agent import AgentRuntime
from meeting_assistant.services.approvals import ApprovalService
from meeting_assistant.services.audio_storage import AudioUploadStore
from meeting_assistant.services.orchestrator import BatchOrchestrator
from meeting_assistant.services.query import QueryService


@dataclass(slots=True)
class Container:
    settings: Settings
    repository: Repository
    agent_runtime: AgentRuntime
    orchestrator: BatchOrchestrator
    query_service: QueryService
    audio_upload_store: AudioUploadStore
    approval_service: ApprovalService
