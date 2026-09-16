import tempfile
import unittest
from pathlib import Path

from agents.testing import ScriptedModel, assistant_message, function_call

from authoring.agent import edit_case
from authoring.case import diff_cases
from authoring.commands import COMMAND_ADAPTER, apply_commands
from authoring.compiler import compile_case, input_files, load_case, read_json, render_case, sha256
from authoring.store import CaseStore, DraftConflict, RevisionConflict


ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "cases" / "test_model_3d.gid"


class TestCanonicalCase(unittest.TestCase):
    def test_import_and_compile_are_lossless_for_the_reference_case(self) -> None:
        case = load_case(CASE_DIR)
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            compile_case(case, CASE_DIR, bundle)
            self.assertEqual(read_json(bundle / "ProjectParameters.json"), read_json(CASE_DIR / "ProjectParameters.json"))
            self.assertEqual(read_json(bundle / "StructuralMaterials.json"), read_json(CASE_DIR / "StructuralMaterials.json"))
            self.assertEqual(sha256(bundle / "test_model_3d.mdpa"), sha256(CASE_DIR / "test_model_3d.mdpa"))

    def test_case_has_stable_entities_and_preserves_native_values(self) -> None:
        case = load_case(CASE_DIR)
        self.assertEqual(len(case.model.regions), 15)
        self.assertEqual(len(case.loads), 8)
        self.assertEqual(case.loads[next(iter(case.loads))].settings["interval"], [0.0, "End"])
        self.assertTrue(all(entity.native["parameter_key"] == "Parameters" for entity in case.loads.values()))
        self.assertEqual(load_case(CASE_DIR).model_dump(), case.model_dump())

    def test_semantic_edit_changes_only_the_requested_native_fields(self) -> None:
        case = load_case(CASE_DIR)
        load_id = next(identifier for identifier, load in case.loads.items() if load.settings["region"].endswith("Top4"))
        before, materials_before = render_case(case)
        edited = apply_commands(case, COMMAND_ADAPTER.validate_python([{
            "type": "define_load", "id": load_id,
            "direction": [0, -1, 0], "interval": {"start": 0.2, "end": "End"},
        }, {
            "type": "define_boundary_condition", "id": next(iter(case.boundary_conditions)),
            "value": [0, None, 0], "fixed": [True, False, True],
        }]))
        after, materials_after = render_case(edited)
        self.assertEqual(materials_before, materials_after)
        self.assertEqual(after["processes"]["loads_process_list"][6]["Parameters"]["direction"], [0, -1, 0])
        self.assertEqual(after["processes"]["loads_process_list"][6]["Parameters"]["interval"], [0.2, "End"])
        self.assertEqual(before["processes"]["loads_process_list"][6]["Parameters"]["modulus"], after["processes"]["loads_process_list"][6]["Parameters"]["modulus"])
        self.assertTrue(diff_cases(case, edited))


class TestCaseStore(unittest.TestCase):
    def test_draft_requires_validation_and_publishes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = CaseStore(CASE_DIR, Path(temporary))
            case = store.read().case
            load_id = next(iter(case.loads))
            draft = store.propose(0, COMMAND_ADAPTER.validate_python([{
                "type": "define_load", "id": load_id, "magnitude": 30,
            }]))
            self.assertEqual(draft.base_revision, 0)
            self.assertIsNone(draft.validation)
            with self.assertRaisesRegex(ValueError, "Validate"):
                store.publish_draft(draft.id, draft.content_hash)
            draft = store.validate_draft(draft.id, draft.content_hash)
            self.assertTrue(draft.validation.valid)
            result = store.publish_draft(draft.id, draft.content_hash)
            self.assertEqual(result.snapshot.case.revision, 1)
            self.assertEqual(store.read_revision(0).case.revision, 0)
            self.assertEqual(store.read().case.revision, 1)
            with self.assertRaises(DraftConflict):
                store.publish_draft(draft.id, draft.content_hash)

    def test_stale_publication_does_not_overwrite_current_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = CaseStore(CASE_DIR, Path(temporary))
            first = store.propose(0, COMMAND_ADAPTER.validate_python([{
                "type": "configure_numerics", "max_iterations": 12,
            }]))
            first = store.validate_draft(first.id, first.content_hash)
            store.publish_draft(first.id, first.content_hash)
            second = store.propose(1, COMMAND_ADAPTER.validate_python([{
                "type": "configure_numerics", "max_iterations": 13,
            }]))
            third = store.propose(1, COMMAND_ADAPTER.validate_python([{
                "type": "configure_numerics", "max_iterations": 14,
            }]))
            third = store.validate_draft(third.id, third.content_hash)
            store.publish_draft(third.id, third.content_hash)
            with self.assertRaises(RevisionConflict):
                store.publish_draft(second.id, second.content_hash)


class TestAgentEditing(unittest.IsolatedAsyncioTestCase):
    async def test_agent_stages_typed_commands_without_publishing(self) -> None:
        case = load_case(CASE_DIR)
        load_id = next(iter(case.loads))
        model = ScriptedModel([
            [function_call("propose_case_changes", {
                "commands": [{"type": "define_load", "id": load_id, "magnitude": 60}],
            }, call_id="call-1")],
            [assistant_message("He preparado el cambio para revisión.")],
        ])
        result = await edit_case("Cambia la magnitud de esta carga a 60", case, model)
        self.assertEqual(result.draft.loads[load_id].settings["magnitude"], 60)
        self.assertEqual(result.draft.revision, case.revision)
        self.assertEqual(result.message, "He preparado el cambio para revisión.")
        self.assertEqual(len(result.tool_calls), 1)
        model.assert_complete()


if __name__ == "__main__":
    unittest.main()
