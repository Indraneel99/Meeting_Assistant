export interface ApiConfig {
  baseUrl: string;
  accessToken: string;
  userExternalId: string;
  userEmail: string;
}

export interface AuthConfigResponse {
  auth_enabled: boolean;
  login_allow_dev: boolean;
  password_login_enabled: boolean;
  google_login_enabled: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user_external_id: string;
  user_email: string;
}

export interface SessionResponse {
  user_external_id: string;
  user_email: string | null;
  auth_type: string;
}

export interface BatchMeetingResponse {
  meeting_id: number;
  workflow_run_id: number;
  status: string;
  summary: string;
  tasks_created: number;
  decisions_logged: number;
  tool_calls_recorded: number;
  iterations_used: number;
  tool_executions: ToolExecutionRecord[];
}

export interface BatchJobAcceptedResponse {
  job_id: number;
  workflow_run_id: number;
  meeting_id: number;
  status: string;
}

export interface ToolExecutionRecord {
  tool_name: string;
  status: string;
  attempts: number;
  idempotency_key: string;
  result: Record<string, unknown> | null;
}

export interface WorkflowStatusResponse {
  workflow_run_id: number;
  meeting_id: number;
  status: string;
  failure_reason: string | null;
  iteration_count: number;
  summary: string | null;
  tasks_created: number | null;
  decisions_logged: number | null;
  tool_calls_recorded: number | null;
  tool_executions: ToolExecutionRecord[];
}

export interface ApprovalRequestResponse {
  approval_request_id: number;
  workflow_run_id: number;
  tool_execution_id: number;
  tool_name: string;
  payload: Record<string, unknown>;
  status: string;
  requested_at: string;
  resolved_by: string | null;
  resolved_at: string | null;
}

export interface ApprovalResolutionResponse {
  approval_request_id: number;
  workflow_run_id: number;
  approval_status: string;
  tool_status: string;
  tool_result: Record<string, unknown>;
  workflow_status: string;
  summary: string;
  tool_executions: Record<string, unknown>[];
  iterations_used: number;
}

export interface MeetingSearchResult {
  meeting_id: number;
  title: string;
  summary: string;
  score: number;
}

export interface ChunkSearchResult {
  chunk_id: number;
  meeting_id: number;
  meeting_title: string;
  chunk_index: number;
  text: string;
  score: number;
}

export interface PaginatedChunkSearchResponse {
  results: ChunkSearchResult[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface MeetingTask {
  assignee: string;
  action: string;
  status: string;
}

export interface PaginatedSearchMeetingsResponse {
  results: MeetingSearchResult[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface DecisionItem {
  decision_id: number;
  meeting_id: number;
  topic: string;
  decision_text: string;
  score: number;
}

export interface PaginatedDecisionsResponse {
  results: DecisionItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface QueryCitation {
  meeting_id: number;
  meeting_title: string;
  source_type: string;
  excerpt: string;
}

export interface QueryResponse {
  answer: string;
  citations: QueryCitation[];
  meetings: MeetingSearchResult[];
  chunks: ChunkSearchResult[];
  tasks: MeetingTask[];
  decisions: DecisionItem[];
}

export interface ApiError {
  detail: string | Record<string, unknown>;
}

export interface IntegrationSummary {
  provider: string;
  status: string;
  provider_account_id: string;
  scopes: string | null;
  settings_json: Record<string, unknown>;
  connected_at: string;
  updated_at: string;
  expires_at: string | null;
}

export interface IntegrationListResponse {
  integrations: IntegrationSummary[];
}

export interface ConnectIntegrationResponse {
  authorize_url: string | null;
  state: string | null;
  status: string | null;
}

export interface IntegrationOption {
  id: string;
  label: string;
  metadata: Record<string, unknown>;
}

export interface IntegrationOptionsResponse {
  options: IntegrationOption[];
}
