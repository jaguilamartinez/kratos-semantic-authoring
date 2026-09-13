import argparse
import hashlib
import json
import math
import shutil
import tempfile
from contextlib import chdir
from datetime import datetime, timezone
from importlib.metadata import version as package_version
from pathlib import Path

import KratosMultiphysics as Kratos
from KratosMultiphysics.StructuralMechanicsApplication.structural_mechanics_analysis import (
    StructuralMechanicsAnalysis,
)


INPUT_FILES = (
    "ProjectParameters.json",
    "StructuralMaterials.json",
    "test_model_3d.mdpa",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_inputs(case_dir: Path, workspace: Path) -> None:
    for name in INPUT_FILES:
        source = case_dir / name
        if not source.is_file():
            raise FileNotFoundError(f"Missing case input: {source}")
        shutil.copy2(source, workspace / name)


def read_vtk_field(lines: list[str], field_name: str) -> list[list[float]]:
    for index, line in enumerate(lines):
        header = line.split()
        if not header or header[0] != field_name:
            continue

        components = int(header[1])
        item_count = int(header[2])
        values: list[float] = []

        for row in lines[index + 1 :]:
            values.extend(float(value) for value in row.split())
            if len(values) >= components * item_count:
                break

        expected = components * item_count
        if len(values) != expected:
            raise ValueError(f"Incomplete VTK field {field_name}: {len(values)}/{expected}")

        return [
            values[offset : offset + components]
            for offset in range(0, expected, components)
        ]

    raise ValueError(f"VTK field not found: {field_name}")


def summarize_vtk(vtk_file: Path) -> dict[str, object]:
    lines = vtk_file.read_text().splitlines()
    displacements = read_vtk_field(lines, "DISPLACEMENT")
    reactions = read_vtk_field(lines, "REACTION")
    stresses = read_vtk_field(lines, "VON_MISES_STRESS")

    displacement_norms = [
        math.sqrt(sum(value * value for value in row))
        for row in displacements
    ]
    max_index, max_norm = max(
        enumerate(displacement_norms),
        key=lambda item: item[1],
    )

    return {
        "node_count": len(displacements),
        "max_displacement": {
            "node_id": max_index + 1,
            "norm": max_norm,
            "vector": displacements[max_index],
        },
        "reaction_sum": [sum(row[axis] for row in reactions) for axis in range(3)],
        "max_von_mises_stress": max(row[0] for row in stresses),
    }


def run_case(case_dir: Path, output_dir: Path, run_id: str | None = None) -> Path:
    case_dir = case_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ksa-") as tmp:
        workspace = Path(tmp)
        copy_inputs(case_dir, workspace)

        raw_parameters = (workspace / "ProjectParameters.json").read_text()
        problem_name = json.loads(raw_parameters)["problem_data"]["problem_name"]
        parameters = Kratos.Parameters(raw_parameters)

        with chdir(workspace):
            StructuralMechanicsAnalysis(Kratos.Model(), parameters).Run()

        vtk_files = sorted((workspace / "vtk_output").glob("*.vtk"))
        if not vtk_files:
            raise RuntimeError("Kratos completed without producing a VTK file")

        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        run_dir = output_dir / run_id
        run_dir.mkdir()

        for output_name in ("gid_output", "vtk_output"):
            source = workspace / output_name
            if source.exists():
                shutil.copytree(source, run_dir / output_name)

        summary = {
            "status": "succeeded",
            "case": problem_name,
            "kratos_version": package_version("KratosMultiphysics"),
            "input_sha256": {
                name: sha256(case_dir / name)
                for name in INPUT_FILES
            },
            "results": summarize_vtk(vtk_files[-1]),
        }
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(json.dumps(summary, indent=2))
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the reference Kratos case")
    parser.add_argument("--case-dir", type=Path, default=Path("/case"))
    parser.add_argument("--output-dir", type=Path, default=Path("/artifacts"))
    parser.add_argument("--run-id")
    args = parser.parse_args()

    run_dir = run_case(args.case_dir, args.output_dir, args.run_id)
    print(f"Artifacts: {run_dir}")


if __name__ == "__main__":
    main()
