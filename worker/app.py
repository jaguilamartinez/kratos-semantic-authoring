import asyncio
import json
import os
import subprocess
import sys
from importlib.metadata import version as package_version
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, status


CASE_DIR = Path(os.environ.get("KSA_CASE_DIR", "/case"))
OUTPUT_DIR = Path(os.environ.get("KSA_OUTPUT_DIR", "/artifacts"))
RUNNER = Path(__file__).with_name("run_case.py")

app = FastAPI(title="KSA Kratos Worker", version="0.1.0")
run_lock = asyncio.Lock()


def load_summary(run_id: UUID) -> dict[str, object]:
    path = OUTPUT_DIR / str(run_id) / "summary.json"
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return json.loads(path.read_text())


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "kratos_version": package_version("KratosMultiphysics"),
        "case": "test_model_3d",
    }


@app.get("/runs/{run_id}")
def get_run(run_id: UUID) -> dict[str, object]:
    return {"run_id": str(run_id), **load_summary(run_id)}


@app.post("/runs", status_code=status.HTTP_201_CREATED)
async def create_run() -> dict[str, object]:
    if run_lock.locked():
        raise HTTPException(status.HTTP_409_CONFLICT, "A run is already in progress")

    async with run_lock:
        run_id = uuid4()
        command = [
            sys.executable,
            str(RUNNER),
            "--case-dir",
            str(CASE_DIR),
            "--output-dir",
            str(OUTPUT_DIR),
            "--run-id",
            str(run_id),
        ]
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
