import json
import tempfile
import unittest
from pathlib import Path

from agents.testing import ScriptedModel, assistant_message, function_call
from pydantic import ValidationError

from authoring.agent import apply_case_changes, edit_case
from authoring.case import (
    Case,
    CaseChanges,
    LoadTarget,
    Region,
    create_revision,
    update_values,
)
from authoring.compiler import INPUT_FILES, compile_case, sha256
from authoring.store import CaseStore, RevisionConflict


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "cases" / "test_model_3d.gid"
BASE_CASE_PATH = ROOT / "authoring" / "base_case.json"


def load_case() -> Case:
    return Case.model_validate_json(BASE_CASE_PATH.read_text())


class TestCompiler(unittest.TestCase):
    def test_base_case_matches_the_original_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            compile_case(load_case(), TEMPLATE_DIR, bundle)

            for name in ("ProjectParameters.json", "StructuralMaterials.json"):
                original = json.loads((TEMPLATE_DIR / name).read_text())
                generated = json.loads((bundle / name).read_text())
                self.assertEqual(generated, original)

            self.assertEqual(
                sha256(bundle / "test_model_3d.mdpa"),
                sha256(TEMPLATE_DIR / "test_model_3d.mdpa"),
            )

    def test_compilation_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first"
            second = root / "second"
            case = load_case()

            compile_case(case, TEMPLATE_DIR, first)
            compile_case(case, TEMPLATE_DIR, second)

            names = ("case.json", *INPUT_FILES, "manifest.json")
            for name in names:
                self.assertEqual(
                    (first / name).read_bytes(),
                    (second / name).read_bytes(),
                )

    def test_changes_only_touch_the_selected_values(self) -> None:
        case = load_case()
        changes = CaseChanges.model_validate(
            {
                "material_changes": [
                    {"region": "Volume3", "young_modulus": 3_500_000_000}
                ],
                "load_changes": [{"target": "Top4", "magnitude": 40}],
            }
        )
        edited = update_values(case, changes)
        revised, diff = create_revision(case, edited)

        self.assertEqual(revised.revision, 1)
        self.assertEqual(
            [change.field for change in diff],
            ["materials.Volume3.young_modulus", "loads.Top4.magnitude"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            compile_case(revised, TEMPLATE_DIR, bundle)
            parameters = json.loads((bundle / "ProjectParameters.json").read_text())
            materials = json.loads((bundle / "StructuralMaterials.json").read_text())

        material_values = {
            item["model_part_name"]: item["Material"]["Variables"]["YOUNG_MODULUS"]
            for item in materials["properties"][1:]
        }
        load_values = {
            item["Parameters"]["model_part_name"]: item["Parameters"]["modulus"]
            for item in parameters["processes"]["loads_process_list"]
        }
        self.assertEqual(material_values["Structure.Volume3"], 3_500_000_000)
        self.assertEqual(load_values["Structure.Top4"], 40)
        self.assertEqual(material_values["Structure.Volume2"], 2_000_000_000)
        self.assertEqual(load_values["Structure.Top3"], 25)


class TestCaseValidation(unittest.TestCase):
    def test_rejects_invalid_numbers_and_duplicate_targets(self) -> None:
        invalid_changes = [
            {"material_changes": [{"region": "Volume1", "young_modulus": 0}]},
            {"load_changes": [{"target": "Point1", "magnitude": -1}]},
            {"load_changes": [{"target": "Point1", "magnitude": True}]},
            {
                "load_changes": [
                    {"target": "Top1", "magnitude": 20},
                    {"target": "Top1", "magnitude": 30},
                ]
            },
        ]

        for values in invalid_changes:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                CaseChanges.model_validate(values)

    def test_tool_schema_contains_only_supported_names(self) -> None:
        schema = apply_case_changes.params_json_schema
        self.assertEqual(
            set(schema["properties"]),
            {"material_changes", "load_changes"},
        )

        definitions = schema["$defs"]
        self.assertEqual(
            set(definitions["Region"]["enum"]),
            {region.value for region in Region},
        )
        self.assertEqual(
            set(definitions["LoadTarget"]["enum"]),
            {target.value for target in LoadTarget},
        )
        self.assertEqual(
            definitions["MaterialChange"]["properties"]["young_modulus"][
                "exclusiveMinimum"
            ],
            0,
        )
        self.assertEqual(
            definitions["LoadChange"]["properties"]["magnitude"]["minimum"],
            0,
        )


class TestCaseStore(unittest.TestCase):
    def test_publishes_a_new_bundle_and_rejects_a_stale_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CaseStore(BASE_CASE_PATH, TEMPLATE_DIR, Path(tmp))
            changes = CaseChanges.model_validate(
                {
                    "material_changes": [],
                    "load_changes": [{"target": "RightEnd", "magnitude": 30}],
                }
            )

            result = store.apply(0, changes)
            self.assertEqual(result.snapshot.case.revision, 1)
            self.assertEqual(result.snapshot.bundle_id, "revision-000001")
            self.assertTrue(
                (Path(tmp) / "revisions" / "revision-000001" / "manifest.json").is_file()
            )

            with self.assertRaises(RevisionConflict):
                store.apply(0, changes)


class TestAgentEditing(unittest.IsolatedAsyncioTestCase):
    async def test_tool_call_produces_one_candidate_revision(self) -> None:
        model = ScriptedModel(
            [
                [
                    function_call(
                        "apply_case_changes",
                        {
                            "material_changes": [
                                {
                                    "region": "Volume2",
                                    "young_modulus": 2_500_000_000,
                                }
                            ],
                            "load_changes": [],
                        },
                        call_id="call-1",
                    )
                ],
                [assistant_message("He cambiado Volume2.")],
            ]
        )

        result = await edit_case("Cambia Volume2", load_case(), model)

        self.assertEqual(result.draft.revision, 0)
        self.assertEqual(
            result.draft.materials[Region.VOLUME_2].young_modulus,
            2_500_000_000,
        )
        self.assertEqual(result.message, "He cambiado Volume2.")
        self.assertEqual(len(result.tool_calls), 1)
        model.assert_complete()

    async def test_question_does_not_create_a_revision(self) -> None:
        model = ScriptedModel(
            [[assistant_message("¿Qué valor quieres usar?")]]
        )

        result = await edit_case("Hazlo más rígido", load_case(), model)

        self.assertEqual(result.draft, load_case())
        self.assertEqual(result.message, "¿Qué valor quieres usar?")
        model.assert_complete()


if __name__ == "__main__":
    unittest.main()
