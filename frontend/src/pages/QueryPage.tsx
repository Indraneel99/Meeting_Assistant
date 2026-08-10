import { FormEvent, useState } from "react";
import { answerQuery } from "../api/client";
import type { QueryResponse } from "../api/types";
import { useConfig } from "../context/ConfigContext";
import { useSession } from "../context/SessionContext";

export function QueryPage() {
  const { config } = useConfig();
  const { lastQuestion, setLastQuestion } = useSession();
  const [question, setQuestion] = useState(lastQuestion);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    setLastQuestion(question);

    try {
      const response = await answerQuery(config, question);
      setResult(response);
    } catch (queryError) {
      setError(queryError instanceof Error ? queryError.message : "Query failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel">
      <h1>Ask a question</h1>
      <p className="lede">RAG query over meetings, chunks, tasks, and decisions with citations.</p>

      <form className="stack" onSubmit={handleSubmit}>
        <label>
          Question
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            rows={4}
            placeholder="What decisions were made about the launch timeline?"
            required
          />
        </label>
        <button type="submit" disabled={loading}>
          {loading ? "Thinking..." : "Ask"}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {result && (
        <div className="stack">
          <div className="result-card">
            <h2>Answer</h2>
            <p className="answer">{result.answer}</p>
          </div>

          {result.citations.length > 0 && (
            <div className="result-card">
              <h3>Citations</h3>
              <ul className="list citation-list">
                {result.citations.map((citation, index) => (
                  <li key={`${citation.meeting_id}-${citation.source_type}-${index}`}>
                    <div className="citation-header">
                      <strong>{citation.meeting_title}</strong>
                      <span className="badge badge-citation">{citation.source_type}</span>
                    </div>
                    <p>{citation.excerpt}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {(result.meetings.length > 0 ||
            result.chunks.length > 0 ||
            result.tasks.length > 0 ||
            result.decisions.length > 0) && (
            <div className="result-card">
              <h3>Retrieved context</h3>
              <div className="context-grid">
                {result.meetings.length > 0 && (
                  <section>
                    <h4>Meetings ({result.meetings.length})</h4>
                    <ul className="list compact-list">
                      {result.meetings.map((meeting) => (
                        <li key={meeting.meeting_id}>
                          <strong>{meeting.title}</strong>
                          <span className="score">{meeting.score.toFixed(3)}</span>
                          <p>{meeting.summary}</p>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                {result.chunks.length > 0 && (
                  <section>
                    <h4>Chunks ({result.chunks.length})</h4>
                    <ul className="list compact-list">
                      {result.chunks.map((chunk) => (
                        <li key={chunk.chunk_id}>
                          <strong>
                            {chunk.meeting_title} · #{chunk.chunk_index}
                          </strong>
                          <span className="score">{chunk.score.toFixed(3)}</span>
                          <p>{chunk.text}</p>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                {result.tasks.length > 0 && (
                  <section>
                    <h4>Tasks ({result.tasks.length})</h4>
                    <ul className="list compact-list">
                      {result.tasks.map((task, index) => (
                        <li key={`${task.assignee}-${task.action}-${index}`}>
                          <strong>{task.assignee}</strong> · {task.status}
                          <p>{task.action}</p>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                {result.decisions.length > 0 && (
                  <section>
                    <h4>Decisions ({result.decisions.length})</h4>
                    <ul className="list compact-list">
                      {result.decisions.map((decision) => (
                        <li key={decision.decision_id}>
                          <strong>{decision.topic}</strong>
                          <span className="score">{decision.score.toFixed(3)}</span>
                          <p>{decision.decision_text}</p>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
