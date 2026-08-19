import type {
  ApiConfig,
  AuthConfigResponse,
  LoginResponse,
  SessionResponse,
  ApprovalRequestResponse,
  ApprovalResolutionResponse,
  BatchJobAcceptedResponse,
  BatchMeetingResponse,
  ConnectIntegrationResponse,
  IntegrationListResponse,
  IntegrationOptionsResponse,
  IntegrationSummary,
  PaginatedChunkSearchResponse,
  PaginatedDecisionsResponse,
  PaginatedSearchMeetingsResponse,
  QueryResponse,
  WorkflowStatusResponse,
} from "./types";

export class ApiClientError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
  }
}

function buildHeaders(config: ApiConfig, extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  if (config.accessToken) {
    headers.set("Authorization", `Bearer ${config.accessToken}`);
  }
  return headers;
}

async function parseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
    if (body.detail) {
      return JSON.stringify(body.detail);
    }
  } catch {
    // ignore parse failures
  }
  return response.statusText || "Request failed";
}

async function request<T>(config: ApiConfig, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${config.baseUrl.replace(/\/$/, "")}${path}`, {
    ...init,
    headers: buildHeaders(config, init?.headers),
  });

  if (!response.ok) {
    throw new ApiClientError(await parseError(response), response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function submitBatchMeeting(
  config: ApiConfig,
  payload: {
    title: string;
    transcript_text: string;
  },
): Promise<BatchMeetingResponse | BatchJobAcceptedResponse> {
  return request(config, "/api/v1/meetings/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_external_id: config.userExternalId,
      user_email: config.userEmail,
      title: payload.title,
      transcript_text: payload.transcript_text,
    }),
  });
}

export async function uploadBatchMeeting(
  config: ApiConfig,
  payload: {
    title: string;
    audio: File;
  },
): Promise<BatchMeetingResponse | BatchJobAcceptedResponse> {
  const form = new FormData();
  form.append("user_external_id", config.userExternalId);
  form.append("user_email", config.userEmail);
  form.append("title", payload.title);
  form.append("audio", payload.audio);

  return request(config, "/api/v1/meetings/batch/upload", {
    method: "POST",
    body: form,
  });
}

export async function getWorkflowStatus(
  config: ApiConfig,
  workflowRunId: number,
): Promise<WorkflowStatusResponse> {
  return request(config, `/api/v1/workflows/${workflowRunId}`);
}

export async function listWorkflowApprovals(
  config: ApiConfig,
  workflowRunId: number,
): Promise<ApprovalRequestResponse[]> {
  return request(config, `/api/v1/workflows/${workflowRunId}/approvals`);
}

export async function approveRequest(
  config: ApiConfig,
  approvalRequestId: number,
  resolvedBy?: string,
): Promise<ApprovalResolutionResponse> {
  return request(config, `/api/v1/approvals/${approvalRequestId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(resolvedBy ? { resolved_by: resolvedBy } : {}),
  });
}

export async function rejectRequest(
  config: ApiConfig,
  approvalRequestId: number,
  resolvedBy?: string,
): Promise<ApprovalResolutionResponse> {
  return request(config, `/api/v1/approvals/${approvalRequestId}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(resolvedBy ? { resolved_by: resolvedBy } : {}),
  });
}

export async function searchMeetings(
  config: ApiConfig,
  query: string,
  limit = 10,
  cursor?: string,
): Promise<PaginatedSearchMeetingsResponse> {
  const params = new URLSearchParams({
    user_external_id: config.userExternalId,
    query,
    limit: String(limit),
  });
  if (cursor) {
    params.set("cursor", cursor);
  }
  return request(config, `/api/v1/meetings/search?${params.toString()}`);
}

export async function searchDecisions(
  config: ApiConfig,
  topic: string,
  limit = 10,
  cursor?: string,
): Promise<PaginatedDecisionsResponse> {
  const params = new URLSearchParams({
    user_external_id: config.userExternalId,
    topic,
    limit: String(limit),
  });
  if (cursor) {
    params.set("cursor", cursor);
  }
  return request(config, `/api/v1/decisions?${params.toString()}`);
}

export async function searchChunks(
  config: ApiConfig,
  query: string,
  limit = 10,
  cursor?: string,
): Promise<PaginatedChunkSearchResponse> {
  const params = new URLSearchParams({
    user_external_id: config.userExternalId,
    query,
    limit: String(limit),
  });
  if (cursor) {
    params.set("cursor", cursor);
  }
  return request(config, `/api/v1/meetings/chunks/search?${params.toString()}`);
}

export async function answerQuery(config: ApiConfig, question: string): Promise<QueryResponse> {
  return request(config, "/api/v1/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_external_id: config.userExternalId,
      question,
    }),
  });
}

export async function checkHealth(config: ApiConfig): Promise<{ status: string }> {
  return request(config, "/health");
}

export async function getAuthConfig(baseUrl: string): Promise<AuthConfigResponse> {
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/api/v1/auth/config`);
  if (!response.ok) {
    throw new ApiClientError(await parseError(response), response.status);
  }
  return (await response.json()) as AuthConfigResponse;
}

export async function login(
  baseUrl: string,
  payload: {
    api_key?: string;
    user_external_id?: string;
    user_email?: string;
  },
): Promise<LoginResponse> {
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new ApiClientError(await parseError(response), response.status);
  }
  return (await response.json()) as LoginResponse;
}

export async function registerAccount(
  baseUrl: string,
  payload: {
    email: string;
    password: string;
    display_name?: string;
  },
): Promise<LoginResponse> {
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new ApiClientError(await parseError(response), response.status);
  }
  return (await response.json()) as LoginResponse;
}

export async function loginEmail(
  baseUrl: string,
  payload: {
    email: string;
    password: string;
  },
): Promise<LoginResponse> {
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/api/v1/auth/login/email`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new ApiClientError(await parseError(response), response.status);
  }
  return (await response.json()) as LoginResponse;
}

export async function getGoogleConnectUrl(baseUrl: string, frontendRedirect: string): Promise<string> {
  const params = new URLSearchParams({ frontend_redirect: frontendRedirect });
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/api/v1/auth/google/connect?${params.toString()}`);
  if (!response.ok) {
    throw new ApiClientError(await parseError(response), response.status);
  }
  const payload = (await response.json()) as { authorize_url: string };
  return payload.authorize_url;
}

export async function getSession(config: ApiConfig): Promise<SessionResponse> {
  return request(config, "/api/v1/auth/me");
}

function userQuery(config: ApiConfig, extra?: Record<string, string>): string {
  const params = new URLSearchParams({ user_external_id: config.userExternalId });
  if (extra) {
    for (const [key, value] of Object.entries(extra)) {
      params.set(key, value);
    }
  }
  return params.toString();
}

export async function listIntegrations(config: ApiConfig): Promise<IntegrationListResponse> {
  return request(config, `/api/v1/integrations?${userQuery(config)}`);
}

export async function connectIntegration(
  config: ApiConfig,
  provider: string,
  frontendRedirect?: string,
): Promise<ConnectIntegrationResponse> {
  const params = userQuery(
    config,
    frontendRedirect ? { frontend_redirect: frontendRedirect } : undefined,
  );
  return request(config, `/api/v1/integrations/${provider}/connect?${params}`);
}

export async function disconnectIntegration(
  config: ApiConfig,
  provider: string,
  providerAccountId = "",
): Promise<IntegrationSummary> {
  const params = userQuery(config, { provider_account_id: providerAccountId });
  return request(config, `/api/v1/integrations/${provider}?${params}`, { method: "DELETE" });
}

export async function updateIntegrationSettings(
  config: ApiConfig,
  provider: string,
  settingsJson: Record<string, unknown>,
  providerAccountId = "",
): Promise<IntegrationSummary> {
  const params = userQuery(config, { provider_account_id: providerAccountId });
  return request(config, `/api/v1/integrations/${provider}/settings?${params}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settings_json: settingsJson }),
  });
}

export async function listIntegrationOptions(
  config: ApiConfig,
  provider: string,
  providerAccountId = "",
): Promise<IntegrationOptionsResponse> {
  const params = userQuery(config, { provider_account_id: providerAccountId });
  return request(config, `/api/v1/integrations/${provider}/options?${params}`);
}
