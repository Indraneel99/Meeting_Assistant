from __future__ import annotations


def encode_cursor(score: float, item_id: int) -> str:
    return f"{score:.6f}:{item_id}"


def decode_cursor(cursor: str) -> tuple[float, int]:
    score_text, item_id_text = cursor.split(":", 1)
    return float(score_text), int(item_id_text)


def paginate_scored_results(
    scored_items: list[dict[str, object]],
    *,
    limit: int,
    cursor: str | None,
    id_key: str,
) -> tuple[list[dict[str, object]], str | None, bool]:
    if cursor:
        cursor_score, cursor_id = decode_cursor(cursor)
        scored_items = [
            item
            for item in scored_items
            if float(item["score"]) < cursor_score
            or (float(item["score"]) == cursor_score and int(item[id_key]) < cursor_id)
        ]

    has_more = len(scored_items) > limit
    page = scored_items[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(float(last["score"]), int(last[id_key]))
    return page, next_cursor, has_more
