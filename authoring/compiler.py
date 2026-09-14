import hashlib
import json
import shutil
from pathlib import Path

from authoring.case import Case, LoadTarget, Region


INPUT_FILES = (
    "ProjectParameters.json",
    "StructuralMaterials.json",
    "test_model_3d.mdpa",
)

LOAD_VARIABLES = {
    LoadTarget.POINT_1: "POINT_LOAD",
    LoadTarget.POINT_2: "POINT_LOAD",
    LoadTarget.RIGHT_END: "SURFACE_LOAD",
    LoadTarget.TOP_1: "SURFACE_LOAD",
    LoadTarget.TOP_2: "SURFACE_LOAD",
    LoadTarget.TOP_3: "SURFACE_LOAD",
    LoadTarget.TOP_4: "SURFACE_LOAD",
    LoadTarget.TOP_5: "SURFACE_LOAD",
}


class TemplateError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise TemplateError(f"Cannot read template file {path.name}") from error


def write_json(path: Path, value: object) -> None:
    text = json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    )
    path.write_text(text + "\n")


def index_by_name(
    items: list[dict[str, object]],
    name: str,
) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    for item in items:
        try:
            key = str(item[name])
        except (KeyError, TypeError) as error:
            raise TemplateError(f"Template entry is missing {name}") from error
        if key in indexed:
            raise TemplateError(f"Duplicate template entry: {key}")
        indexed[key] = item
    return indexed


def material_entries(materials: dict[str, object]) -> dict[Region, dict[str, object]]:
    try:
        properties = materials["properties"]
        indexed = index_by_name(properties, "model_part_name")
    except (KeyError, TypeError) as error:
        raise TemplateError("Invalid StructuralMaterials.json structure") from error

    expected = {"Structure", *(f"Structure.{region.value}" for region in Region)}
    if set(indexed) != expected:
        raise TemplateError("Unexpected material model parts in template")

    result: dict[Region, dict[str, object]] = {}
    for region in Region:
        entry = indexed[f"Structure.{region.value}"]
        try:
            law = entry["Material"]["constitutive_law"]["name"]
        except (KeyError, TypeError) as error:
            raise TemplateError(f"Invalid material entry for {region.value}") from error
        if law != "LinearElastic3DLaw":
            raise TemplateError(f"Unexpected material law for {region.value}")
        result[region] = entry
    return result


def load_entries(parameters: dict[str, object]) -> dict[LoadTarget, dict[str, object]]:
    try:
        raw_loads = parameters["processes"]["loads_process_list"]
        items = [load["Parameters"] for load in raw_loads]
        indexed = index_by_name(items, "model_part_name")
    except (KeyError, TypeError) as error:
        raise TemplateError("Invalid load process structure") from error

    expected = {f"Structure.{target.value}" for target in LoadTarget}
    if set(indexed) != expected:
        raise TemplateError("Unexpected load model parts in template")

    result: dict[LoadTarget, dict[str, object]] = {}
    for target, variable in LOAD_VARIABLES.items():
        entry = indexed[f"Structure.{target.value}"]
        if entry.get("variable_name") != variable:
            raise TemplateError(f"Unexpected load type for {target.value}")
        if entry.get("direction") != [0.0, 0.0, -1]:
            raise TemplateError(f"Unexpected load direction for {target.value}")
        result[target] = entry
    return result


def compile_case(case: Case, template_dir: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"Bundle already exists: {destination}")

    for name in INPUT_FILES:
        if not (template_dir / name).is_file():
            raise TemplateError(f"Missing template file: {name}")

    parameters = read_json(template_dir / "ProjectParameters.json")
    materials = read_json(template_dir / "StructuralMaterials.json")

    for region, entry in material_entries(materials).items():
        entry["Material"]["Variables"]["YOUNG_MODULUS"] = (
            case.materials[region].young_modulus
        )
    for target, entry in load_entries(parameters).items():
        entry["modulus"] = case.loads[target].magnitude

    destination.mkdir(parents=True)
    try:
        write_json(destination / "case.json", case.model_dump(mode="json"))
        write_json(destination / "ProjectParameters.json", parameters)
        write_json(destination / "StructuralMaterials.json", materials)
        shutil.copyfile(
            template_dir / "test_model_3d.mdpa",
            destination / "test_model_3d.mdpa",
        )

        generated_files = ("case.json", *INPUT_FILES)
        manifest = {
            "schema_version": "ksa.bundle/0.1",
            "case_revision": case.revision,
            "files": {
                name: {"sha256": sha256(destination / name)}
                for name in generated_files
            },
        }
        write_json(destination / "manifest.json", manifest)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
