from dataclasses import dataclass, field

from agents import (
    Agent,
    Model,
    ModelSettings,
    RunContextWrapper,
    Runner,
    function_tool,
)

from authoring.case import (
    Case,
    CaseChanges,
    LoadChange,
    MaterialChange,
    update_values,
)


INSTRUCTIONS = """You edit one fixed Kratos structural mechanics case.
Only change values explicitly requested by the user. The unit system has not been
confirmed, so never infer or convert units. If a request is ambiguous, contains
units, or asks for an unsupported change, ask a concise question and do not call
the tool. Do not include unchanged or unrequested fields. Call apply_case_changes
once with every requested change. Use an empty array for a category that does not
change. After a successful tool call, briefly state what changed. Never claim that
the case was run or physically validated.
"""


@dataclass
class EditContext:
    draft: Case
    tool_calls: list[dict[str, object]] = field(default_factory=list)


@function_tool(failure_error_function=None)
def apply_case_changes(
    context: RunContextWrapper[EditContext],
    material_changes: list[MaterialChange],
    load_changes: list[LoadChange],
) -> dict[str, object]:
    """Stage one atomic edit of the current structural case.

    Args:
        material_changes: Young's modulus changes in the model's current units.
        load_changes: Load magnitude changes in the model's current units.
    """
    changes = CaseChanges(
        material_changes=material_changes,
        load_changes=load_changes,
    )
    context.context.draft = update_values(context.context.draft, changes)
    context.context.tool_calls.append(
        {
            "name": "apply_case_changes",
            "arguments": changes.model_dump(mode="json"),
        }
    )
    return "Changes staged."


@dataclass(frozen=True)
class EditResult:
    draft: Case
    message: str
    tool_calls: list[dict[str, object]]


def case_change_tool_spec() -> dict[str, object]:
    return {
        "type": "function",
        "name": apply_case_changes.name,
        "description": apply_case_changes.description,
        "parameters": apply_case_changes.params_json_schema,
        "strict": apply_case_changes.strict_json_schema,
    }


async def edit_case(prompt: str, case: Case, model: str | Model) -> EditResult:
    context = EditContext(draft=case)
    agent = Agent[EditContext](
        name="Kratos case editor",
        instructions=(
            f"{INSTRUCTIONS}\nCurrent canonical case:\n"
            f"{case.model_dump_json(indent=2)}"
        ),
        model=model,
        tools=[apply_case_changes],
        model_settings=ModelSettings(
            parallel_tool_calls=False,
            store=False,
            response_include=["reasoning.encrypted_content"],
            timeout=30,
        ),
    )
    result = await Runner.run(
        agent,
        prompt,
        context=context,
        max_turns=3,
        run_config={"tracing_disabled": True},
    )
    return EditResult(
        draft=context.draft,
        message=str(result.final_output or ""),
        tool_calls=context.tool_calls,
    )
