import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { submitBatchMeeting, uploadBatchMeeting } from "../api/client";
import type { BatchJobAcceptedResponse, BatchMeetingResponse } from "../api/types";
import { useConfig } from "../context/ConfigContext";
import { useSession } from "../context/SessionContext";

function isAsyncResponse(
  result: BatchMeetingResponse | BatchJobAcceptedResponse,
): result is BatchJobAcceptedResponse {
  return "job_id" in result;
}

export function UploadPage() {
  const { config } = useConfig();
  const {
    uploadDraft,
    lastBatchResult,
    updateUploadDraft,
    setLastBatchResult,
    setActiveWorkflowRunId,
  } = useSession();
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BatchMeetingResponse | BatchJobAcceptedResponse | null>(lastBatchResult);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const response =
        uploadDraft.mode === "text"
          ? await submitBatchMeeting(config, {
              title: uploadDraft.title,
              transcript_text: uploadDraft.transcript,
            })
          : await uploadBatchMeeting(config, { title: uploadDraft.title, audio: audioFile! });
      setResult(response);
      setLastBatchResult(response);
      setActiveWorkflowRunId(String(response.workflow_run_id));
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  const needsApproval = result?.status === "awaiting_approval";

  return (
    <section className="panel">
      <h1>Ingest a meeting</h1>
      <p className="lede">Paste a transcript or upload an audio file to start the batch pipeline.</p>

      <div className="segmented">
        <button
          type="button"
          className={uploadDraft.mode === "text" ? "active" : ""}
          onClick={() => updateUploadDraft({ mode: "text" })}
        >
          Transcript text
        </button>
        <button
          type="button"
          className={uploadDraft.mode === "audio" ? "active" : ""}
          onClick={() => updateUploadDraft({ mode: "audio" })}
        >
          Audio upload
        </button>
      </div>

      <form className="stack" onSubmit={handleSubmit}>
        <label>
          Title
          <input
            value={uploadDraft.title}
            onChange={(event) => updateUploadDraft({ title: event.target.value })}
            required
          />
        </label>

        {uploadDraft.mode === "text" ? (
          <label>
            Transcript
            <textarea
              value={uploadDraft.transcript}
              onChange={(event) => updateUploadDraft({ transcript: event.target.value })}
              rows={12}
              placeholder="Paste meeting transcript. Include keywords like email, calendar, slack for tool actions."
              required
            />
          </label>
        ) : (
          <label>
            Audio file
            <input
              type="file"
              accept="audio/*"
              onChange={(event) => setAudioFile(event.target.files?.[0] ?? null)}
              required
            />
          </label>
        )}

        <button type="submit" disabled={loading}>
          {loading ? "Submitting..." : "Submit batch"}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {result && (
        <div className="result-card">
          <h2>Batch accepted</h2>
          <dl className="meta-grid">
            <div>
              <dt>Meeting ID</dt>
              <dd>{result.meeting_id}</dd>
            </div>
            <div>
              <dt>Workflow run ID</dt>
              <dd>{result.workflow_run_id}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{result.status}</dd>
            </div>
          </dl>

          {!isAsyncResponse(result) && (
            <>
              <p>{result.summary}</p>
              <p className="muted">
                {result.tasks_created} tasks · {result.decisions_logged} decisions · {result.tool_calls_recorded}{" "}
                tool calls
              </p>
            </>
          )}

          <div className="link-row">
            <Link className="inline-link" to={`/workflow?id=${result.workflow_run_id}`}>
              View workflow status →
            </Link>
            {needsApproval && (
              <Link className="inline-link" to={`/approvals?workflow=${result.workflow_run_id}`}>
                Review approvals →
              </Link>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
