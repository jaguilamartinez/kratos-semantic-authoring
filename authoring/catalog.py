"""The native components this authoring profile knows how to edit."""

KRATOS_VERSION = "10.4.3"
PROFILE = "structural-static-3d"

CAPABILITIES = {
    "assign_vector_variable": {
        "kind": "boundary_condition",
        "label": "Prescribed displacement",
        "process_name": "AssignVectorVariableProcess",
        "python_module": "assign_vector_variable_process",
        "fields": ["region", "value", "fixed", "interval"],
    },
    "assign_vector_by_direction_to_condition": {
        "kind": "load",
        "label": "Point force or surface traction",
        "process_name": "AssignVectorByDirectionToConditionProcess",
        "python_module": "assign_vector_by_direction_to_condition_process",
        "fields": ["region", "magnitude", "direction", "interval"],
    },
    "import_mdpa": {
        "kind": "preparation",
        "label": "Import mesh",
        "name": "Modelers.KratosMultiphysics.ImportMDPAModeler",
        "fields": ["input_filename", "region"],
    },
    "create_entities": {
        "kind": "preparation",
        "label": "Create elements and conditions",
        "name": "Modelers.KratosMultiphysics.CreateEntitiesFromGeometriesModeler",
        "fields": ["elements_list", "conditions_list"],
    },
    "gid_output": {
        "kind": "output",
        "label": "GiD output",
        "process_name": "GiDOutputProcess",
        "python_module": "gid_output_process",
        "fields": ["region", "output_name", "postprocess_parameters"],
    },
    "vtk_output": {
        "kind": "output",
        "label": "VTK output",
        "process_name": "VtkOutputProcess",
        "python_module": "vtk_output_process",
        "fields": ["region", "output_path", "output_interval", "file_format"],
    },
}


def discover_capabilities() -> dict[str, object]:
    return {
        "kratos_version": KRATOS_VERSION,
        "profile": PROFILE,
        "components": [{"id": key, **value} for key, value in CAPABILITIES.items()],
        "materials": ["LinearElastic3DLaw"],
        "elements": ["SmallDisplacementElement3D4N"],
        "conditions": ["PointLoadCondition3D1N", "SurfaceLoadCondition3D3N"],
        "deferred": ["dynamic", "modal", "initial_conditions", "pressure"],
        "preservation": "Unknown native fields and components are retained, not silently made editable.",
    }


def native_descriptor(capability: str) -> dict[str, object]:
    entry = CAPABILITIES[capability]
    if "name" in entry:
        return {"descriptor": {"name": entry["name"]}, "parameters": {}, "parameter_key": "parameters"}
    return {
        "descriptor": {"python_module": entry["python_module"], "kratos_module": "KratosMultiphysics", "process_name": entry["process_name"]},
        "parameters": {},
        "parameter_key": "Parameters",
    }
