import { FormEvent, useEffect, useState } from "react";
import { searchChunks, searchDecisions, searchMeetings } from "../api/client";
import type { ChunkSearchResult, DecisionItem, MeetingSearchResult } from "../api/types";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { useConfig } from "../context/ConfigContext";
import { useSession } from "../context/SessionContext";
import { emptyPaginatedState, type PaginatedState } from "../hooks/pagination";

const PAGE_SIZE = 5;

export function SearchPage() {
  const { config } = useConfig();
  const { searchQuery, setSearchQuery } = useSession();
  const [query, setQuery] = useState(searchQuery);
  const [meetings, setMeetings] = useState<PaginatedState<MeetingSearchResult>>(emptyPaginatedState);
  const [chunks, setChunks] = useState<PaginatedState<ChunkSearchResult>>(emptyPaginatedState);
  const [decisions, setDecisions] = useState<PaginatedState<DecisionItem>>(emptyPaginatedState);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  async function runSearch(searchTerm: string) {
    setLoading(true);
    setError(null);
    setHasSearched(true);
    setSearchQuery(searchTerm);

    try {
      const [meetingResults, chunkResults, decisionResults] = await Promise.all([
        searchMeetings(config, searchTerm, PAGE_SIZE),
        searchChunks(config, searchTerm, PAGE_SIZE),
        searchDecisions(config, searchTerm, PAGE_SIZE),
      ]);

      setMeetings({
        items: meetingResults.results,
        nextCursor: meetingResults.next_cursor,
        hasMore: meetingResults.has_more,
        loadingMore: false,
      });
      setChunks({
        items: chunkResults.results,
        nextCursor: chunkResults.next_cursor,
        hasMore: chunkResults.has_more,
        loadingMore: false,
      });
      setDecisions({
        items: decisionResults.results,
        nextCursor: decisionResults.next_cursor,
        hasMore: decisionResults.has_more,
        loadingMore: false,
      });
    } catch (searchError) {
      setMeetings(emptyPaginatedState());
      setChunks(emptyPaginatedState());
      setDecisions(emptyPaginatedState());
      setError(searchError instanceof Error ? searchError.message : "Search failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    await runSearch(query);
  }

  useEffect(() => {
    if (searchQuery) {
      void runSearch(searchQuery);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadMoreMeetings() {
    if (!meetings.nextCursor || meetings.loadingMore) {
      return;
    }

    setMeetings((current) => ({ ...current, loadingMore: true }));
    try {
      const response = await searchMeetings(config, query, PAGE_SIZE, meetings.nextCursor);
      setMeetings((current) => ({
        items: [...current.items, ...response.results],
        nextCursor: response.next_cursor,
        hasMore: response.has_more,
        loadingMore: false,
      }));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load more meetings");
      setMeetings((current) => ({ ...current, loadingMore: false }));
    }
  }

  async function loadMoreChunks() {
    if (!chunks.nextCursor || chunks.loadingMore) {
      return;
    }

    setChunks((current) => ({ ...current, loadingMore: true }));
    try {
      const response = await searchChunks(config, query, PAGE_SIZE, chunks.nextCursor);
      setChunks((current) => ({
        items: [...current.items, ...response.results],
        nextCursor: response.next_cursor,
        hasMore: response.has_more,
        loadingMore: false,
      }));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load more chunks");
      setChunks((current) => ({ ...current, loadingMore: false }));
    }
  }

  async function loadMoreDecisions() {
    if (!decisions.nextCursor || decisions.loadingMore) {
      return;
    }

    setDecisions((current) => ({ ...current, loadingMore: true }));
    try {
      const response = await searchDecisions(config, query, PAGE_SIZE, decisions.nextCursor);
      setDecisions((current) => ({
        items: [...current.items, ...response.results],
        nextCursor: response.next_cursor,
        hasMore: response.has_more,
        loadingMore: false,
      }));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load more decisions");
      setDecisions((current) => ({ ...current, loadingMore: false }));
    }
  }

  return (
    <section className="panel">
      <h1>Search meetings</h1>
      <p className="lede">Semantic search across meeting summaries, transcript chunks, and logged decisions.</p>

      <form className="inline-form" onSubmit={handleSearch}>
        <label>
          Query
          <input value={query} onChange={(event) => setQuery(event.target.value)} required />
        </label>
        <button type="submit" disabled={loading}>
          {loading ? "Searching..." : "Search"}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      <div className="search-grid">
        <div className="result-card">
          <h2>Meetings</h2>
          {meetings.items.length === 0 ? (
            <p className="muted">{hasSearched ? "No meeting results." : "Run a search to see meetings."}</p>
          ) : (
            <ul className="list">
              {meetings.items.map((meeting) => (
                <li key={meeting.meeting_id}>
                  <strong>{meeting.title}</strong>
                  <span className="score">score {meeting.score.toFixed(3)}</span>
                  <p>{meeting.summary}</p>
                </li>
              ))}
            </ul>
          )}
          <LoadMoreButton hasMore={meetings.hasMore} loading={meetings.loadingMore} onClick={() => void loadMoreMeetings()} />
        </div>

        <div className="result-card">
          <h2>Transcript chunks</h2>
          {chunks.items.length === 0 ? (
            <p className="muted">{hasSearched ? "No chunk results." : "Run a search to see transcript chunks."}</p>
          ) : (
            <ul className="list">
              {chunks.items.map((chunk) => (
                <li key={chunk.chunk_id}>
                  <strong>
                    {chunk.meeting_title} · chunk {chunk.chunk_index}
                  </strong>
                  <span className="score">score {chunk.score.toFixed(3)}</span>
                  <p>{chunk.text}</p>
                </li>
              ))}
            </ul>
          )}
          <LoadMoreButton hasMore={chunks.hasMore} loading={chunks.loadingMore} onClick={() => void loadMoreChunks()} />
        </div>

        <div className="result-card">
          <h2>Decisions</h2>
          {decisions.items.length === 0 ? (
            <p className="muted">{hasSearched ? "No decision results." : "Run a search to see decisions."}</p>
          ) : (
            <ul className="list">
              {decisions.items.map((decision) => (
                <li key={decision.decision_id}>
                  <strong>{decision.topic}</strong>
                  <span className="score">score {decision.score.toFixed(3)}</span>
                  <p>{decision.decision_text}</p>
                </li>
              ))}
            </ul>
          )}
          <LoadMoreButton
            hasMore={decisions.hasMore}
            loading={decisions.loadingMore}
            onClick={() => void loadMoreDecisions()}
          />
        </div>
      </div>
    </section>
  );
}
