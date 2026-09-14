from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def reject_boolean(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("expected a number, not a boolean")
    return value


Number = Annotated[float, BeforeValidator(reject_boolean)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Material(StrictModel):
    variables: dict[str, Number]


class Process(StrictModel):
    model_part_name: str | None = None
    process_name: str
    variable_name: str | None = None
    parameters: dict[str, Number]


class Case(StrictModel):
    schema_version: Literal["ksa.structural-case/0.2"]
    problem_name: str
    revision: Annotated[int, Field(ge=0)]
    unit_system: Literal["unconfirmed"]
    materials: dict[str, Material]
    processes: dict[str, Process]


class MaterialChange(StrictModel):
    model_part_name: str
    variable_name: str
    value: Number


class ProcessChange(StrictModel):
    process_id: str
    parameter_name: str
    value: Number


class CaseChanges(StrictModel):
    material_changes: list[MaterialChange] = Field(default_factory=list)
    process_changes: list[ProcessChange] = Field(default_factory=list)


class FieldChange(StrictModel):
    field: str
    before: float
    after: float


def update_values(case: Case, changes: CaseChanges) -> Case:
    data = case.model_dump(mode="json")

    for change in changes.material_changes:
        variables = data["materials"][change.model_part_name]["variables"]
        if change.variable_name not in variables:
            raise ValueError(f"Unknown material variable: {change.variable_name}")
        variables[change.variable_name] = change.value

    for change in changes.process_changes:
        parameters = data["processes"][change.process_id]["parameters"]
        if change.parameter_name not in parameters:
            raise ValueError(f"Unknown process parameter: {change.parameter_name}")
        parameters[change.parameter_name] = change.value

    return Case.model_validate(data)


def create_revision(before: Case, edited: Case) -> tuple[Case, list[FieldChange]]:
    changes: list[FieldChange] = []

    for model_part_name, material in before.materials.items():
        for variable_name, old_value in material.variables.items():
            new_value = edited.materials[model_part_name].variables[variable_name]
            if old_value != new_value:
                changes.append(
                    FieldChange(
                        field=f"materials.{model_part_name}.variables.{variable_name}",
                        before=old_value,
                        after=new_value,
                    )
                )

    for process_id, process in before.processes.items():
        for parameter_name, old_value in process.parameters.items():
            new_value = edited.processes[process_id].parameters[parameter_name]
            if old_value != new_value:
                changes.append(
                    FieldChange(
                        field=f"processes.{process_id}.parameters.{parameter_name}",
                        before=old_value,
                        after=new_value,
                    )
                )

    if not changes:
        return before, []

    data = edited.model_dump(mode="json")
    data["revision"] = before.revision + 1
    return Case.model_validate(data), changes
