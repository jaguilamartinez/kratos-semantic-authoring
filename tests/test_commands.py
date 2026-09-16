from pathlib import Path
import unittest

from pydantic import ValidationError

from authoring.case import Component
from authoring.commands import COMMAND_ADAPTER, apply_commands, validate_case
from authoring.compiler import load_case, render_case


CASE_DIR = Path(__file__).resolve().parents[1] / "cases" / "test_model_3d.gid"


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case(CASE_DIR)

    def apply(self, *commands):
        return apply_commands(self.case, COMMAND_ADAPTER.validate_python(list(commands)))

    def test_reference_case_is_supported_without_claiming_a_native_check(self):
        report = validate_case(self.case)
        self.assertTrue(report.valid)
        self.assertTrue(report.execution_supported)
        self.assertEqual(report.native_check, "not_run")
        self.assertEqual(report.issues, [])

    def test_vector_support_and_directed_load_preserve_other_native_settings(self):
        boundary_id = next(iter(self.case.boundary_conditions))
        load_id = next(key for key, value in self.case.loads.items() if value.settings["region"].endswith("Top4"))
        before, _ = render_case(self.case)
        edited = self.apply(
            {"type": "define_boundary_condition", "id": boundary_id, "value": [0, None, 0], "fixed": [True, False, True]},
            {"type": "define_load", "id": load_id, "direction": [0, -1, 0], "interval": {"start": 0.2, "end": "End"}},
        )
        after, _ = render_case(edited)
        expected = before["processes"]
        expected["constraints_process_list"][0]["Parameters"].update(value=[0, None, 0], constrained=[True, False, True])
        target = next(item for item in expected["loads_process_list"] if item["Parameters"]["model_part_name"].endswith("Top4"))
        target["Parameters"].update(direction=[0, -1, 0], interval=[0.2, "End"])
        self.assertEqual(after, before)
        self.assertEqual(self.case.boundary_conditions[boundary_id].settings["value"], [0, 0, 0])
        self.assertEqual(edited.revision, 0)

    def test_add_remove_and_reorder_do_not_rename_existing_entities(self):
        original_ids = list(self.case.loads)
        edited = self.apply({"type": "define_load", "id": "extra-traction", "kind": "surface_traction", "region": "Structure.Top1", "magnitude": -10, "direction": [0, 0, 1]})
        self.assertEqual(list(edited.loads)[:-1], original_ids)
        self.case = edited
        order = list(reversed(edited.process_groups["loads_process_list"]))
        edited = self.apply({"type": "reorder_processes", "collection": "processes", "group": "loads_process_list", "ids": order})
        self.assertEqual(edited.process_groups["loads_process_list"], order)
        self.case = edited
        edited = self.apply({"type": "remove_entity", "collection": "loads", "id": "extra-traction"})
        self.assertEqual(set(edited.loads), set(original_ids))
        self.assertNotIn("extra-traction", edited.process_groups["loads_process_list"])

    def test_invalid_batch_is_atomic(self):
        original = self.case.model_dump()
        load_id = next(iter(self.case.loads))
        with self.assertRaisesRegex(ValueError, "Unknown region"):
            self.apply(
                {"type": "define_load", "id": load_id, "magnitude": 300},
                {"type": "define_load", "id": "missing-region", "region": "NotInTheMesh", "kind": "point_force", "magnitude": 10, "direction": [1, 0, 0]},
            )
        self.assertEqual(self.case.model_dump(), original)

    def test_material_definition_is_separate_from_assignment(self):
        assignment = next(item for item in self.case.material_assignments.values() if item.region.endswith("Volume3"))
        edited = self.apply(
            {"type": "define_material", "id": "new-elastic-material", "law": "LinearElastic3DLaw", "properties": [{"name": "YOUNG_MODULUS", "value": 8e9}, {"name": "POISSON_RATIO", "value": 0.25}, {"name": "DENSITY", "value": 1200}]},
            {"type": "assign_material", "id": assignment.id, "material_id": "new-elastic-material", "region": assignment.region, "properties_id": assignment.properties_id},
        )
        self.assertEqual(edited.material_assignments[assignment.id].material_id, "new-elastic-material")
        self.assertIn(assignment.material_id, edited.materials)
        _, materials = render_case(edited)
        native = next(item for item in materials["properties"] if item["model_part_name"] == assignment.region)
        self.assertEqual(native["Material"]["Variables"]["YOUNG_MODULUS"], 8e9)
        with self.assertRaisesRegex(ValueError, "Remove material assignments"):
            self.apply({"type": "remove_entity", "collection": "materials", "id": assignment.material_id})

    def test_missing_material_properties_and_duplicate_properties_id_fail(self):
        with self.assertRaisesRegex(ValueError, "requires POISSON_RATIO"):
            self.apply({"type": "define_material", "id": "incomplete", "law": "LinearElastic3DLaw", "properties": [{"name": "YOUNG_MODULUS", "value": 100}]})
        assignment = next(iter(self.case.material_assignments.values()))
        with self.assertRaisesRegex(ValueError, "Duplicate properties ID"):
            self.apply({"type": "assign_material", "id": "duplicate", "material_id": assignment.material_id, "region": assignment.region, "properties_id": assignment.properties_id})

    def test_output_and_solver_patches_only_change_requested_fields(self):
        output_id = next(key for key, value in self.case.outputs.items() if value.capability == "vtk_output")
        before, _ = render_case(self.case)
        edited = self.apply(
            {"type": "configure_numerics", "max_iterations": 20, "line_search": True},
            {"type": "configure_analysis", "end_time": 2, "time_step": 0.2},
            {"type": "configure_output", "id": output_id, "interval": 2, "nodal_variables": ["DISPLACEMENT"]},
            {"type": "configure_component", "id": output_id, "options": {"capability": "vtk_output", "output_precision": 9}},
        )
        after, _ = render_case(edited)
        before["solver_settings"].update(max_iteration=20, line_search=True)
        before["solver_settings"]["time_stepping"]["time_step"] = 0.2
        before["problem_data"]["end_time"] = 2
        before["output_processes"]["vtk_output"][0]["Parameters"].update(output_interval=2, nodal_solution_step_data_variables=["DISPLACEMENT"], output_precision=9)
        self.assertEqual(after, before)

    def test_unknown_native_component_is_preserved_but_not_execution_supported(self):
        self.case.auxiliary_processes["external"] = Component(id="external", label="Custom", native={"descriptor": {"python_module": "custom"}, "parameter_key": "Parameters", "parameters": {"flag": True}})
        self.case.process_groups.setdefault("list_other_processes", []).append("external")
        report = validate_case(self.case)
        self.assertTrue(report.valid)
        self.assertFalse(report.execution_supported)
        self.assertTrue(any(item.path == "auxiliary_processes.external" and item.status == "native-only" for item in report.coverage))

    def test_reorder_duplicate_and_protected_mesh_import_removal_fail(self):
        ids = self.case.process_groups["loads_process_list"]
        with self.assertRaisesRegex(ValueError, "exactly once"):
            self.apply({"type": "reorder_processes", "collection": "processes", "group": "loads_process_list", "ids": [ids[0]] * len(ids)})
        import_id = next(key for key, value in self.case.preparation.items() if value.capability == "import_mdpa")
        with self.assertRaisesRegex(ValueError, "mesh-import"):
            self.apply({"type": "remove_entity", "collection": "preparation", "id": import_id})

    def test_typed_commands_reject_booleans_and_arbitrary_native_modules(self):
        with self.assertRaises(ValidationError):
            COMMAND_ADAPTER.validate_python([{"type": "define_load", "id": "load", "magnitude": True}])
        with self.assertRaises(ValidationError):
            COMMAND_ADAPTER.validate_python([{"type": "define_load", "id": "load", "python_module": "anything"}])
        with self.assertRaisesRegex(ValueError, "verified profiles"):
            self.apply({"type": "configure_analysis", "analysis_type": "dynamic"})


if __name__ == "__main__":
    unittest.main()
