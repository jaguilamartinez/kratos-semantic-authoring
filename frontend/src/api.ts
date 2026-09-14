export type ScalarValues = Record<string, number>;

export interface Material {
  variables: ScalarValues;
}

export interface Process {
  model_part_name: string | null;
  process_name: string;
  variable_name: string | null;
  parameters: ScalarValues;
}

export interface CanonicalCase {
  schema_version: string;
  problem_name: string;
  revision: number;
  unit_system: string;
  materials: Record<string, Material>;
  processes: Record<string, Process>;
}

export interface FieldChange {
  field: string;
  before: number;
  after: number;
}

export interface CaseSnapshot {
  case: CanonicalCase;
  bundle_id: string;
}

export interface EditResponse extends CaseSnapshot {
  applied: boolean;
  changes: FieldChange[];
  message: string;
}

export interface RunSummary {
  run_id: string;
  status: string;
  case: string;
  analysis_stage: string;
  case_revision: number | null;
  kratos_version: string;
  input_sha256: Record<string, string>;
  outputs: string[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function responseMessage(body: unknown, status: number): string {
  if (typeof body === "string" && body.trim() && !body.trim().startsWith("<")) {
    return body;
  }
  if (body && typeof body === "object" && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      const message = detail.message;
      if (typeof message === "string") return message;
    }
  }
  return `Request failed (${status})`;
}

async function request<T>(
  basePath: string,
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`${basePath}${path}`, options);
  const text = await response.text();
  let body: unknown = text;

  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      // Proxy errors may be plain text or HTML.
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, responseMessage(body, response.status));
  }

  return body as T;
}

export function getCase(): Promise<CaseSnapshot> {
  return request<CaseSnapshot>("/api", "/case");
}

export function editCase(
  prompt: string,
  expectedRevision: number,
): Promise<EditResponse> {
  return request<EditResponse>("/api", "/edits", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, expected_revision: expectedRevision }),
  });
}

export function runRevision(revision: number): Promise<RunSummary> {
  return request<RunSummary>("/worker-api", "/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ revision }),
  });
}
