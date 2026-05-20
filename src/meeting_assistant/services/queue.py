from collections import defaultdict


class InMemoryTranscriptQueue:
    def __init__(self) -> None:
        self._messages: dict[int, list[str]] = defaultdict(list)

    def publish(self, meeting_id: int, chunks: list[str]) -> None:
        self._messages[meeting_id].extend(chunks)

    def drain(self, meeting_id: int) -> list[str]:
        chunks = list(self._messages[meeting_id])
        self._messages[meeting_id].clear()
        return chunks
