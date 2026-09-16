import asyncio
import json
import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import UUID

from agents.exceptions import AgentsException
from fastapi import FastAPI, HTTPException, Request as APIRequest
from fastapi.responses import JSONResponse
from openai import OpenAIError
from pydantic import Field

from authoring.agent import edit_case, tool_specs
from authoring.case import StrictModel, diff_cases
from authoring.catalog import discover_capabilities
from authoring.commands import CaseCommand, ValidationIssue, validate_case
from authoring.compiler import render_case
from authoring.store import CaseStore, DraftConflict, RevisionConflict


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = Path(os.environ.get("KSA_TEMPLATE_DIR", "/case"))
WORKSPACE_DIR = Path(os.environ.get("KSA_WORKSPACE_DIR", ROOT / "workspace"))
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")
WORKER_URL = os.environ.get("KSA_WORKER_URL", "")

store = CaseStore(TEMPLATE_DIR, WORKSPACE_DIR)
app = FastAPI(title="KSA Authoring API", version="0.3.0")


class DraftRequest(StrictModel):
    expected_revision: int = Field(ge=0)
    draft_id: UUID | None = None
    content_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ProposeRequest(DraftRequest):
    commands: list[CaseCommand] = Field(min_length=1)


class EditRequest(DraftRequest):
    prompt: str = Field(min_length=1, max_length=4000)


class DraftVersion(StrictModel):
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


@app.exception_handler(RevisionConflict)
async def revision_conflict(_: APIRequest, error: RevisionConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": {
        "message": str(error), "expected_revision": error.expected,
        "current_revision": error.actual,
    }})


@app.exception_handler(DraftConflict)
async def draft_conflict(_: APIRequest, error: DraftConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.exception_handler(FileNotFoundError)
async def not_found(_: APIRequest, error: FileNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Case, draft or input file not found"})


@app.exception_handler(ValueError)
async def invalid_request(_: APIRequest, error: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(error)})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_configured": bool(os.environ.get("OPENAI_API_KEY")),
            "model": OPENAI_MODEL, "native_validation": bool(WORKER_URL)}


@app.get("/case")
def get_case():
    return store.read()


@app.get("/case/coverage")
def get_coverage():
    return validate_case(store.read().case)


@app.get("/case/native")
def get_native():
    parameters, materials = render_case(store.read().case)
    return {"ProjectParameters": parameters, "Materials": materials}


@app.get("/capabilities")
def get_capabilities():
    return discover_capabilities()


@app.get("/tools")
def get_tools():
    return {"tools": tool_specs()}


@app.get("/revisions")
def get_revisions():
    return {"revisions": store.list_revisions()}


@app.get("/revisions/{revision}")
def get_revision(revision: int):
    if revision < 0:
        raise HTTPException(404, "Revision not found")
    return store.read_revision(revision)


@app.get("/drafts")
def get_drafts():
    return {"drafts": store.list_drafts()}


@app.get("/drafts/{draft_id}")
def get_draft(draft_id: UUID):
    return store.read_draft(str(draft_id))


@app.get("/drafts/{draft_id}/coverage")
def get_draft_coverage(draft_id: UUID):
    return validate_case(store.read_draft(str(draft_id)).case)


@app.get("/drafts/{draft_id}/native")
def get_draft_native(draft_id: UUID):
    parameters, materials = render_case(store.read_draft(str(draft_id)).case)
    return {"ProjectParameters": parameters, "Materials": materials}


@app.post("/drafts")
@app.post("/tools/propose-case-changes")
def propose_changes(request: ProposeRequest):
    return store.propose(request.expected_revision, request.commands,
                         str(request.draft_id) if request.draft_id else None,
                         request.content_hash)


def native_check(digest: str) -> dict:
    request = Request(f"{WORKER_URL}/checks", method="POST",
                      data=json.dumps({"bundle_hash": digest}).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=120) as response:
        return json.load(response)


@app.post("/drafts/{draft_id}/validate")
async def validate(draft_id: UUID, request: DraftVersion):
    draft = store.validate_draft(str(draft_id), request.content_hash)
    report = draft.validation
    if report.valid and report.execution_supported and WORKER_URL:
        try:
            result = await asyncio.to_thread(native_check, draft.content_hash)
            report.native_check = "passed" if result["valid"] else "failed"
            if not result["valid"]:
                report.valid = False
                report.issues.append(ValidationIssue(
                    level="error", path="native", message=result["message"],
                ))
        except (URLError, TimeoutError) as error:
            raise HTTPException(503, "Kratos validation is unavailable; retry validation") from error
        draft = store.record_validation(str(draft_id), request.content_hash, report)
    return draft


@app.post("/drafts/{draft_id}/publish")
def publish(draft_id: UUID, request: DraftVersion):
    result = store.publish_draft(str(draft_id), request.content_hash, require_native=bool(WORKER_URL))
    return {"case": result.snapshot.case, "bundle_id": result.snapshot.bundle_id,
            "changes": result.changes, "applied": bool(result.changes)}


@app.post("/edits")
async def create_edit(request: EditRequest):
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(503, "OPENAI_API_KEY is not configured")
    draft_id = str(request.draft_id) if request.draft_id else None
    case = store.editing_case(request.expected_revision, draft_id)
    if draft_id and store.read_draft(draft_id).content_hash != request.content_hash:
        raise DraftConflict("The draft changed; reload it before continuing")
    try:
        edit = await edit_case(request.prompt, case, OPENAI_MODEL)
    except (AgentsException, OpenAIError) as error:
        raise HTTPException(502, f"LLM request failed ({type(error).__name__})") from error
    draft = None
    if diff_cases(case, edit.draft):
        draft = store.stage(request.expected_revision, edit.draft, draft_id, request.content_hash)
    elif draft_id:
        draft = store.read_draft(draft_id)
    return {"draft": draft, "message": edit.message, "model": OPENAI_MODEL,
            "tool_calls": edit.tool_calls}
