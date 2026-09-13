import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "cases" / "test_model_3d.gid"
INPUT_FILES = (
    "ProjectParameters.json",
    "StructuralMaterials.json",
    "test_model_3d.mdpa",
)


class TestReferenceCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parameters = json.loads((CASE_DIR / "ProjectParameters.json").read_text())
        cls.materials = json.loads((CASE_DIR / "StructuralMaterials.json").read_text())
        cls.mdpa = (CASE_DIR / "test_model_3d.mdpa").read_text()

    def test_required_inputs_exist(self) -> None:
        for name in INPUT_FILES:
            self.assertTrue((CASE_DIR / name).is_file(), name)

    def test_solver_configuration(self) -> None:
        problem = self.parameters["problem_data"]
        solver = self.parameters["solver_settings"]

        self.assertEqual(problem["parallel_type"], "OpenMP")
        self.assertEqual(solver["domain_size"], 3)
        self.assertEqual(solver["solver_type"].lower(), "static")
        self.assertEqual(solver["analysis_type"], "non_linear")
        self.assertEqual(solver["model_part_name"], "Structure")

    def test_materials(self) -> None:
        properties = self.materials["properties"][1:]
        young_moduli = [
            item["Material"]["Variables"]["YOUNG_MODULUS"]
            for item in properties
        ]

        self.assertEqual(young_moduli, [1e9, 2e9, 3e9, 4e9, 5e9])
        for item in properties:
            law = item["Material"]["constitutive_law"]["name"]
            self.assertEqual(law, "LinearElastic3DLaw")

    def test_model_parts(self) -> None:
        names = [f"Volume{index}" for index in range(1, 6)]
        names.extend(["LeftEnd", "Point1", "Point2", "RightEnd"])
        names.extend(f"Top{index}" for index in range(1, 6))

        for name in names:
            self.assertIn(f"Begin SubModelPart {name}", self.mdpa)

    def test_loads(self) -> None:
        loads = self.parameters["processes"]["loads_process_list"]
        expected = [
            ("Structure.Point1", "POINT_LOAD", 1000.0),
            ("Structure.Point2", "POINT_LOAD", 1000.0),
            ("Structure.RightEnd", "SURFACE_LOAD", 25.0),
        ]
        expected.extend(
            (f"Structure.Top{index}", "SURFACE_LOAD", 25.0)
            for index in range(1, 6)
        )
        actual = [
            (
                load["Parameters"]["model_part_name"],
                load["Parameters"]["variable_name"],
                load["Parameters"]["modulus"],
            )
            for load in loads
        ]

        self.assertEqual(actual, expected)
        for load in loads:
            self.assertEqual(load["Parameters"]["direction"], [0.0, 0.0, -1])

    def test_fixed_support(self) -> None:
        constraints = self.parameters["processes"]["constraints_process_list"]

        self.assertEqual(len(constraints), 1)
        support = constraints[0]["Parameters"]
        self.assertEqual(support["model_part_name"], "Structure.LeftEnd")
        self.assertEqual(support["variable_name"], "DISPLACEMENT")
        self.assertEqual(support["constrained"], [True, True, True])
        self.assertEqual(support["value"], [0.0, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
