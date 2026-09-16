import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path

from authoring.case import Case, Component, Material, MaterialAssignment, MeshAsset, Region
from authoring.catalog import CAPABILITIES


PROJECT_PARAMETERS = "ProjectParameters.json"
MODEL_FIELDS = {
    "model_part_name": "root", "domain_size": "dimension",
    "model_import_settings": "import_settings",
    "material_import_settings": "material_import_settings",
}
ANALYSIS_FIELDS = {"solver_type": "type", "time_stepping": "time_stepping"}
PROCESS_FIELDS = {
    "model_part_name": "region", "variable_name": "variable", "value": "value",
    "constrained": "fixed", "modulus": "magnitude", "direction": "direction",
    "interval": "interval",
}
MATERIAL_FIELDS = {"Variables": "properties", "constitutive_law": "law", "Tables": "tables"}


class TemplateError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise TemplateError(f"Cannot read input file {path.name}") from error


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")


def asset_path(directory: Path, filename: str) -> Path:
    relative = Path(filename)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise TemplateError(f"Expected a relative asset filename: {filename}")
    path = directory / relative
    if not path.resolve().is_relative_to(directory.resolve()):
        raise TemplateError(f"Asset escapes its bundle: {filename}")
    return path


def materials_filename(parameters: dict) -> str | None:
    solver = parameters.get("solver_settings") or {}
    settings = solver.get("material_import_settings") or {}
    return settings.get("materials_filename")


def mesh_filenames(parameters: dict) -> tuple[str, ...]:
    names = []
    for modeler in parameters.get("modelers") or []:
        name = modeler.get("name", modeler.get("modeler_name", ""))
        if name.split(".")[-1] == "ImportMDPAModeler":
            names.append(modeler["parameters"]["input_filename"])
    solver = parameters.get("solver_settings") or {}
    settings = solver.get("model_import_settings") or {}
    if settings.get("input_type") == "mdpa":
        names.append(settings["input_filename"])
    return tuple(dict.fromkeys(name if name.endswith(".mdpa") else f"{name}.mdpa" for name in names))


def input_files(parameters: dict) -> tuple[str, ...]:
    material_file = materials_filename(parameters)
    return (PROJECT_PARAMETERS, *((material_file,) if material_file else ()), *mesh_filenames(parameters))


def take_fields(source: dict, mapping: dict[str, str]) -> dict:
    return {semantic: source.pop(native) for native, semantic in mapping.items() if native in source}


def merge_owned(residual: dict, owned: dict, context: str) -> dict:
    overlap = residual.keys() & owned.keys()
    if overlap:
        raise TemplateError(f"Duplicate owners in {context}: {', '.join(sorted(overlap))}")
    return {**deepcopy(residual), **owned}


def native_fields(settings: dict, mapping: dict[str, str]) -> dict:
    reverse = {semantic: native for native, semantic in mapping.items()}
    return {reverse.get(key, key): deepcopy(value) for key, value in settings.items()}


def stable_id(prefix: str, identity: str, existing: dict) -> str:
    digest = hashlib.sha256(identity.encode()).hexdigest()[:12]
    identifier = f"{prefix}-{digest}"
    occurrence = 2
    while identifier in existing:
        identifier = f"{prefix}-{digest}-{occurrence}"
        occurrence += 1
    return identifier


def import_component(item: dict, group: str, existing: dict, modeler: bool = False) -> Component:
    descriptor = deepcopy(item)
    parameter_key = "parameters" if modeler else "Parameters"
    present = parameter_key in descriptor
    parameters = descriptor.pop(parameter_key, {})
    name = str(descriptor.get("process_name", descriptor.get("name", descriptor.get("modeler_name", "unknown"))))
    capability = None
    for identifier, entry in CAPABILITIES.items():
        fields = ("name",) if "name" in entry else ("process_name", "python_module")
        if all(descriptor.get(field) == entry[field] for field in fields):
            if modeler or descriptor.get("kratos_module", "KratosMultiphysics") == "KratosMultiphysics":
                capability = identifier
                break
    settings = {}
    residual = deepcopy(parameters)
    if capability and isinstance(residual, dict):
        if capability in {"assign_vector_variable", "assign_vector_by_direction_to_condition"}:
            settings = take_fields(residual, PROCESS_FIELDS)
        else:
            settings = {("region" if key == "model_part_name" else key): value for key, value in residual.items()}
            residual = {}
    region = parameters.get("model_part_name", "") if isinstance(parameters, dict) else ""
    variable = parameters.get("variable_name", "") if isinstance(parameters, dict) else ""
    identifier = stable_id("component", f"{group}|{name}|{region}|{variable}", existing)
    return Component(
        id=identifier, label=f"{region}: {variable}".strip(": ") or name,
        capability=capability, settings=settings,
        native={"descriptor": descriptor, "parameters": residual,
                "parameter_key": parameter_key if present else None},
    )


def export_component(component: Component, modeler: bool = False) -> dict:
    descriptor = component.native.get("descriptor", {})
    residual = component.native.get("parameters", {})
    if component.capability in {"assign_vector_variable", "assign_vector_by_direction_to_condition"}:
        settings = native_fields(component.settings, PROCESS_FIELDS)
    else:
        settings = native_fields(component.settings, {"model_part_name": "region"})
    parameter_key = component.native.get("parameter_key", "parameters" if modeler else "Parameters")
    if settings and parameter_key is None:
        parameter_key = "parameters" if modeler else "Parameters"
    if not parameter_key:
        return deepcopy(descriptor)
    parameters = merge_owned(residual, settings, component.id) if isinstance(residual, dict) else residual
    return merge_owned(descriptor, {parameter_key: parameters}, component.id)


def add_region(case: Case, name: str, mesh_id: str | None = None) -> None:
    if name not in case.model.regions:
        parent = name.rsplit(".", 1)[0] if "." in name else None
        case.model.regions[name] = Region(name=name, parent=parent)
    if mesh_id and mesh_id not in case.model.regions[name].mesh_ids:
        case.model.regions[name].mesh_ids.append(mesh_id)


def load_case(directory: Path, revision: int = 0) -> Case:
    parameters = read_json(directory / PROJECT_PARAMETERS)
    material_file = materials_filename(parameters)
    material_document = read_json(asset_path(directory, material_file)) if material_file else {}
    remainder = deepcopy(parameters)
    sections = []
    case = Case(problem_name="", revision=revision)

    problem = remainder.get("problem_data")
    if isinstance(problem, dict):
        remainder.pop("problem_data")
        sections.append("problem_data")
    else:
        problem = {}
    if "problem_name" in problem:
        case.problem_name = problem.pop("problem_name")
        sections.append("problem_name")
    case.analysis.update(take_fields(problem, {"start_time": "start_time", "end_time": "end_time"}))
    case.execution = problem

    solver = remainder.get("solver_settings")
    if isinstance(solver, dict):
        remainder.pop("solver_settings")
        sections.append("solver_settings")
    else:
        solver = {}
    case.model.settings = take_fields(solver, MODEL_FIELDS)
    case.analysis.update(take_fields(solver, ANALYSIS_FIELDS))
    case.numerics = solver
    if "analysis_stage" in remainder:
        case.analysis["stage"] = remainder.pop("analysis_stage")

    for group_key, order, is_output in [("processes", case.process_groups, False), ("output_processes", case.output_groups, True)]:
        groups = remainder.get(group_key)
        if not isinstance(groups, dict):
            continue
        remainder.pop(group_key)
        sections.append(group_key)
        for group, items in groups.items():
            order[group] = []
            for item in items:
                component = import_component(item, group, {key: True for ids in order.values() for key in ids})
                if is_output:
                    collection = case.outputs
                elif component.capability == "assign_vector_by_direction_to_condition":
                    collection = case.loads
                elif component.capability == "assign_vector_variable":
                    collection = case.boundary_conditions
                else:
                    collection = case.auxiliary_processes
                collection[component.id] = component
                order[group].append(component.id)

    modelers = remainder.get("modelers")
    if isinstance(modelers, list):
        remainder.pop("modelers")
        sections.append("modelers")
        for item in modelers:
            component = import_component(item, "modelers", case.preparation, modeler=True)
            case.preparation[component.id] = component
            case.preparation_order.append(component.id)

    material_remainder = deepcopy(material_document)
    properties = material_remainder.get("properties")
    if isinstance(properties, list):
        material_remainder.pop("properties")
        sections.append("material_properties")
        for entry in properties:
            assignment_native = deepcopy(entry)
            region = assignment_native.pop("model_part_name")
            properties_id = assignment_native.pop("properties_id")
            content = assignment_native.pop("Material")
            material_id = stable_id("material", f"{properties_id}|{region}", case.materials)
            case.materials[material_id] = Material(
                id=material_id, label=region, settings=take_fields(content, MATERIAL_FIELDS), native=content,
            )
            assignment_id = stable_id("assignment", f"{properties_id}|{region}", case.material_assignments)
            case.material_assignments[assignment_id] = MaterialAssignment(
                id=assignment_id, material_id=material_id, region=region,
                properties_id=properties_id, native=assignment_native,
            )
            case.material_order.append(assignment_id)

    root = case.model.settings.get("root")
    if root:
        add_region(case, root)
    for filename in mesh_filenames(parameters):
        path = asset_path(directory, filename)
        mesh_id = stable_id("mesh", filename, case.model.meshes)
        case.model.meshes[mesh_id] = MeshAsset(filename=filename, sha256=sha256(path))
        mesh_root = root
        for modeler in case.preparation.values():
            input_name = modeler.settings.get("input_filename", "")
            if modeler.capability == "import_mdpa" and filename in {input_name, f"{input_name}.mdpa"}:
                mesh_root = modeler.settings.get("region", root)
                break
        if mesh_root:
            add_region(case, mesh_root, mesh_id)
            parents = [mesh_root]
            with path.open() as source:
                for line in source:
                    words = line.split()
                    if words[:2] == ["Begin", "SubModelPart"]:
                        name = f"{parents[-1]}.{words[2]}"
                        add_region(case, name, mesh_id)
                        parents.append(name)
                    elif words[:2] == ["End", "SubModelPart"]:
                        parents.pop()
    case.extensions = {"project": remainder, "materials": material_remainder, "sections": sections}
    return case


def render_case(case: Case) -> tuple[dict, dict]:
    """Compile native configuration without consulting mutable template files."""
    sections = case.extensions.get("sections", [])
    owned = {}
    problem = {}
    if "problem_name" in sections or case.problem_name:
        problem["problem_name"] = case.problem_name
    problem.update({key: deepcopy(case.analysis[key]) for key in ("start_time", "end_time") if key in case.analysis})
    if "problem_data" in sections or problem or case.execution:
        owned["problem_data"] = merge_owned(case.execution, problem, "problem_data")
    solver = native_fields(case.model.settings, MODEL_FIELDS)
    solver.update(native_fields({key: value for key, value in case.analysis.items() if key in ANALYSIS_FIELDS.values()}, ANALYSIS_FIELDS))
    if "solver_settings" in sections or solver or case.numerics:
        owned["solver_settings"] = merge_owned(case.numerics, solver, "solver_settings")
    if "stage" in case.analysis:
        owned["analysis_stage"] = case.analysis["stage"]
    components = {**case.boundary_conditions, **case.loads, **case.initial_conditions, **case.auxiliary_processes}
    if "processes" in sections or case.process_groups:
        owned["processes"] = {group: [export_component(components[identifier]) for identifier in ids] for group, ids in case.process_groups.items()}
    if "output_processes" in sections or case.output_groups:
        owned["output_processes"] = {group: [export_component(case.outputs[identifier]) for identifier in ids] for group, ids in case.output_groups.items()}
    if "modelers" in sections or case.preparation_order:
        owned["modelers"] = [export_component(case.preparation[identifier], modeler=True) for identifier in case.preparation_order]
    material_owned = {}
    if "material_properties" in sections or case.material_order:
        entries = []
        for identifier in case.material_order:
            assignment = case.material_assignments[identifier]
            material = case.materials[assignment.material_id]
            content = merge_owned(material.native, native_fields(material.settings, MATERIAL_FIELDS), material.id)
            entries.append(merge_owned(assignment.native, {
                "model_part_name": assignment.region, "properties_id": assignment.properties_id, "Material": content,
            }, assignment.id))
        material_owned["properties"] = entries
    return (
        merge_owned(case.extensions.get("project", {}), owned, "ProjectParameters"),
        merge_owned(case.extensions.get("materials", {}), material_owned, "materials"),
    )


def compile_case(case: Case, assets_dir: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"Bundle already exists: {destination}")
    parameters, materials = render_case(case)
    material_file = materials_filename(parameters)
    required_meshes = set(mesh_filenames(parameters))
    assets = {mesh.filename: mesh for mesh in case.model.meshes.values()}
    for filename in required_meshes:
        if filename not in assets:
            raise TemplateError(f"Mesh is not a registered immutable asset: {filename}")
        source = asset_path(assets_dir, filename)
        if not source.is_file() or sha256(source) != assets[filename].sha256:
            raise TemplateError(f"Mesh asset is missing or changed: {filename}")
    if material_file:
        asset_path(destination, material_file)
    destination.mkdir(parents=True)
    try:
        write_json(destination / "case.json", case.model_dump(mode="json"))
        write_json(destination / PROJECT_PARAMETERS, parameters)
        if material_file:
            write_json(asset_path(destination, material_file), materials)
        for filename in sorted(required_meshes):
            target = asset_path(destination, filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(asset_path(assets_dir, filename), target)
        files = ("case.json", *input_files(parameters))
        write_json(destination / "manifest.json", {
            "schema_version": "ksa.bundle/0.2", "case_revision": case.revision,
            "target": case.target,
            "files": {name: {"sha256": sha256(destination / name)} for name in files},
        })
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
