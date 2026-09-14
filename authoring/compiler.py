import hashlib
import json
import shutil
from pathlib import Path

from authoring.case import Case, Material, Process


PROJECT_PARAMETERS = "ProjectParameters.json"


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


def materials_filename(parameters: dict[str, object]) -> str:
    return str(
        parameters["solver_settings"]["material_import_settings"][
            "materials_filename"
        ]
    )


def mesh_filenames(parameters: dict[str, object]) -> tuple[str, ...]:
    names: list[str] = []
    for modeler in parameters["modelers"]:
        if not str(modeler["name"]).endswith("ImportMDPAModeler"):
            continue
        name = str(modeler["parameters"]["input_filename"])
        names.append(name if name.endswith(".mdpa") else f"{name}.mdpa")
    return tuple(names)


def input_files(parameters: dict[str, object]) -> tuple[str, ...]:
    return (
        PROJECT_PARAMETERS,
        materials_filename(parameters),
        *mesh_filenames(parameters),
    )


def scalar_values(values: object) -> dict[str, float]:
    if not isinstance(values, dict):
        return {}
    return {
        str(name): float(value)
        for name, value in values.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def process_id(process_list: str, position: int) -> str:
    return f"{process_list}:{position}"


def load_case(template_dir: Path) -> Case:
    parameters = read_json(template_dir / PROJECT_PARAMETERS)
    materials = read_json(template_dir / materials_filename(parameters))

    canonical_materials: dict[str, Material] = {}
    for entry in materials["properties"]:
        values = scalar_values(entry["Material"]["Variables"])
        if values:
            canonical_materials[str(entry["model_part_name"])] = Material(
                variables=values
            )

    canonical_processes: dict[str, Process] = {}
    for list_name, items in parameters["processes"].items():
        for position, item in enumerate(items):
            process_parameters = item["Parameters"]
            values = scalar_values(process_parameters)
            if values:
                canonical_processes[process_id(list_name, position)] = Process(
                    model_part_name=process_parameters.get("model_part_name"),
                    process_name=str(item["process_name"]),
                    variable_name=process_parameters.get("variable_name"),
                    parameters=values,
                )

    return Case(
        schema_version="ksa.structural-case/0.2",
        problem_name=str(parameters["problem_data"]["problem_name"]),
        revision=0,
        unit_system="unconfirmed",
        materials=canonical_materials,
        processes=canonical_processes,
    )


def index_materials(materials: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        str(entry["model_part_name"]): entry
        for entry in materials["properties"]
    }


def compile_case(case: Case, template_dir: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"Bundle already exists: {destination}")

    parameters = read_json(template_dir / PROJECT_PARAMETERS)
    material_file = materials_filename(parameters)
    materials = read_json(template_dir / material_file)
    files = input_files(parameters)

    for name in files:
        if not (template_dir / name).is_file():
            raise TemplateError(f"Missing template file: {name}")

    material_entries = index_materials(materials)
    for model_part_name, material in case.materials.items():
        variables = material_entries[model_part_name]["Material"]["Variables"]
        variables.update(material.variables)

    for identifier, process in case.processes.items():
        list_name, position = identifier.rsplit(":", 1)
        process_parameters = parameters["processes"][list_name][int(position)][
            "Parameters"
        ]
        process_parameters.update(process.parameters)

    destination.mkdir(parents=True)
    try:
        write_json(destination / "case.json", case.model_dump(mode="json"))
        write_json(destination / PROJECT_PARAMETERS, parameters)
        write_json(destination / material_file, materials)
        for name in files[2:]:
            shutil.copyfile(template_dir / name, destination / name)

        generated_files = ("case.json", *files)
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
