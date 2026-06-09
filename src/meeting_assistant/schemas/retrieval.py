from pydantic import BaseModel, Field


class MeetingSearchResult(BaseModel):
    meeting_id: int
    title: str
    summary: str
    score: float


class PaginatedSearchMeetingsResponse(BaseModel):
    results: list[MeetingSearchResult]
    next_cursor: str | None = None
    has_more: bool = False


class ChunkSearchResult(BaseModel):
    chunk_id: int
    meeting_id: int
    meeting_title: str
    chunk_index: int
    text: str
    score: float


class PaginatedChunkSearchResponse(BaseModel):
    results: list[ChunkSearchResult]
    next_cursor: str | None = None
    has_more: bool = False


class MeetingTask(BaseModel):
    assignee: str
    action: str
    status: str


class MeetingTasksResponse(BaseModel):
    meeting_id: int
    tasks: list[MeetingTask]


class DecisionItem(BaseModel):
    decision_id: int
    meeting_id: int
    topic: str
    decision_text: str
    score: float


class PaginatedDecisionsResponse(BaseModel):
    results: list[DecisionItem]
    next_cursor: str | None = None
    has_more: bool = False


class QueryCitation(BaseModel):
    meeting_id: int
    meeting_title: str
    source_type: str
    excerpt: str


class QueryRequest(BaseModel):
    user_external_id: str
    question: str = Field(min_length=1)


class QueryResponse(BaseModel):
    answer: str
    citations: list[QueryCitation]
    meetings: list[MeetingSearchResult]
    chunks: list[ChunkSearchResult]
    tasks: list[MeetingTask]
    decisions: list[DecisionItem]
