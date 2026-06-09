import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from meeting_assistant.api.deps import get_container
from meeting_assistant.container import Container

router = APIRouter(tags=["admin"])


@router.get("/admin/approvals/{approval_request_id}", response_class=HTMLResponse)
def approval_admin_page(
    approval_request_id: int,
    container: Container = Depends(get_container),
) -> HTMLResponse:
    request = container.repository.get_approval_request(approval_request_id)
    if request is None:
        raise HTTPException(status_code=404, detail=f"Approval request {approval_request_id} not found")

    payload = json.dumps(json.loads(request.payload), indent=2)
    pending = request.status.value == "pending"
    actions = ""
    if pending:
        actions = f"""
  <button class="approve" onclick="resolve('approve')">Approve</button>
  <button class="reject" onclick="resolve('reject')">Reject</button>
  <p id="result"></p>
  <script>
    async function resolve(action) {{
      const response = await fetch('/api/v1/approvals/{request.id}/' + action, {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ resolved_by: 'admin-ui' }}),
      }});
      const data = await response.json();
      document.getElementById('result').textContent = response.ok
        ? 'Workflow status: ' + data.workflow_status
        : 'Error: ' + (data.detail || JSON.stringify(data));
    }}
  </script>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Approval Request #{request.id}</title>
  <style>
    body {{ font-family: sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }}
    .meta {{ background: #f5f5f5; padding: 1rem; border-radius: 8px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; }}
    button {{ padding: 0.5rem 1rem; cursor: pointer; margin-right: 0.5rem; }}
    .approve {{ background: #1a7f37; color: white; border: none; border-radius: 4px; }}
    .reject {{ background: #cf222e; color: white; border: none; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Approval Request #{request.id}</h1>
  <div class="meta">
    <p><strong>Workflow:</strong> {request.workflow_run_id}</p>
    <p><strong>Tool:</strong> {request.tool_name}</p>
    <p><strong>Status:</strong> {request.status.value}</p>
    <p><strong>Payload:</strong></p>
    <pre>{payload}</pre>
  </div>
  {actions if pending else '<p>This request has already been resolved.</p>'}
</body>
</html>"""
    return HTMLResponse(content=html)
