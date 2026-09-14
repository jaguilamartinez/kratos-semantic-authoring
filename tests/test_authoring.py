import json
import tempfile
import unittest
from pathlib import Path

from agents.testing import ScriptedModel, assistant_message, function_call
from pydantic import ValidationError

from authoring.agent import apply_case_changes, edit_case
from authoring.case import CaseChanges, create_revision, update_values
from authoring.compiler import compile_case, input_files, load_case, read_json, sha256
from authoring.store import CaseStore, RevisionConflict


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "cases" / "test_model_3d.gid"


class TestCompiler(unittest.TestCase):
    def test_base_case_matches_the_original_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            compile_case(load_case(TEMPLATE_DIR), TEMPLATE_DIR, bundle)

            for name in ("ProjectParameters.json", "StructuralMaterials.json"):
                self.assertEqual(
                    read_json(bundle / name),
                    read_json(TEMPLATE_DIR / name),
                )

            self.assertEqual(
                sha256(bundle / "test_model_3d.mdpa"),
                sha256(TEMPLATE_DIR / "test_model_3d.mdpa"),
            )

    def test_compilation_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first"
            second = root / "second"
            case = load_case(TEMPLATE_DIR)
            parameters = read_json(TEMPLATE_DIR / "ProjectParameters.json")

            compile_case(case, TEMPLATE_DIR, first)
            compile_case(case, TEMPLATE_DIR, second)

            names = (
                "case.json",
                *input_files(parameters),
                "manifest.json",
            )
            for name in names:
                self.assertEqual(
                    (first / name).read_bytes(),
                    (second / name).read_bytes(),
                )

    def test_changes_only_touch_the_selected_values(self) -> None:
        case = load_case(TEMPLATE_DIR)
        changes = CaseChanges.model_validate(
            {
                "material_changes": [
                    {
                        "model_part_name": "Structure.Volume3",
                        "variable_name": "YOUNG_MODULUS",
                        "value": 3_500_000_000,
                    }
                ],
                "process_changes": [
                    {
                        "process_id": "loads_process_list:6",
                        "parameter_name": "modulus",
                        "value": 40,
                    }
                ],
            }
        )
        revised, diff = create_revision(case, update_values(case, changes))

        self.assertEqual(revised.revision, 1)
        self.assertEqual(
            [change.field for change in diff],
            [
                "materials.Structure.Volume3.variables.YOUNG_MODULUS",
                "processes.loads_process_list:6.parameters.modulus",
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            compile_case(revised, TEMPLATE_DIR, bundle)
            parameters = read_json(bundle / "ProjectParameters.json")
            materials = read_json(bundle / "StructuralMaterials.json")

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

    def test_template_names_and_sizes_are_not_part_of_the_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / "template"
            template.mkdir()
            self.write_generic_template(template)

            case = load_case(template)
            self.assertEqual(case.problem_name, "bridge_trial")
            self.assertEqual(set(case.materials), {"Frame.Core"})
            self.assertEqual(set(case.processes), {"actions:0"})

            changes = CaseChanges.model_validate(
                {
                    "material_changes": [
                        {
                            "model_part_name": "Frame.Core",
                            "variable_name": "DENSITY",
                            "value": 7800,
                        }
                    ],
                    "process_changes": [
                        {
                            "process_id": "actions:0",
                            "parameter_name": "factor",
                            "value": -12,
                        }
                    ],
                }
            )
            edited = update_values(case, changes)
            bundle = Path(tmp) / "bundle"
            compile_case(edited, template, bundle)

            parameters = read_json(bundle / "ProjectParameters.json")
            materials = read_json(bundle / "BridgeMaterials.json")
            self.assertEqual(
                materials["properties"][0]["Material"]["Variables"]["DENSITY"],
                7800,
            )
            self.assertEqual(
                parameters["processes"]["actions"][0]["Parameters"]["factor"],
                -12,
            )
            self.assertTrue((bundle / "bridge_mesh.mdpa").is_file())

    @staticmethod
    def write_generic_template(template: Path) -> None:
        parameters = {
            "analysis_stage": "example.structural_analysis",
            "problem_data": {"problem_name": "bridge_trial"},
            "solver_settings": {
                "material_import_settings": {
                    "materials_filename": "BridgeMaterials.json"
                }
            },
            "modelers": [
                {
                    "name": "Modelers.KratosMultiphysics.ImportMDPAModeler",
                    "parameters": {
                        "input_filename": "bridge_mesh",
                        "model_part_name": "Frame",
                    },
                }
            ],
            "processes": {
                "actions": [
                    {
                        "process_name": "ApplyAction",
                        "Parameters": {
                            "model_part_name": "Frame.Roof",
                            "variable_name": "LINE_LOAD",
                            "factor": 5.0,
                            "direction": [0.0, 0.0, -1.0],
                        },
                    }
                ]
            },
        }
        materials = {
            "properties": [
                {
                    "model_part_name": "Frame.Core",
                    "Material": {
                        "Variables": {"DENSITY": 7850.0, "POISSON_RATIO": 0.29}
                    },
                }
            ]
        }
        (template / "ProjectParameters.json").write_text(json.dumps(parameters))
        (template / "BridgeMaterials.json").write_text(json.dumps(materials))
        (template / "bridge_mesh.mdpa").write_text(
            "Begin ModelPartData\nEnd ModelPartData\n"
        )


class TestCaseContract(unittest.TestCase):
    def test_values_are_finite_numbers_but_not_case_specific(self) -> None:
        changes = CaseChanges.model_validate(
            {
                "process_changes": [
                    {
                        "process_id": "any-list:0",
                        "parameter_name": "factor",
                        "value": -1,
                    }
                ]
            }
        )
        self.assertEqual(changes.process_changes[0].value, -1)

        with self.assertRaises(ValidationError):
            CaseChanges.model_validate(
                {
                    "process_changes": [
                        {
                            "process_id": "any-list:0",
                            "parameter_name": "factor",
                            "value": True,
                        }
                    ]
                }
            )

    def test_tool_schema_uses_names_from_the_canonical_case(self) -> None:
        schema = apply_case_changes.params_json_schema
        self.assertEqual(
            set(schema["properties"]),
            {"material_changes", "process_changes"},
        )
        encoded = json.dumps(schema)
        self.assertNotIn("Volume1", encoded)
        self.assertNotIn("Top1", encoded)


class TestCaseStore(unittest.TestCase):
    def test_publishes_a_new_bundle_and_rejects_a_stale_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CaseStore(TEMPLATE_DIR, Path(tmp))
            changes = CaseChanges.model_validate(
                {
                    "process_changes": [
                        {
                            "process_id": "loads_process_list:2",
                            "parameter_name": "modulus",
                            "value": 30,
                        }
                    ]
                }
            )

            result = store.apply(0, changes)
            self.assertEqual(result.snapshot.case.revision, 1)
            self.assertEqual(result.snapshot.bundle_id, "revision-000001")
            self.assertTrue(
                (
                    Path(tmp)
                    / "revisions"
                    / "revision-000001"
                    / "manifest.json"
                ).is_file()
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
                                    "model_part_name": "Structure.Volume2",
                                    "variable_name": "DENSITY",
                                    "value": 1200,
                                }
                            ],
                            "process_changes": [],
                        },
                        call_id="call-1",
                    )
                ],
                [assistant_message("He cambiado la densidad de Structure.Volume2.")],
            ]
        )

        case = load_case(TEMPLATE_DIR)
        result = await edit_case("Cambia la densidad de Volume2", case, model)

        self.assertEqual(result.draft.revision, 0)
        self.assertEqual(
            result.draft.materials["Structure.Volume2"].variables["DENSITY"],
            1200,
        )
        self.assertEqual(
            result.message,
            "He cambiado la densidad de Structure.Volume2.",
        )
        self.assertEqual(len(result.tool_calls), 1)
        model.assert_complete()

    async def test_question_does_not_create_a_revision(self) -> None:
        model = ScriptedModel([[assistant_message("¿Qué valor quieres usar?")]])
        case = load_case(TEMPLATE_DIR)

        result = await edit_case("Hazlo más rígido", case, model)

        self.assertEqual(result.draft, case)
        self.assertEqual(result.message, "¿Qué valor quieres usar?")
        model.assert_complete()


if __name__ == "__main__":
    unittest.main()
