"""Small, typed edits to a case. A batch either succeeds in full or changes nothing."""

from typing import Annotated, Literal, Union

from pydantic import BeforeValidator, Field, TypeAdapter

from authoring.case import Case, Component, Material, MaterialAssignment, StrictModel
from authoring.catalog import CAPABILITIES, native_descriptor


def _number(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("Expected a number, not a boolean")
    return value


Number = Annotated[float, BeforeValidator(_number)]
Vector = Annotated[list[Number], Field(min_length=3, max_length=3)]
Displacement = Annotated[list[Number | None], Field(min_length=3, max_length=3)]
Fixed = Annotated[list[bool], Field(min_length=3, max_length=3)]


class Interval(StrictModel):
    start: Number
    end: Number | Literal["End"]


class ConfigureAnalysis(StrictModel):
    type: Literal["configure_analysis"]
    analysis_type: Literal["static", "dynamic", "modal"] | None = None
    start_time: Number | None = None
    end_time: Number | None = None
    time_step: Annotated[Number, Field(gt=0)] | None = None


class ConfigureNumerics(StrictModel):
    type: Literal["configure_numerics"]
    strategy: Literal["linear", "non_linear"] | None = None
    max_iterations: Annotated[int, Field(ge=1)] | None = None
    line_search: bool | None = None
    convergence_criterion: Literal["residual_criterion", "displacement_criterion", "and_criterion", "or_criterion"] | None = None
    displacement_relative_tolerance: Annotated[Number, Field(gt=0)] | None = None
    displacement_absolute_tolerance: Annotated[Number, Field(gt=0)] | None = None
    residual_relative_tolerance: Annotated[Number, Field(gt=0)] | None = None
    residual_absolute_tolerance: Annotated[Number, Field(gt=0)] | None = None


class MaterialProperty(StrictModel):
    name: Literal["DENSITY", "YOUNG_MODULUS", "POISSON_RATIO"]
    value: Number


class DefineMaterial(StrictModel):
    type: Literal["define_material"]
    id: str
    label: str | None = None
    law: Literal["LinearElastic3DLaw"] | None = None
    properties: list[MaterialProperty] = Field(default_factory=list)


class AssignMaterial(StrictModel):
    type: Literal["assign_material"]
    id: str
    material_id: str
    region: str
    properties_id: Annotated[int, Field(ge=0)]


class DefineBoundaryCondition(StrictModel):
    type: Literal["define_boundary_condition"]
    id: str
    label: str | None = None
    region: str | None = None
    value: Displacement | None = None
    fixed: Fixed | None = None
    interval: Interval | None = None


class DefineLoad(StrictModel):
    type: Literal["define_load"]
    id: str
    label: str | None = None
    region: str | None = None
    kind: Literal["point_force", "surface_traction"] | None = None
    magnitude: Number | None = None
    direction: Vector | None = None
    interval: Interval | None = None


class DefineInitialCondition(StrictModel):
    type: Literal["define_initial_condition"]
    id: str
    region: str
    variable: Literal["DISPLACEMENT", "VELOCITY", "ACCELERATION"]
    value: Vector


class ConfigureModelPreparation(StrictModel):
    type: Literal["configure_model_preparation"]
    id: str
    capability: Literal["import_mdpa", "create_entities"] | None = None
    label: str | None = None
    input_asset: str | None = None
    region: str | None = None


class AssignDiscretization(StrictModel):
    type: Literal["assign_discretization"]
    preparation_id: str
    region: str
    formulation: Literal["SmallDisplacementElement3D4N", "PointLoadCondition3D1N", "SurfaceLoadCondition3D3N"]


class ConfigureOutput(StrictModel):
    type: Literal["configure_output"]
    id: str
    writer: Literal["gid", "vtk"] | None = None
    label: str | None = None
    region: str | None = None
    interval: Annotated[Number, Field(gt=0)] | None = None
    control: Literal["time", "step"] | None = None
    output_path: str | None = None
    nodal_variables: list[str] | None = None
    gauss_point_variables: list[str] | None = None


EntityCollection = Literal["materials", "material_assignments", "boundary_conditions", "loads", "initial_conditions", "auxiliary_processes", "outputs", "preparation"]


class RemoveEntity(StrictModel):
    type: Literal["remove_entity"]
    collection: EntityCollection
    id: str


class ReorderProcesses(StrictModel):
    type: Literal["reorder_processes"]
    collection: Literal["processes", "outputs", "preparation"]
    group: str | None = None
    ids: list[str]


class VtkOptions(StrictModel):
    capability: Literal["vtk_output"]
    file_format: Literal["ascii", "binary"] | None = None
    output_precision: Annotated[int, Field(ge=1)] | None = None
    output_sub_model_parts: bool | None = None
    save_output_files_in_folder: bool | None = None


class GidOptions(StrictModel):
    capability: Literal["gid_output"]
    mode: Literal["GiD_PostAscii", "GiD_PostBinary"] | None = None
    deformed_mesh: bool | None = None
    write_conditions: bool | None = None
    multiple_files: bool | None = None
    body_output: bool | None = None
    node_output: bool | None = None
    skin_output: bool | None = None


class SolverOptions(StrictModel):
    capability: Literal["structural_static"]
    use_old_stiffness_in_first_iteration: bool | None = None
    echo_level: Annotated[int, Field(ge=0)] | None = None


class ConfigureComponent(StrictModel):
    type: Literal["configure_component"]
    id: str
    options: VtkOptions | GidOptions | SolverOptions


# A plain union produces anyOf, which also works in the SDK's strict tool schema.
CaseCommand = Union[ConfigureAnalysis, ConfigureNumerics, DefineMaterial, AssignMaterial, DefineBoundaryCondition, DefineLoad, DefineInitialCondition, ConfigureModelPreparation, AssignDiscretization, ConfigureOutput, RemoveEntity, ReorderProcesses, ConfigureComponent]
COMMAND_ADAPTER = TypeAdapter(list[CaseCommand])


class ValidationIssue(StrictModel):
    level: Literal["error", "warning"]
    path: str
    message: str


class CoverageEntry(StrictModel):
    path: str
    capability: str | None
    status: Literal["semantic", "native-only"]


class ValidationReport(StrictModel):
    valid: bool
    issues: list[ValidationIssue]
    coverage: list[CoverageEntry]
    execution_supported: bool
    native_check: Literal["not_run", "passed", "failed"] = "not_run"


COMPONENT_COLLECTIONS = ("preparation", "boundary_conditions", "loads", "initial_conditions", "auxiliary_processes", "outputs")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _region(case: Case, region: str) -> None:
    _require(region in case.model.regions, f"Unknown region: {region}")


def _component(case: Case, collection: str, entity_id: str, capability: str | None, label: str | None = None) -> Component:
    entities = getattr(case, collection)
    if entity_id in entities:
        entity = entities[entity_id]
        _require(entity.capability is not None, "Native-only components cannot be edited with semantic commands")
        _require(capability is None or entity.capability == capability, "Changing a component's native type requires removing it first")
    else:
        _require(capability in CAPABILITIES, "A supported capability is required for a new component")
        _require(not any(entity_id in getattr(case, name) for name in COMPONENT_COLLECTIONS), f"Component ID already exists: {entity_id}")
        entity = Component(id=entity_id, label=label or entity_id, capability=capability, settings={}, native=native_descriptor(capability))
        entities[entity_id] = entity
        if collection == "preparation":
            case.preparation_order.append(entity_id)
        elif collection == "outputs":
            case.output_groups.setdefault(capability, []).append(entity_id)
        else:
            group = "constraints_process_list" if collection == "boundary_conditions" else "loads_process_list"
            case.process_groups.setdefault(group, []).append(entity_id)
    if label is not None:
        entity.label = label
    return entity


def _set(settings: dict, values: dict, aliases: dict[str, str] | None = None) -> None:
    for key, value in values.items():
        if value is not None:
            settings[(aliases or {}).get(key, key)] = value


def _output_config(component: Component) -> dict:
    if component.capability == "gid_output":
        return component.settings.setdefault("postprocess_parameters", {}).setdefault("result_file_configuration", {})
    return component.settings


def _apply(case: Case, command: CaseCommand) -> None:
    values = command.model_dump(exclude={"type"}, exclude_none=True)
    if isinstance(command, ConfigureAnalysis):
        if command.analysis_type is not None:
            _require(command.analysis_type == "static", "Dynamic and modal authoring need their own verified profiles")
            case.analysis["type"] = "Static"
        _set(case.analysis, {key: values[key] for key in ("start_time", "end_time") if key in values})
        if command.time_step is not None:
            case.analysis.setdefault("time_stepping", {})["time_step"] = command.time_step
    elif isinstance(command, ConfigureNumerics):
        _set(case.numerics, values, {"strategy": "analysis_type", "max_iterations": "max_iteration"})
    elif isinstance(command, DefineMaterial):
        material = case.materials.get(command.id)
        if material is None:
            _require(command.law is not None, "A constitutive law is required for a new material")
            material = Material(id=command.id, label=command.label or command.id, settings={"properties": {}}, native={})
            case.materials[command.id] = material
        if command.label is not None:
            material.label = command.label
        if command.law is not None:
            material.settings.setdefault("law", {})["name"] = command.law
        if command.properties:
            _require(isinstance(material.settings.get("properties"), dict), "The material does not have a property dictionary")
            for prop in command.properties:
                material.settings["properties"][prop.name] = prop.value
    elif isinstance(command, AssignMaterial):
        _region(case, command.region)
        _require(command.material_id in case.materials, f"Unknown material: {command.material_id}")
        previous = case.material_assignments.get(command.id)
        case.material_assignments[command.id] = MaterialAssignment(**values, native=previous.native if previous else {})
        if previous is None:
            case.material_order.append(command.id)
    elif isinstance(command, (DefineBoundaryCondition, DefineLoad)):
        boundary = isinstance(command, DefineBoundaryCondition)
        collection = "boundary_conditions" if boundary else "loads"
        capability = "assign_vector_variable" if boundary else "assign_vector_by_direction_to_condition"
        entity = _component(case, collection, command.id, capability, command.label)
        _set(entity.settings, {key: value for key, value in values.items() if key not in {"id", "label", "interval", "kind"}})
        if boundary:
            entity.settings["variable"] = "DISPLACEMENT"
        elif command.kind is not None:
            entity.settings["variable"] = {"point_force": "POINT_LOAD", "surface_traction": "SURFACE_LOAD"}[command.kind]
        if command.interval is not None:
            entity.settings["interval"] = [command.interval.start, command.interval.end]
        entity.settings.setdefault("interval", [0.0, "End"])
    elif isinstance(command, DefineInitialCondition):
        raise ValueError("Initial-condition authoring is not supported by the static profile")
    elif isinstance(command, ConfigureModelPreparation):
        entity = _component(case, "preparation", command.id, command.capability, command.label)
        if command.region is not None:
            _region(case, command.region)
            entity.settings["region"] = command.region
        if command.input_asset is not None:
            _require(entity.capability == "import_mdpa", "Only mesh import accepts an input asset")
            _require(command.input_asset in case.model.meshes, f"Unknown mesh asset: {command.input_asset}")
            entity.settings["input_filename"] = case.model.meshes[command.input_asset].filename.removesuffix(".mdpa")
        if entity.capability == "create_entities":
            entity.settings.setdefault("elements_list", [])
            entity.settings.setdefault("conditions_list", [])
    elif isinstance(command, AssignDiscretization):
        _region(case, command.region)
        _require(command.preparation_id in case.preparation, f"Unknown preparation component: {command.preparation_id}")
        entity = case.preparation[command.preparation_id]
        _require(entity.capability == "create_entities", "Discretization belongs to a create-entities modeler")
        kind = "element" if "Element" in command.formulation else "condition"
        entries = entity.settings.setdefault(f"{kind}s_list", [])
        entry = next((item for item in entries if item.get("model_part_name") == command.region), None)
        if entry is None:
            entry = {"model_part_name": command.region}
            entries.append(entry)
        entry[f"{kind}_name"] = command.formulation
    elif isinstance(command, ConfigureOutput):
        entity = _component(case, "outputs", command.id, f"{command.writer}_output" if command.writer else None, command.label)
        settings = entity.settings
        if command.region is not None:
            settings["region"] = command.region
        if command.output_path is not None:
            settings["output_name" if entity.capability == "gid_output" else "output_path"] = command.output_path
        config = _output_config(entity)
        _set(config, {"output_interval": command.interval, "output_control_type": command.control})
        if entity.capability == "gid_output":
            _set(config, {"nodal_results": command.nodal_variables, "gauss_point_results": command.gauss_point_variables})
        else:
            _set(config, {"nodal_solution_step_data_variables": command.nodal_variables, "gauss_point_variables_extrapolated_to_nodes": command.gauss_point_variables})
    elif isinstance(command, RemoveEntity):
        entities = getattr(case, command.collection)
        _require(command.id in entities, f"Unknown {command.collection} entity: {command.id}")
        if command.collection == "materials":
            _require(not any(item.material_id == command.id for item in case.material_assignments.values()), "Remove material assignments before deleting their material")
        if command.collection == "preparation":
            _require(entities[command.id].capability != "import_mdpa", "Cannot remove the mesh-import preparation step")
        del entities[command.id]
        orders = [case.preparation_order] if command.collection == "preparation" else [case.material_order] if command.collection == "material_assignments" else list(case.process_groups.values()) + list(case.output_groups.values())
        for order in orders:
            if command.id in order:
                order.remove(command.id)
    elif isinstance(command, ReorderProcesses):
        if command.collection == "preparation":
            order = case.preparation_order
        else:
            groups = case.process_groups if command.collection == "processes" else case.output_groups
            _require(command.group in groups, f"Unknown process group: {command.group}")
            order = groups[command.group]
        _require(len(command.ids) == len(order) and set(command.ids) == set(order), "Reordering must include every existing ID exactly once")
        order[:] = command.ids
    elif isinstance(command, ConfigureComponent):
        options = command.options.model_dump(exclude={"capability"}, exclude_none=True)
        if isinstance(command.options, SolverOptions):
            _require(command.id == "numerics", "Solver options target the numerics component")
            _set(case.numerics, options)
        else:
            _require(command.id in case.outputs, f"Unknown output component: {command.id}")
            entity = case.outputs[command.id]
            _require(entity.capability == command.options.capability, "Options do not match this component's capability")
            if isinstance(command.options, VtkOptions):
                _set(entity.settings, options)
            else:
                config = _output_config(entity)
                flags = config.setdefault("gidpost_flags", {})
                for key in ("body_output", "node_output", "skin_output"):
                    if key in options:
                        config[key] = options[key]
                if command.options.mode is not None:
                    flags["GiDPostMode"] = command.options.mode
                for key, native, yes, no in (("deformed_mesh", "WriteDeformedMeshFlag", "WriteDeformed", "WriteUndeformed"), ("write_conditions", "WriteConditionsFlag", "WriteConditions", "WriteElementsOnly"), ("multiple_files", "MultiFileFlag", "MultipleFiles", "SingleFile")):
                    if key in options:
                        flags[native] = yes if options[key] else no


def apply_commands(case: Case, commands: list[CaseCommand]) -> Case:
    edited = case.model_copy(deep=True)
    for command in commands:
        _apply(edited, command)
    report = validate_case(edited)
    errors = [f"{issue.path}: {issue.message}" for issue in report.issues if issue.level == "error"]
    if errors:
        raise ValueError("; ".join(errors))
    return edited


def validate_case(case: Case) -> ValidationReport:
    issues: list[ValidationIssue] = []
    coverage: list[CoverageEntry] = []

    def issue(path: str, message: str, level: Literal["error", "warning"] = "error") -> None:
        issues.append(ValidationIssue(level=level, path=path, message=message))

    supported = str(case.analysis.get("type", "")).lower() == "static" and case.model.settings.get("dimension") == 3
    for path in ("model", "analysis", "numerics", "execution"):
        coverage.append(CoverageEntry(path=path, capability="structural_static", status="semantic"))

    for section in ("project", "materials"):
        residual = case.extensions.get(section)
        if isinstance(residual, dict) and residual:
            supported = False
            coverage.append(CoverageEntry(path=f"extensions.{section}", capability=None, status="native-only"))
            issue(f"extensions.{section}", "Native fields are preserved without a semantic editor", "warning")

    def region(value: object, path: str) -> None:
        if value not in case.model.regions:
            issue(path, f"Unknown region: {value}")

    if not supported:
        issue("analysis", "Only the static 3D profile has verified execution support", "warning")
    if case.model.settings.get("root") not in case.model.regions:
        issue("model.root", "The root model part must exist in the region index")
    if case.model.settings.get("import_settings", {}).get("input_type") == "use_input_model_part" and not any(item.capability == "import_mdpa" for item in case.preparation.values()):
        issue("preparation", "This model requires a mesh-import preparation step")
    start, end = case.analysis.get("start_time"), case.analysis.get("end_time")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end < start:
        issue("analysis.end_time", "End time must not precede start time")
    step = case.analysis.get("time_stepping", {}).get("time_step")
    if isinstance(step, (int, float)) and step <= 0:
        issue("analysis.time_stepping.time_step", "Time step must be positive")

    for entity_id, material in case.materials.items():
        path = f"materials.{entity_id}"
        law = material.settings.get("law")
        properties = material.settings.get("properties", {})
        known = isinstance(law, dict) and law.get("name") == "LinearElastic3DLaw"
        coverage.append(CoverageEntry(path=path, capability="LinearElastic3DLaw" if known else None, status="semantic" if known or not law else "native-only"))
        if law and not known:
            supported = False
            issue(path, "Constitutive law is preserved without an authoring profile", "warning")
        if known:
            for name in ("YOUNG_MODULUS", "POISSON_RATIO"):
                if not isinstance(properties, dict) or name not in properties:
                    issue(path, f"Linear elasticity requires {name}")
        if isinstance(properties, dict):
            for name in ("DENSITY", "YOUNG_MODULUS"):
                value = properties.get(name)
                if isinstance(value, (int, float)) and value <= 0:
                    issue(f"{path}.properties.{name}", "Must be positive")
            poisson = properties.get("POISSON_RATIO")
            if isinstance(poisson, (int, float)) and not -1 < poisson < 0.5:
                issue(f"{path}.properties.POISSON_RATIO", "Must be between -1 and 0.5")

    properties_ids: set[int] = set()
    for entity_id, assignment in case.material_assignments.items():
        path = f"material_assignments.{entity_id}"
        region(assignment.region, path)
        if assignment.material_id not in case.materials:
            issue(path, f"Unknown material: {assignment.material_id}")
        if assignment.properties_id in properties_ids:
            issue(path, f"Duplicate properties ID: {assignment.properties_id}")
        properties_ids.add(assignment.properties_id)

    formulations = {
        entry.get("model_part_name"): entry.get("condition_name")
        for item in case.preparation.values() if item.capability == "create_entities"
        for entry in item.settings.get("conditions_list", [])
    }

    for collection in COMPONENT_COLLECTIONS:
        for entity_id, component in getattr(case, collection).items():
            path = f"{collection}.{entity_id}"
            known = component.capability in CAPABILITIES
            coverage.append(CoverageEntry(path=path, capability=component.capability, status="semantic" if known else "native-only"))
            if not known:
                supported = False
                issue(path, "Native component is preserved but not semantically validated", "warning")
                continue
            settings = component.settings
            if component.capability != "create_entities":
                region(settings.get("region"), f"{path}.region")
            if component.native.get("parameters"):
                issue(path, "Additional native parameters are retained; the runtime check validates them", "warning")
            if component.capability in {"assign_vector_variable", "assign_vector_by_direction_to_condition"}:
                interval = settings.get("interval")
                if interval is not None and (not isinstance(interval, list) or len(interval) != 2 or not isinstance(interval[0], (int, float)) or not (interval[1] == "End" or isinstance(interval[1], (int, float)) and interval[1] >= interval[0])):
                    issue(f"{path}.interval", "Expected [start, end] with end >= start or 'End'")
            if component.capability == "assign_vector_variable":
                if settings.get("variable") != "DISPLACEMENT":
                    supported = False
                    issue(path, "Only prescribed displacement is in the current boundary-condition profile", "warning")
                if not isinstance(settings.get("value"), list) or len(settings["value"]) != 3:
                    issue(f"{path}.value", "Three displacement components are required")
                fixed = settings.get("fixed")
                if not isinstance(fixed, bool) and (not isinstance(fixed, list) or len(fixed) != 3 or not all(isinstance(item, bool) for item in fixed)):
                    issue(f"{path}.fixed", "Expected a boolean or three fixed-component flags")
            if component.capability == "assign_vector_by_direction_to_condition":
                if settings.get("variable") not in {"POINT_LOAD", "SURFACE_LOAD"}:
                    supported = False
                    issue(path, "This load variable has no verified point-force or surface-traction profile", "warning")
                direction = settings.get("direction")
                if not isinstance(direction, list) or len(direction) != 3 or not any(direction):
                    issue(f"{path}.direction", "A nonzero three-component direction is required")
                if "magnitude" not in settings:
                    issue(f"{path}.magnitude", "A load magnitude is required")
                expected = {"POINT_LOAD": "PointLoadCondition3D1N", "SURFACE_LOAD": "SurfaceLoadCondition3D3N"}.get(settings.get("variable"))
                if formulations and expected and formulations.get(settings.get("region")) != expected:
                    issue(path, "The load needs a compatible condition assignment on its target region")
            if component.capability == "import_mdpa":
                filename = settings.get("input_filename")
                if not isinstance(filename, str) or not any(asset.filename.removesuffix(".mdpa") == filename.removesuffix(".mdpa") for asset in case.model.meshes.values()):
                    issue(path, "Mesh import must refer to an immutable case asset")
            if component.capability == "create_entities":
                for key in ("elements_list", "conditions_list"):
                    for entry in settings.get(key, []):
                        region(entry.get("model_part_name"), f"{path}.{key}")
            if collection == "outputs":
                config = settings.get("postprocess_parameters", {}).get("result_file_configuration", {}) if component.capability == "gid_output" else settings
                interval = config.get("output_interval")
                if isinstance(interval, (int, float)) and interval <= 0:
                    issue(f"{path}.output_interval", "Output interval must be positive")

    def check_order(order: list[str], expected: set[str], path: str) -> None:
        if len(order) != len(expected) or set(order) != expected:
            issue(path, "Every entity must occur exactly once in its native order")

    check_order(case.preparation_order, set(case.preparation), "preparation_order")
    check_order(case.material_order, set(case.material_assignments), "material_order")
    check_order([value for group in case.output_groups.values() for value in group], set(case.outputs), "output_groups")
    process_ids = set().union(*(set(getattr(case, name)) for name in ("boundary_conditions", "loads", "initial_conditions", "auxiliary_processes")))
    check_order([value for group in case.process_groups.values() for value in group], process_ids, "process_groups")
    valid = not any(item.level == "error" for item in issues)
    return ValidationReport(valid=valid, issues=issues, coverage=coverage,
                            execution_supported=supported and valid)
