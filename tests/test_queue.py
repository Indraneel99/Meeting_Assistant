
from meeting_assistant.services.queue import InMemoryTranscriptQueue


def test_inmemory_transcript_queue_publish_consume_ack() -> None:
    queue = InMemoryTranscriptQueue()
    queue.publish(1, ["chunk-a", "chunk-b", "chunk-c"])

    consumed = queue.consume(1, count=2)

    assert consumed == ["chunk-a", "chunk-b"]
    queue.ack(1, ["chunk-a"])
    assert queue._pending[1] == ["chunk-b"]
    assert queue.consume(1, count=1) == ["chunk-c"]
    assert queue.consume(1) == []


def test_inmemory_transcript_queue_nack_requeues_chunks() -> None:
    queue = InMemoryTranscriptQueue()
    queue.publish(1, ["chunk-a", "chunk-b"])
    consumed = queue.consume(1, count=2)

    queue.nack(1, consumed)

    assert queue.drain(1) == ["chunk-a", "chunk-b"]


def test_inmemory_transcript_queue_drain_clears_all_chunks() -> None:
    queue = InMemoryTranscriptQueue()
    queue.publish(42, ["one", "two"])

    assert queue.drain(42) == ["one", "two"]
    assert queue.drain(42) == []
