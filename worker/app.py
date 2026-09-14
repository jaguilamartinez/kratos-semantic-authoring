import asyncio
import json
import os
import subprocess
import sys
from importlib.metadata import version as package_version
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from run_case import PROJECT_PARAMETERS, input_files


CASE_DIR = Path(os.environ.get("KSA_CASE_DIR", "/case"))
OUTPUT_DIR = Path(os.environ.get("KSA_OUTPUT_DIR", "/artifacts"))
REVISION_DIR = Path(os.environ.get("KSA_REVISION_DIR", "/workspace/revisions"))
RUNNER = Path(__file__).with_name("run_case.py")

app = FastAPI(title="KSA Kratos Worker", version="0.1.0")
run_lock = asyncio.Lock()


class RunRequest(BaseModel):
    revision: int | None = Field(default=None, ge=0)


def load_summary(run_id: UUID) -> dict[str, object]:
    path = OUTPUT_DIR / str(run_id) / "summary.json"
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return json.loads(path.read_text())


@app.get("/health")
def health() -> dict[str, str]:
    parameters = json.loads((CASE_DIR / PROJECT_PARAMETERS).read_text())
    return {
        "status": "ok",
        "kratos_version": package_version("KratosMultiphysics"),
        "case": str(parameters["problem_data"]["problem_name"]),
        "analysis_stage": str(parameters["analysis_stage"]),
    }


@app.get("/runs/{run_id}")
def get_run(run_id: UUID) -> dict[str, object]:
    return {"run_id": str(run_id), **load_summary(run_id)}


def case_dir_for(revision: int | None) -> Path:
    if revision is None:
        return CASE_DIR

    case_dir = REVISION_DIR / f"revision-{revision:06d}"
    parameters_path = case_dir / PROJECT_PARAMETERS
    if not parameters_path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case revision not found")

    parameters = json.loads(parameters_path.read_text())
    required = input_files(parameters)
    if not all((case_dir / name).is_file() for name in required):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case revision not found")
    return case_dir


@app.post("/runs", status_code=status.HTTP_201_CREATED)
async def create_run(request: RunRequest | None = None) -> dict[str, object]:
    if run_lock.locked():
        raise HTTPException(status.HTTP_409_CONFLICT, "A run is already in progress")

    async with run_lock:
        run_id = uuid4()
        revision = request.revision if request else None
        command = [
            sys.executable,
            str(RUNNER),
            "--case-dir",
            str(case_dir_for(revision)),
            "--output-dir",
            str(OUTPUT_DIR),
            "--run-id",
            str(run_id),
        ]
        if revision is not None:
            command.extend(["--case-revision", str(revision)])
        result = await asyncio.to_thread(
            subprocess.run,
            command,
            capture_output=True,
            text=True,
            check=False,
        )

        run_dir = OUTPUT_DIR / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "stdout.log").write_text(result.stdout)
        (run_dir / "stderr.log").write_text(result.stderr)

        if result.returncode:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                {"run_id": str(run_id), "message": "Kratos failed; see stderr.log"},
            )

        return {"run_id": str(run_id), **load_summary(run_id)}
