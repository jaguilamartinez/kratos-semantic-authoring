export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type Settings = Record<string, JsonValue>;

export interface Material {
  id: string;
  label: string;
  settings: {
    properties: Settings | JsonValue[];
    law: Settings | null;
    tables: Settings | JsonValue[] | null;
  };
  native: Settings;
}

export interface Component {
  id: string;
  label: string;
  capability: string | null;
  settings: Settings;
  native: Settings;
}

export interface CanonicalCase {
  schema_version: string;
  problem_name: string;
  revision: number;
  unit_system: string;
  target: Settings;
  model: {
    settings: Settings;
    regions: Record<string, { name: string; parent: string | null; mesh_ids: string[] }>;
    meshes: Record<string, { filename: string; sha256: string }>;
  };
  analysis: Settings;
  numerics: Settings;
  execution: Settings;
  materials: Record<string, Material>;
  material_assignments: Record<string, {
    id: string;
    material_id: string;
    region: string;
    properties_id: number;
    native: Settings;
  }>;
  boundary_conditions: Record<string, Component>;
  loads: Record<string, Component>;
  initial_conditions: Record<string, Component>;
  auxiliary_processes: Record<string, Component>;
  outputs: Record<string, Component>;
  preparation: Record<string, Component>;
  preparation_order: string[];
  material_order: string[];
  process_groups: Record<string, string[]>;
  output_groups: Record<string, string[]>;
  extensions: Settings;
}

export interface FieldChange {
  field: string;
  before?: JsonValue;
  after?: JsonValue;
  operation?: "add" | "remove" | "replace";
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface DraftChangeSet {
  sequence: number;
  changes: FieldChange[];
  native_changes: FieldChange[];
}

export interface CaseSnapshot {
  case: CanonicalCase;
  bundle_id: string;
}

export interface ValidationReport {
  valid: boolean;
  issues: Array<{ level: "error" | "warning"; path: string; message: string }>;
  coverage: Array<{ path: string; capability: string | null; status: "semantic" | "native-only" }>;
  execution_supported: boolean;
  native_check?: "not_run" | "passed" | "failed";
}

export interface Draft {
  id: string;
  base_revision: number;
  content_hash: string;
  validated_hash: string | null;
  case: CanonicalCase;
  messages: ChatMessage[];
  change_log: DraftChangeSet[];
  changes: FieldChange[];
  native_changes: FieldChange[];
  validation: ValidationReport | null;
  status: "editing" | "published";
  published_revision?: number | null;
}

export interface EditResponse {
  draft: Draft | null;
  message: string;
  model: string;
  tool_calls: unknown[];
}

export interface Revision {
  revision: number;
  bundle_id: string;
  problem_name: string;
  schema_version: string;
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
  draftId?: string,
  contentHash?: string,
): Promise<EditResponse> {
  return request<EditResponse>("/api", "/edits", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt, expected_revision: expectedRevision, draft_id: draftId, content_hash: contentHash,
    }),
  });
}

export function getDrafts(): Promise<{ drafts: Draft[] }> {
  return request("/api", "/drafts");
}

export function getDraft(id: string): Promise<Draft> {
  return request("/api", `/drafts/${encodeURIComponent(id)}`);
}

export function getCoverage(draftId?: string): Promise<ValidationReport> {
  const path = draftId ? `/drafts/${encodeURIComponent(draftId)}/coverage` : "/case/coverage";
  return request("/api", path);
}

export function validateDraft(draft: Draft): Promise<Draft> {
  return request("/api", `/drafts/${encodeURIComponent(draft.id)}/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content_hash: draft.content_hash }),
  });
}

export function publishDraft(draft: Draft): Promise<CaseSnapshot & { applied: boolean; changes: FieldChange[] }> {
  return request("/api", `/drafts/${encodeURIComponent(draft.id)}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content_hash: draft.content_hash }),
  });
}

export function getRevisions(): Promise<{ revisions: Revision[] }> {
  return request("/api", "/revisions");
}

export function getRevision(revision: number): Promise<CaseSnapshot> {
  return request("/api", `/revisions/${revision}`);
}

export function runRevision(revision: number): Promise<RunSummary> {
  return request<RunSummary>("/worker-api", "/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ revision }),
  });
}
