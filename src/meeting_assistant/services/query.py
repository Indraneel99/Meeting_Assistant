from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.retrieval import (
    DecisionItem,
    DecisionsResponse,
    MeetingSearchResult,
    MeetingTask,
    MeetingTasksResponse,
    QueryRequest,
    QueryResponse,
    SearchMeetingsResponse,
)
from meeting_assistant.services.embeddings import InMemoryEmbeddingIndex


class QueryService:
    def __init__(self, repository: Repository, embedding_index: InMemoryEmbeddingIndex) -> None:
        self.repository = repository
        self.embedding_index = embedding_index

    def search_past_meetings(self, user_external_id: str, query: str, limit: int) -> SearchMeetingsResponse:
        user = self.repository.get_user_by_external_id(user_external_id)
        if not user:
            return SearchMeetingsResponse(results=[])

        results = self.embedding_index.search_for_user(self.repository, user.id, query, limit)
        return SearchMeetingsResponse(
            results=[MeetingSearchResult(**item) for item in results]
        )

    def get_meeting_tasks(self, meeting_id: int) -> MeetingTasksResponse:
        tasks = self.repository.get_tasks_for_meeting(meeting_id)
        return MeetingTasksResponse(
            meeting_id=meeting_id,
            tasks=[MeetingTask(assignee=task.assignee, action=task.action, status=task.status) for task in tasks],
        )

    def get_decisions(self, user_external_id: str, topic: str, limit: int) -> DecisionsResponse:
        user = self.repository.get_user_by_external_id(user_external_id)
        if not user:
            return DecisionsResponse(results=[])

        topic_lower = topic.lower()
        decisions = [
            decision
            for decision in self.repository.get_decisions_for_user(user.id)
            if topic_lower in decision.topic.lower() or topic_lower in decision.decision_text.lower()
        ]
        return DecisionsResponse(
            results=[
                DecisionItem(meeting_id=decision.meeting_id, topic=decision.topic, decision_text=decision.decision_text)
                for decision in decisions[:limit]
            ]
        )

    def answer(self, payload: QueryRequest) -> QueryResponse:
        meetings = self.search_past_meetings(payload.user_external_id, payload.question, 3).results
        tasks = self.get_meeting_tasks(meetings[0].meeting_id).tasks if meetings else []
        decisions = self.get_decisions(payload.user_external_id, payload.question, 3).results

        if meetings:
            answer = f"Most relevant meeting: {meetings[0].title}. {meetings[0].summary}"
        else:
            answer = "No matching meeting history was found for that question yet."

        return QueryResponse(answer=answer, meetings=meetings, tasks=tasks, decisions=decisions)
