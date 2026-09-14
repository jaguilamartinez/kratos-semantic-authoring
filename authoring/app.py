import os
from pathlib import Path

from agents.exceptions import AgentsException
from fastapi import FastAPI, HTTPException, status
from openai import OpenAIError
from pydantic import Field

from authoring.agent import case_change_tool_spec, edit_case
from authoring.case import CaseChanges, StrictModel
from authoring.store import CaseStore, ChangeResult, RevisionConflict


ROOT = Path(__file__).resolve().parents[1]
BASE_CASE_PATH = Path(
    os.environ.get("KSA_BASE_CASE_PATH", Path(__file__).with_name("base_case.json"))
)
TEMPLATE_DIR = Path(
    os.environ.get("KSA_TEMPLATE_DIR", ROOT / "cases" / "test_model_3d.gid")
)
WORKSPACE_DIR = Path(os.environ.get("KSA_WORKSPACE_DIR", ROOT / "workspace"))
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")

store = CaseStore(BASE_CASE_PATH, TEMPLATE_DIR, WORKSPACE_DIR)
app = FastAPI(title="KSA Authoring API", version="0.2.0")


class ApplyChangesRequest(CaseChanges):
    expected_revision: int = Field(ge=0)


class EditRequest(StrictModel):
    prompt: str = Field(min_length=1, max_length=4000)
    expected_revision: int = Field(ge=0)


def serialize_result(result: ChangeResult) -> dict[str, object]:
    return {
        "case": result.snapshot.case,
        "bundle_id": result.snapshot.bundle_id,
        "changes": result.changes,
        "applied": bool(result.changes),
    }


def conflict_response(error: RevisionConflict) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        {
            "message": str(error),
            "expected_revision": error.expected,
            "current_revision": error.actual,
        },
    )


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "llm_configured": bool(os.environ.get("OPENAI_API_KEY")),
        "model": OPENAI_MODEL,
    }


@app.get("/case")
def get_case() -> dict[str, object]:
    snapshot = store.read()
    return {"case": snapshot.case, "bundle_id": snapshot.bundle_id}


@app.get("/tools")
def get_tools() -> dict[str, object]:
    return {"tools": [case_change_tool_spec()]}


@app.post("/tools/apply-case-changes")
def apply_changes(request: ApplyChangesRequest) -> dict[str, object]:
    try:
        return serialize_result(store.apply(request.expected_revision, request))
    except RevisionConflict as error:
        raise conflict_response(error) from error


@app.post("/edits")
async def create_edit(request: EditRequest) -> dict[str, object]:
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "OPENAI_API_KEY is not configured",
        )

    try:
        current = store.read_revision(request.expected_revision)
        edit = await edit_case(request.prompt, current.case, OPENAI_MODEL)
        result = store.publish(request.expected_revision, edit.draft)
    except RevisionConflict as error:
        raise conflict_response(error) from error
    except (AgentsException, OpenAIError) as error:
        detail = f"LLM request failed ({type(error).__name__})"
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail) from error

    response = serialize_result(result)
    response.update(
        {
            "message": edit.message,
            "model": OPENAI_MODEL,
            "tool_calls": edit.tool_calls,
        }
    )
    return response
