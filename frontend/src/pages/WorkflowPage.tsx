import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getWorkflowStatus } from "../api/client";
import type { WorkflowStatusResponse } from "../api/types";
import { useConfig } from "../context/ConfigContext";
import { useSession } from "../context/SessionContext";

const TERMINAL_STATUSES = new Set(["done", "failed", "awaiting_approval"]);

export function WorkflowPage() {
  const { config } = useConfig();
  const { activeWorkflowRunId, setActiveWorkflowRunId } = useSession();
  const [searchParams, setSearchParams] = useSearchParams();
  const workflowFromUrl = searchParams.get("id") ?? "";
  const resolvedWorkflowId = workflowFromUrl || activeWorkflowRunId;
  const [workflowRunId, setWorkflowRunId] = useState(resolvedWorkflowId);
  const [status, setStatus] = useState<WorkflowStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);

  const shouldPoll = useMemo(() => status !== null && !TERMINAL_STATUSES.has(status.status), [status]);

  async function fetchStatus(id: string, silent = false) {
    if (!id.trim()) {
      setError("Enter a workflow run ID");
      return;
    }

    if (!silent) {
      setError(null);
    }

    try {
      const result = await getWorkflowStatus(config, Number(id));
      setStatus(result);
      const workflowId = String(result.workflow_run_id);
      setWorkflowRunId(workflowId);
      setActiveWorkflowRunId(workflowId);
      setSearchParams({ id: workflowId }, { replace: true });
    } catch (fetchError) {
      setStatus(null);
      setError(fetchError instanceof Error ? fetchError.message : "Failed to load workflow");
    }
  }

  useEffect(() => {
    if (resolvedWorkflowId && resolvedWorkflowId !== workflowRunId) {
      setWorkflowRunId(resolvedWorkflowId);
    }
  }, [resolvedWorkflowId, workflowRunId]);

  useEffect(() => {
    if (resolvedWorkflowId) {
      void fetchStatus(resolvedWorkflowId, true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedWorkflowId, config.baseUrl, config.accessToken]);

  useEffect(() => {
    if (!shouldPoll || !workflowRunId) {
      setPolling(false);
      return;
    }

    setPolling(true);
    const timer = window.setInterval(() => {
      void fetchStatus(workflowRunId, true);
    }, 3000);

    return () => {
      window.clearInterval(timer);
      setPolling(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shouldPoll, workflowRunId, config.baseUrl, config.accessToken]);

  return (
    <section className="panel">
      <h1>Workflow status</h1>
      <p className="lede">Poll a workflow run to see tool executions and completion state.</p>

      <form
        className="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          void fetchStatus(workflowRunId);
        }}
      >
        <label>
          Workflow run ID
          <input value={workflowRunId} onChange={(event) => setWorkflowRunId(event.target.value)} required />
        </label>
        <button type="submit">Refresh</button>
      </form>

      {polling && <p className="muted">Auto-refreshing every 3 seconds…</p>}
      {error && <p className="error">{error}</p>}

      {status && (
        <div className="stack">
          <div className="result-card">
            <div className="status-row">
              <h2>Run #{status.workflow_run_id}</h2>
              <span className={`badge badge-${status.status}`}>{status.status}</span>
            </div>
            <dl className="meta-grid">
              <div>
                <dt>Meeting ID</dt>
                <dd>{status.meeting_id}</dd>
              </div>
              <div>
                <dt>Iterations</dt>
                <dd>{status.iteration_count}</dd>
              </div>
              {status.tasks_created != null && (
                <div>
                  <dt>Tasks</dt>
                  <dd>{status.tasks_created}</dd>
                </div>
              )}
              {status.decisions_logged != null && (
                <div>
                  <dt>Decisions</dt>
                  <dd>{status.decisions_logged}</dd>
                </div>
              )}
            </dl>
            {status.summary && <p>{status.summary}</p>}
            {status.failure_reason && <p className="error">{status.failure_reason}</p>}
            {status.status === "awaiting_approval" && (
              <Link className="inline-link" to={`/approvals?workflow=${status.workflow_run_id}`}>
                Review approvals →
              </Link>
            )}
          </div>

          {status.tool_executions.length > 0 && (
            <div className="result-card">
              <h3>Tool executions</h3>
              <ul className="list">
                {status.tool_executions.map((tool) => (
                  <li key={tool.idempotency_key}>
                    <strong>{tool.tool_name}</strong> · {tool.status} · {tool.attempts} attempt(s)
                    {tool.status === "failed" && typeof tool.result?.error === "string" && (
                      <p className="error tool-error">{tool.result.error}</p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
