from pydantic import BaseModel, Field


class MeetingSearchResult(BaseModel):
    meeting_id: int
    title: str
    summary: str
    score: float


class SearchMeetingsResponse(BaseModel):
    results: list[MeetingSearchResult]


class MeetingTask(BaseModel):
    assignee: str
    action: str
    status: str


class MeetingTasksResponse(BaseModel):
    meeting_id: int
    tasks: list[MeetingTask]


class DecisionItem(BaseModel):
    meeting_id: int
    topic: str
    decision_text: str


class DecisionsResponse(BaseModel):
    results: list[DecisionItem]


class QueryRequest(BaseModel):
    user_external_id: str
    question: str = Field(min_length=1)


class QueryResponse(BaseModel):
    answer: str
    meetings: list[MeetingSearchResult]
    tasks: list[MeetingTask]
    decisions: list[DecisionItem]
