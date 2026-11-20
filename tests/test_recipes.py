"""Offline synthetic regression checks. The temporary fixtures never operate a desktop."""
import argparse
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import experience as ex


class FakeEditor:
    real_device = False

    def __init__(self, project, **overrides):
        self.state = dict(version="1.0", dpi=96, layout=[100,80], project=project, foreground=True,
                          unknown_dialog=False, selected=False)
        self.state.update(overrides)
        self.actions = 0

    def snapshot(self, dest):
        return dict(self.state)

    def execute(self, action):
        self.actions += 1
        self.state["selected"] = True


class RecipeGuards(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.file = self.work/"recipe.json"
        self.recipe = {
            "schema":1, "id":"test-selection", "app":"jianying", "version":"1.0",
            "kind":"operation", "task_type":"video", "params":{"project":{"type":"str"}},
            "environment":dict(version="1.0", dpi=96, layout=[100,80], foreground=True,
                               unknown_dialog=False, project="${project}"),
            "native":{"version":"1.0", "probes":{}},
            "steps":[{"id":"select", "before":{"selected":False}, "action":{"op":"click","point":[2,4]},
                      "after":{"selected":True}}]}
        ex.write(self.file, self.recipe)
        self.params = {"project":"copy-a"}

    def prepare(self):
        return ex.prepare(self.recipe, self.params, self.work)

    def fixture(self, project="copy-a", **overrides):
        editor = FakeEditor(project, **overrides)
        output = self.work/project
        ex.run_recipe(self.recipe, {"project":project}, editor, output, self.work)
        return output/"result.json", editor

    def receipt_fixture(self, project):
        # Test receipt verification branches with an explicitly synthetic temporary fixture.
        path, _ = self.fixture(project)
        ex.write(path, dict(ex.read(path), real_device=True))
        return path

    def test_missing_parameter(self):
        self.params.clear()
        with self.assertRaisesRegex(ValueError, "Missing parameter"):
            self.prepare()

    def test_project_guard(self):
        self.recipe["environment"].pop("project")
        with self.assertRaisesRegex(ValueError, "guards"):
            self.prepare()

    def test_version_pin(self):
        self.recipe["native"]["version"] = "1.1"
        with self.assertRaisesRegex(ValueError, "pinned"):
            self.prepare()

    def test_app_identity(self):
        self.recipe["app"] = "unrelated-editor"
        with self.assertRaisesRegex(ValueError, "Jianying"):
            self.prepare()

    def test_focus_loss(self):
        path, editor = self.fixture(foreground=False)
        self.assertEqual((ex.read(path)["status"], editor.actions), ("interrupted", 0))

    def test_unknown_dialog(self):
        path, editor = self.fixture(unknown_dialog=True)
        self.assertEqual((ex.read(path)["status"], editor.actions), ("interrupted", 0))

    def test_layout_mismatch(self):
        path, editor = self.fixture(layout=[101,80])
        self.assertEqual((ex.read(path)["status"], editor.actions), ("interrupted", 0))

    def test_outside_coordinate(self):
        self.recipe["steps"][0]["action"]["point"] = [100,0]
        with self.assertRaisesRegex(ValueError, "outside"):
            self.prepare()

    def test_probe_bounds(self):
        self.recipe["native"]["probes"]["label"] = {"rect":[0,0,101,10]}
        with self.assertRaisesRegex(ValueError, "outside"):
            self.prepare()

    def test_step_filename(self):
        self.recipe["steps"][0]["id"] = "../escape"
        with self.assertRaisesRegex(ValueError, "step ID"):
            self.prepare()

    def test_key_boundaries(self):
        ex.check_keys("{Ctrl}a-1.0{Enter}")
        with self.assertRaisesRegex(ValueError, "key sequence"):
            ex.check_keys("{Win}r")

    def test_missing_after_state(self):
        self.recipe["steps"][0]["after"] = {}
        with self.assertRaisesRegex(ValueError, "postconditions"):
            self.prepare()

    def test_guard_override(self):
        self.recipe["steps"][0]["after"]["unknown_dialog"] = True
        with self.assertRaisesRegex(ValueError, "guard"):
            self.prepare()

    def test_mock_run_not_promoted(self):
        path, _ = self.fixture()
        with self.assertRaisesRegex(ValueError, "real device"):
            ex.verify_receipts(self.recipe, [path], self.work)

    def test_changed_trace(self):
        path = self.receipt_fixture("copy-a")
        (path.parent/"actions.jsonl").write_text("", encoding="utf8")
        with self.assertRaisesRegex(ValueError, "trace"):
            ex.verify_receipts(self.recipe,[path],self.work)

    def test_independent_projects(self):
        path = self.receipt_fixture("copy-a")
        with self.assertRaisesRegex(ValueError, "independent"):
            ex.verify_receipts(self.recipe,[path,path],self.work)

    def test_changed_recipe(self):
        path = self.receipt_fixture("copy-a")
        self.recipe["description"] = "modified"
        with self.assertRaisesRegex(ValueError, "changed"):
            ex.verify_receipts(self.recipe, [path], self.work)

    def test_audition(self):
        with self.assertRaisesRegex(ValueError,"listening"):
            ex.check_quality("audio", {"metrics":"passed"}, "123")

    def test_quality_binds_output(self):
        with self.assertRaisesRegex(ValueError, "output"):
            ex.check_quality("visual", {"visual":"actually-reviewed-pass","recipe_hash":"123",
                                        "output":str(self.file),"output_sha256":"changed"}, "123")

    def test_regression_bound_to_runtime(self):
        report = self.work/"regression.json"
        ex.write(report, dict(tests=20,failures=0,errors=0,source_hashes={}))
        with self.assertRaisesRegex(ValueError,"regression"):
            ex.verify_negative_tests(report)

    def test_temporary_registry_lifecycle(self):
        runs = [self.receipt_fixture(p) for p in ["copy-a","copy-b"]]
        report = self.work/"fixture.json"
        ex.write(report, dict(tests=20,failures=0,errors=0,source_hashes=ex.regression_sources()))
        data = self.work/"data"
        def finalize():
            return ex.finalize_recipe(self.file, runs, report, data=data)
        self.assertEqual(finalize()["status"], "applied")
        self.assertEqual(finalize()["status"], "already-applied")
        self.assertEqual(len(ex.find_recipes("video", "jianying","1.0",data=data)), 1)
        self.assertEqual(len(ex.find_recipes("video", "jianying","1.1",data=data)), 0)
        ex.write(self.file, dict(self.recipe, description="changed"))
        self.assertEqual(ex.find_recipes("video",data=data), [])
        ex.write(self.file, self.recipe)
        self.assertEqual(ex.deactivate_recipe(self.recipe, "failed", data)["status"], "rolled_back")
        self.assertEqual(ex.find_recipes("video", data=data), [])
        self.assertEqual(finalize()["status"], "candidate")

    def test_capture_keeps_recipe_inactive(self):
        data = self.work/"data"
        result = ex.capture("failure","gain did not persist","workflow.md",data)
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(ex.find_recipes("video",data=data), [])

    def test_private_template_resolution(self):
        template = self.work/"clip.png"
        template.write_bytes(b"synthetic")
        self.recipe["native"]["probes"]["clip_label"] = {"rect":[0,0,20,20],"template":"clip.png"}
        resolved,_ = self.prepare()
        self.assertEqual(resolved["native"]["probes"]["clip_label"]["template"], str(template))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RecipeGuards)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if args.report:
        ex.write(args.report, dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                                   source_hashes=ex.regression_sources(), basis="synthetic adapter checks"))
    sys.exit(0 if result.wasSuccessful() else 1)
