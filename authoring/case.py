import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MeshAsset(StrictModel):
    filename: str
    sha256: str


class Region(StrictModel):
    name: str
    parent: str | None = None
    mesh_ids: list[str] = Field(default_factory=list)


class ModelDefinition(StrictModel):
    settings: dict[str, JsonValue] = Field(default_factory=dict)
    regions: dict[str, Region] = Field(default_factory=dict)
    meshes: dict[str, MeshAsset] = Field(default_factory=dict)


class Component(StrictModel):
    id: str
    label: str
    capability: str | None = None
    settings: dict[str, JsonValue] = Field(default_factory=dict)
    native: dict[str, JsonValue] = Field(default_factory=dict)


class Material(StrictModel):
    id: str
    label: str
    settings: dict[str, JsonValue] = Field(default_factory=dict)
    native: dict[str, JsonValue] = Field(default_factory=dict)


class MaterialAssignment(StrictModel):
    id: str
    material_id: str
    region: str
    properties_id: int
    native: dict[str, JsonValue] = Field(default_factory=dict)


class Case(StrictModel):
    schema_version: Literal["ksa.structural-case/0.3"] = "ksa.structural-case/0.3"
    problem_name: str
    revision: int = Field(default=0, ge=0)
    unit_system: str = "unconfirmed"
    target: dict[str, JsonValue] = Field(default_factory=lambda: {
        "kratos_version": "10.4.3", "profile": "structural-static-3d", "catalog": "structural/1",
    })
    model: ModelDefinition = Field(default_factory=ModelDefinition)
    analysis: dict[str, JsonValue] = Field(default_factory=dict)
    numerics: dict[str, JsonValue] = Field(default_factory=dict)
    execution: dict[str, JsonValue] = Field(default_factory=dict)
    preparation: dict[str, Component] = Field(default_factory=dict)
    materials: dict[str, Material] = Field(default_factory=dict)
    material_assignments: dict[str, MaterialAssignment] = Field(default_factory=dict)
    boundary_conditions: dict[str, Component] = Field(default_factory=dict)
    loads: dict[str, Component] = Field(default_factory=dict)
    initial_conditions: dict[str, Component] = Field(default_factory=dict)
    auxiliary_processes: dict[str, Component] = Field(default_factory=dict)
    outputs: dict[str, Component] = Field(default_factory=dict)
    preparation_order: list[str] = Field(default_factory=list)
    material_order: list[str] = Field(default_factory=list)
    process_groups: dict[str, list[str]] = Field(default_factory=dict)
    output_groups: dict[str, list[str]] = Field(default_factory=dict)
    extensions: dict[str, JsonValue] = Field(default_factory=dict)


class FieldChange(StrictModel):
    field: str
    before: JsonValue = None
    after: JsonValue = None
    operation: Literal["add", "remove", "replace"] = "replace"


def diff_values(before: Any, after: Any, prefix: str = "") -> list[FieldChange]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            path = f"{prefix}.{key}" if prefix else key
            if key not in before:
                changes.append(FieldChange(field=path, after=after[key], operation="add"))
            elif key not in after:
                changes.append(FieldChange(field=path, before=before[key], operation="remove"))
            else:
                changes.extend(diff_values(before[key], after[key], path))
        return changes
    if json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True):
        return []
    return [FieldChange(field=prefix, before=before, after=after)]


def diff_cases(before: Case, after: Case) -> list[FieldChange]:
    return diff_values(
        before.model_dump(mode="json", exclude={"revision"}),
        after.model_dump(mode="json", exclude={"revision"}),
    )


def create_revision(before: Case, edited: Case) -> tuple[Case, list[FieldChange]]:
    changes = diff_cases(before, edited)
    if not changes:
        return before, []
    return edited.model_copy(update={"revision": before.revision + 1}, deep=True), changes
