from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


class Region(StrEnum):
    VOLUME_1 = "Volume1"
    VOLUME_2 = "Volume2"
    VOLUME_3 = "Volume3"
    VOLUME_4 = "Volume4"
    VOLUME_5 = "Volume5"


class LoadTarget(StrEnum):
    POINT_1 = "Point1"
    POINT_2 = "Point2"
    RIGHT_END = "RightEnd"
    TOP_1 = "Top1"
    TOP_2 = "Top2"
    TOP_3 = "Top3"
    TOP_4 = "Top4"
    TOP_5 = "Top5"


def reject_boolean(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("expected a number, not a boolean")
    return value


PositiveNumber = Annotated[float, Field(gt=0), BeforeValidator(reject_boolean)]
NonNegativeNumber = Annotated[float, Field(ge=0), BeforeValidator(reject_boolean)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Material(StrictModel):
    young_modulus: PositiveNumber


class Load(StrictModel):
    magnitude: NonNegativeNumber


class Case(StrictModel):
    schema_version: Literal["ksa.case/0.1"]
    workflow_id: Literal["structural.static.segmented-beam-3d/v1"]
    template_id: Literal["test-model-3d/v1"]
    revision: Annotated[int, Field(ge=0)]
    unit_system: Literal["unconfirmed"]
    materials: dict[Region, Material]
    loads: dict[LoadTarget, Load]

    @model_validator(mode="after")
    def require_complete_case(self) -> "Case":
        if set(self.materials) != set(Region):
            raise ValueError("the case must contain Volume1 through Volume5")
        if set(self.loads) != set(LoadTarget):
            raise ValueError("the case must contain all eight reference loads")
        return self


class MaterialChange(StrictModel):
    region: Region
    young_modulus: PositiveNumber


class LoadChange(StrictModel):
    target: LoadTarget
    magnitude: NonNegativeNumber


class CaseChanges(StrictModel):
    material_changes: list[MaterialChange] = Field(default_factory=list)
    load_changes: list[LoadChange] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_unique_changes(self) -> "CaseChanges":
        if not self.material_changes and not self.load_changes:
            raise ValueError("at least one change is required")

        regions = [change.region for change in self.material_changes]
        targets = [change.target for change in self.load_changes]
        if len(regions) != len(set(regions)):
            raise ValueError("a material region can only appear once")
        if len(targets) != len(set(targets)):
            raise ValueError("a load target can only appear once")
        return self


class FieldChange(StrictModel):
    field: str
    before: float
    after: float


def update_values(case: Case, changes: CaseChanges) -> Case:
    data = case.model_dump(mode="json")

    for change in changes.material_changes:
        data["materials"][change.region.value]["young_modulus"] = change.young_modulus
    for change in changes.load_changes:
        data["loads"][change.target.value]["magnitude"] = change.magnitude

    return Case.model_validate(data)


def create_revision(before: Case, edited: Case) -> tuple[Case, list[FieldChange]]:
    changes: list[FieldChange] = []

    for region in Region:
        old = before.materials[region].young_modulus
        new = edited.materials[region].young_modulus
        if old != new:
            changes.append(
                FieldChange(
                    field=f"materials.{region.value}.young_modulus",
                    before=old,
                    after=new,
                )
            )

    for target in LoadTarget:
        old = before.loads[target].magnitude
        new = edited.loads[target].magnitude
        if old != new:
            changes.append(
                FieldChange(
                    field=f"loads.{target.value}.magnitude",
                    before=old,
                    after=new,
                )
            )

    if not changes:
        return before, []

    data = edited.model_dump(mode="json")
    data["revision"] = before.revision + 1
    return Case.model_validate(data), changes
