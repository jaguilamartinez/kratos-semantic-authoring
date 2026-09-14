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

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options);
  const body = (await response.json()) as {
    detail?: string | { message?: string };
  };

  if (!response.ok) {
    const detail = body.detail;
    const message =
      typeof detail === "string" ? detail : detail?.message || "Request failed";
    throw new ApiError(response.status, message);
  }

  return body as T;
}

export function getCase(): Promise<CaseSnapshot> {
  return request<CaseSnapshot>("/case");
}

export function editCase(
  prompt: string,
  expectedRevision: number,
): Promise<EditResponse> {
  return request<EditResponse>("/edits", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, expected_revision: expectedRevision }),
  });
}
