import { Link } from "react-router-dom";
import { useSession } from "../context/SessionContext";

export function ActiveWorkflowBanner() {
  const { activeWorkflowRunId } = useSession();

  if (!activeWorkflowRunId) {
    return null;
  }

  return (
    <section className="panel compact">
      <h2>Active workflow</h2>
      <p className="workflow-id">#{activeWorkflowRunId}</p>
      <div className="button-row">
        <Link className="text-button" to={`/workflow?id=${activeWorkflowRunId}`}>
          Status
        </Link>
        <Link className="text-button" to={`/approvals?workflow=${activeWorkflowRunId}`}>
          Approvals
        </Link>
      </div>
    </section>
  );
}
