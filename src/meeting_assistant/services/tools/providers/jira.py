from __future__ import annotations

import httpx

from meeting_assistant.services.tools.base import RetryableToolError
from meeting_assistant.services.tools.http import request_json


class StubJiraToolProvider:
    def execute(self, payload: dict[str, str], *, idempotency_key: str | None = None) -> dict[str, object]:
        if payload.get("simulate_retryable_failure") == "true":
            raise RetryableToolError("Simulated transient Jira delivery failure.")
        return {
            "provider": "stub",
            "delivery_status": "created",
            "issue_key": f"STUB-{(idempotency_key or 'local')[:6]}",
            "provider_message_id": f"stub-jira-{(idempotency_key or 'local')[:12]}",
            "idempotency_key": idempotency_key,
        }


class JiraRestToolProvider:
    def __init__(
        self,
        *,
        base_url: str,
        user_email: str,
        api_token: str,
        project_key: str,
        default_issue_type: str,
        http_client: httpx.Client,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_email = user_email
        self.api_token = api_token
        self.project_key = project_key
        self.default_issue_type = default_issue_type
        self.http_client = http_client

    def execute(self, payload: dict[str, str], *, idempotency_key: str | None = None) -> dict[str, object]:
        if payload.get("simulate_retryable_failure") == "true":
            raise RetryableToolError("Simulated transient Jira delivery failure.")

        summary = payload.get("issue_summary") or payload.get("title") or payload.get("subject", "Meeting follow-up")
        description = payload.get("issue_description") or payload.get("body") or payload.get("details", "")
        issue_type = payload.get("issue_type") or self.default_issue_type

        request_body = {
            "fields": {
                "project": {"key": self.project_key},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description}],
                        }
                    ],
                },
                "issuetype": {"name": issue_type},
                "labels": [f"idempotency-{idempotency_key[:24]}" if idempotency_key else "meeting-assistant"],
            }
        }

        response_payload = request_json(
            self.http_client,
            "POST",
            f"{self.base_url}/rest/api/3/issue",
            provider="jira",
            auth=(self.user_email, self.api_token),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Atlassian-Token": "no-check",
            },
            json=request_body,
        )

        issue_key = str(response_payload.get("key", ""))
        issue_id = str(response_payload.get("id", ""))
        return {
            "provider": "jira",
            "delivery_status": "created",
            "issue_key": issue_key,
            "issue_id": issue_id,
            "provider_message_id": issue_id or issue_key,
            "idempotency_key": idempotency_key,
        }
