import argparse
import hashlib
import importlib
import json
import shutil
import tempfile
from contextlib import chdir
from datetime import datetime, timezone
from importlib.metadata import version as package_version
from pathlib import Path

import KratosMultiphysics as Kratos


PROJECT_PARAMETERS = "ProjectParameters.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_files(parameters: dict[str, object]) -> tuple[str, ...]:
    solver = parameters.get("solver_settings", {})
    material_file = solver.get("material_import_settings", {}).get("materials_filename")
    meshes: list[str] = []
    for modeler in parameters.get("modelers", []):
        if not str(modeler.get("name", modeler.get("modeler_name", ""))).endswith("ImportMDPAModeler"):
            continue
        name = str(modeler["parameters"]["input_filename"])
        meshes.append(name if name.endswith(".mdpa") else f"{name}.mdpa")
    settings = solver.get("model_import_settings", {})
    if settings.get("input_type") == "mdpa":
        name = settings["input_filename"]
        meshes.append(name if name.endswith(".mdpa") else f"{name}.mdpa")
    return (PROJECT_PARAMETERS, *((material_file,) if material_file else ()), *dict.fromkeys(meshes))


def copy_inputs(case_dir: Path, workspace: Path, names: tuple[str, ...]) -> None:
    for name in names:
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError(f"Expected a relative input filename: {name}")
        source = case_dir / name
        if not source.is_file():
            raise FileNotFoundError(f"Missing case input: {source}")
        destination = workspace / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def verify_bundle(case_dir: Path) -> None:
    manifest_path = case_dir / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text())
    target = manifest.get("target", {})
    if target.get("kratos_version", package_version("KratosMultiphysics")) != package_version("KratosMultiphysics"):
        raise ValueError("The bundle targets a different Kratos version")
    for name, expected in manifest["files"].items():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Invalid manifest input path")
        if sha256(case_dir / name) != expected["sha256"]:
            raise ValueError(f"Bundle input was modified: {name}")


def check_case(case_dir: Path) -> None:
    """Initialize and check in scratch space, without a solution step or saved outputs."""
    verify_bundle(case_dir)
    raw_parameters = (case_dir / PROJECT_PARAMETERS).read_text()
    configuration = json.loads(raw_parameters)
    with tempfile.TemporaryDirectory(prefix="ksa-check-") as tmp:
        workspace = Path(tmp)
        copy_inputs(case_dir, workspace, input_files(configuration))
        analysis_type = load_analysis_stage(configuration["analysis_stage"])
        with chdir(workspace):
            analysis = analysis_type(Kratos.Model(), Kratos.Parameters(raw_parameters))
            analysis.Initialize()  # Kratos calls solver and process Check here.
            analysis.Finalize()


def load_analysis_stage(module_name: str) -> type:
    class_name = "".join(
        part.title() for part in module_name.rsplit(".", 1)[-1].split("_")
    )
    return getattr(importlib.import_module(module_name), class_name)


def copy_outputs(
    workspace: Path,
    run_dir: Path,
    input_names: tuple[str, ...],
) -> list[str]:
    outputs = [path for path in workspace.iterdir() if path.name not in input_names]
    for source in outputs:
        destination = run_dir / source.name
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    return sorted(path.name for path in outputs)


def run_case(
    case_dir: Path,
    output_dir: Path,
    run_id: str | None = None,
    case_revision: int | None = None,
) -> Path:
    case_dir = case_dir.resolve()
    verify_bundle(case_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_parameters = (case_dir / PROJECT_PARAMETERS).read_text()
    configuration = json.loads(raw_parameters)
    names = input_files(configuration)

    with tempfile.TemporaryDirectory(prefix="ksa-") as tmp:
        workspace = Path(tmp)
        copy_inputs(case_dir, workspace, names)

        parameters = Kratos.Parameters(raw_parameters)
        analysis_stage_name = str(configuration["analysis_stage"])
        analysis_stage = load_analysis_stage(analysis_stage_name)

        with chdir(workspace):
            analysis_stage(Kratos.Model(), parameters).Run()

        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        run_dir = output_dir / run_id
        run_dir.mkdir()
        outputs = copy_outputs(workspace, run_dir, names)

        summary = {
            "status": "succeeded",
            "case": configuration["problem_data"]["problem_name"],
            "analysis_stage": analysis_stage_name,
            "case_revision": case_revision,
            "kratos_version": package_version("KratosMultiphysics"),
            "input_sha256": {
                name: sha256(case_dir / name)
                for name in names
            },
            "outputs": outputs,
        }
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(json.dumps(summary, indent=2))
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Kratos structural case")
    parser.add_argument("--case-dir", type=Path, default=Path("/case"))
    parser.add_argument("--output-dir", type=Path, default=Path("/artifacts"))
    parser.add_argument("--run-id")
    parser.add_argument("--case-revision", type=int)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    if args.check_only:
        check_case(args.case_dir)
        return

    run_dir = run_case(
        args.case_dir,
        args.output_dir,
        args.run_id,
        args.case_revision,
    )
    print(f"Artifacts: {run_dir}")


if __name__ == "__main__":
    main()
