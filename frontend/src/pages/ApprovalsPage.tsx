import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { approveRequest, listWorkflowApprovals, rejectRequest } from "../api/client";
import type { ApprovalRequestResponse } from "../api/types";
import { useConfig } from "../context/ConfigContext";
import { useSession } from "../context/SessionContext";

export function ApprovalsPage() {
  const { config } = useConfig();
  const { activeWorkflowRunId, setActiveWorkflowRunId } = useSession();
  const [searchParams, setSearchParams] = useSearchParams();
  const workflowFromUrl = searchParams.get("workflow") ?? "";
  const resolvedWorkflowId = workflowFromUrl || activeWorkflowRunId;
  const [workflowRunId, setWorkflowRunId] = useState(resolvedWorkflowId);
  const [approvals, setApprovals] = useState<ApprovalRequestResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionId, setActionId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function loadApprovals(id: string) {
    if (!id.trim()) {
      setError("Enter a workflow run ID");
      return;
    }

    setLoading(true);
    setError(null);
    setMessage(null);

    try {
      const result = await listWorkflowApprovals(config, Number(id));
      setApprovals(result);
      const workflowId = String(id);
      setWorkflowRunId(workflowId);
      setActiveWorkflowRunId(workflowId);
      setSearchParams({ workflow: workflowId }, { replace: true });
    } catch (loadError) {
      setApprovals([]);
      setError(loadError instanceof Error ? loadError.message : "Failed to load approvals");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (resolvedWorkflowId && resolvedWorkflowId !== workflowRunId) {
      setWorkflowRunId(resolvedWorkflowId);
    }
  }, [resolvedWorkflowId, workflowRunId]);

  useEffect(() => {
    if (resolvedWorkflowId) {
      void loadApprovals(resolvedWorkflowId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedWorkflowId, config.baseUrl, config.accessToken]);

  async function handleDecision(approvalRequestId: number, action: "approve" | "reject") {
    setActionId(approvalRequestId);
    setError(null);
    setMessage(null);

    try {
      const result =
        action === "approve"
          ? await approveRequest(config, approvalRequestId, config.userExternalId)
          : await rejectRequest(config, approvalRequestId, config.userExternalId);
      setMessage(`Workflow ${result.workflow_status}: ${result.summary}`);
      await loadApprovals(String(result.workflow_run_id));
    } catch (decisionError) {
      setError(decisionError instanceof Error ? decisionError.message : "Action failed");
    } finally {
      setActionId(null);
    }
  }

  return (
    <section className="panel">
      <h1>Approval inbox</h1>
      <p className="lede">Review pending tool actions (for example calendar holds) and approve or reject them.</p>

      <form
        className="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          void loadApprovals(workflowRunId);
        }}
      >
        <label>
          Workflow run ID
          <input value={workflowRunId} onChange={(event) => setWorkflowRunId(event.target.value)} required />
        </label>
        <button type="submit" disabled={loading}>
          {loading ? "Loading..." : "Load approvals"}
        </button>
      </form>

      {message && <p className="success">{message}</p>}
      {error && <p className="error">{error}</p>}

      {approvals.length === 0 && !loading && !error && !resolvedWorkflowId && (
        <p className="muted">Submit a batch first or enter a workflow run ID.</p>
      )}

      {approvals.length === 0 && !loading && !error && resolvedWorkflowId && (
        <p className="muted">No approvals found for workflow #{resolvedWorkflowId}.</p>
      )}

      <div className="stack">
        {approvals.map((approval) => (
          <article key={approval.approval_request_id} className="result-card">
            <div className="status-row">
              <h2>
                {approval.tool_name} · request #{approval.approval_request_id}
              </h2>
              <span className={`badge badge-${approval.status}`}>{approval.status}</span>
            </div>
            <p className="muted">Workflow {approval.workflow_run_id}</p>
            <pre className="payload">{JSON.stringify(approval.payload, null, 2)}</pre>

            {approval.status === "pending" && (
              <div className="button-row">
                <button
                  type="button"
                  disabled={actionId === approval.approval_request_id}
                  onClick={() => void handleDecision(approval.approval_request_id, "approve")}
                >
                  Approve
                </button>
                <button
                  type="button"
                  className="danger"
                  disabled={actionId === approval.approval_request_id}
                  onClick={() => void handleDecision(approval.approval_request_id, "reject")}
                >
                  Reject
                </button>
              </div>
            )}

            {approval.resolved_at && (
              <p className="muted">
                Resolved by {approval.resolved_by ?? "unknown"} at {new Date(approval.resolved_at).toLocaleString()}
              </p>
            )}
          </article>
        ))}
      </div>

      {workflowRunId && (
        <Link className="inline-link" to={`/workflow?id=${workflowRunId}`}>
          Back to workflow status →
        </Link>
      )}
    </section>
  );
}
