"""Offline transfer of an observed project toolchain through the normal CLI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectTools(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.store = self.work / "personal"
        self.proof = self.work / "private-customer-frames.txt"
        self.proof.write_text("private frame inspection fixture", encoding="utf8")
        self.tools = {
            "software": [{"name": "剪映专业版", "version": "11.8.0.14778"}],
            "skills": ["jianying-local"], "capabilities": ["subtitle-placement"],
            "uses": [
                {"kind": "software", "name": "剪映专业版", "purpose": "Reopened the draft and viewed caption frames."},
                {"kind": "skill", "name": "jianying-local", "purpose": "Created an editable timed caption track."},
            ],
        }
        self.form = {
            "id": "caption-position", "task": "video", "kind": "method", "topics": ["caption"],
            "environment": "Desktop editor", "method": "Reopen the editable timeline.",
            "check": "Inspect the caption location at the two intended frames.",
            "basis": "frames", "evidence": "Caption location persisted on both frames.", "author": "editor",
        }

    def put(self, name, data):
        path = self.work / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf8")
        return path

    def cli(self, command, *args, ok=True, store=None):
        if command.startswith("community-"):
            script = "community_memory"
        elif command.startswith("scene-"):
            script = "scene_memory"
        else:
            script = "experience"
        cmd = [sys.executable, "-B", "-X", "utf8", str(ROOT / "scripts" / (script + ".py")),
               "--data", str(store or self.store), command, *map(str, args)]
        run = subprocess.run(cmd, cwd=self.work, env=dict(os.environ, WATCH_AND_DO_QUEUE_WORKER="off"),
                             capture_output=True, encoding="utf8")
        if not ok:
            self.assertNotEqual(run.returncode, 0, run.stdout)
            return run.stderr
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def capture(self, tools=None, kind="success", ok=True):
        return self.cli("capture", "--kind", kind, "--task-type", "video", "--summary", "private-customer caption",
                        "--check", "private-customer frame pair", "--basis", "frames", "--evidence", self.proof,
                        "--tools", self.put("tools.json", self.tools if tools is None else tools), ok=ok)

    def draft(self, candidate, form, ok=True):
        return self.cli("community-draft", "--from-capture", candidate, "--input", self.put("form.json", form),
                        "--out", self.work / "card.json", ok=ok)

    def test_project_closeout_to_review_and_another_devices_preflight(self):
        candidate = self.capture()["candidate"]
        local = self.cli("find-captures", "--task-type", "video", "--query", "剪映 editable")
        self.assertEqual([(r["candidate"], r["tools"]) for r in local], [(candidate, self.tools)])
        inventory = self.put("local-inventory.json", [
            {"kind": "software", "name": "剪映专业版", "status": "found", "version": "12.0", "evidence": "About dialog."},
            {"kind": "skill", "name": "jianying-local", "status": "missing", "evidence": "Checked session skills."}])
        local_check = self.cli("community-preflight", "--capture-id", candidate, "--inventory", inventory)
        self.assertEqual(local_check["acceptance"]["check"], "private-customer frame pair")
        self.draft(candidate, self.form)
        card_path = self.work / "card.json"
        public = json.loads(card_path.read_text(encoding="utf8"))
        self.assertEqual(public, dict(self.form, tools=self.tools))
        self.cli("community-sharing", "--set", "review")
        preview = self.cli("community-share-preview", "--input", card_path)
        self.assertEqual(preview["queue_status"], "awaiting-approval")
        seen = self.cli("community-queue-review", "--all")["drafts"]
        self.assertEqual(seen, [{"sha256": preview["sha256"], "payload": public}])
        self.assertNotIn("private-customer", json.dumps(seen))
        self.assertNotIn(candidate, json.dumps(seen))

        # Independent offline fixture, with a different toolchain, then a separately opted-in pack.
        peer_tools = {"software": [{"name": "Peer Editor", "version": "3"}], "skills": "none",
                      "capabilities": ["subtitle-placement"],
                      "uses": [{"kind": "software", "name": "Peer Editor", "purpose": "Inspected the two frames."}]}
        report = self.work / "review.json"
        self.cli("community-review", "--card", card_path, "--reviewer", "observer", "--environment", "Peer device",
                 "--outcome", "reproduced", "--basis", "frames", "--evidence", "Both caption frames checked.",
                 "--tools", self.put("peer.json", peer_tools), "--out", report)
        peer = self.work / "another-device"
        pack = self.work / "pack.json"
        self.cli("community-release", "--version", "1", "--maintainer", "offline-fixture", "--review", report, "--out", pack)
        self.cli("community-install", "--allow-other-maintainer", "--input", pack, store=peer)
        found = self.cli("community-find", "--task", "video", "--brief", "剪映专业版", store=peer)
        row = next(r for r in found if r["id"] == self.form["id"])
        self.assertEqual(row["tools"], self.tools)
        self.assertEqual(row["reproductions"][0]["tools"], peer_tools)
        result = self.cli("community-preflight", "--installed-id", row["id"], "--inventory", inventory, store=peer)
        self.assertEqual(result["original_tools"], self.tools)
        self.assertEqual(result["software"][0]["recorded_version"], "11.8.0.14778")
        self.assertEqual(result["software"][0]["version_check"], "different")
        self.assertEqual(result["skills"][0]["status"], "missing")
        self.assertEqual(result["skills"][0]["used_for"], self.tools["uses"][1]["purpose"])
        self.assertEqual(result["acceptance"], dict(check=public["check"], basis="frames", status="needs-local-test"))

    def test_conflict_changed_evidence_and_sensitive_purpose_never_export(self):
        candidate = self.capture(kind="rollback")["candidate"]
        self.assertIn("does not match", self.draft(candidate, self.form, ok=False))
        form = dict(self.form, kind="pitfall")
        override = dict(self.tools, software=[{"name": "剪映专业版", "version": "unknown"}])
        self.assertIn("conflict", self.draft(candidate, dict(form, tools=override), ok=False))
        self.assertIn("conflict", self.draft(candidate, dict(form, tools=dict(self.tools, uses=[])), ok=False))
        self.proof.write_text("changed", encoding="utf8")
        self.assertIn("missing or changed", self.draft(candidate, form, ok=False))
        self.assertFalse((self.work / "card.json").exists())
        self.assertIn("each named", self.capture(dict(self.tools, uses=[]), ok=False))
        self.tools["uses"][0]["purpose"] = "Opened C:/Users/Private/secret.mp4"
        self.assertIn("private", self.capture(ok=False))
        self.assertEqual(len(self.cli("find-captures", "--task-type", "video")), 1)

    def test_scene_binding_and_legacy_capture(self):
        scene = dict(self.form, task="scene")
        lesson = dict(id=scene["id"], project="private-customer", method=scene["method"], check=scene["check"],
                      status="pass", verification="frames", topics=scene["topics"], evidence=[str(self.proof)], tools=self.tools)
        self.cli("scene-learn", "--input", self.put("lesson.json", lesson))
        form = self.put("scene-form.json", scene)
        path = self.work / "scene-card.json"
        self.cli("community-draft", "--from-scene", "--input", form, "--out", path)
        self.assertEqual(json.loads(path.read_text(encoding="utf8")), dict(scene, tools=self.tools))
        path.unlink()
        self.put("scene-form.json", dict(scene, tools=dict(self.tools, skills="none", uses=[])))
        self.assertIn("conflict", self.cli("community-draft", "--from-scene", "--input", form, "--out", path, ok=False))
        self.assertFalse(path.exists())
        old = self.cli("capture", "--kind", "observation", "--summary", "Legacy signal", "--evidence", "old note")
        self.assertEqual(old["status"], "candidate")
        self.assertEqual(self.cli("find-captures", "--task-type", "video"), [])
        self.assertIn("No structured project capture", self.draft(old["candidate"], self.form, ok=False))

    def test_powershell_routes_structured_capture_with_a_legacy_runtime_configured(self):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell not installed")
        runtime = self.work / "old-runtime"
        runtime.mkdir()
        (runtime / "experience.py").write_text('print("external recipe runtime")', encoding="utf8")
        cmd = [shell, "-NoProfile", "-File", str(ROOT / "scripts" / "experience.ps1"),
               "--data", str(self.store)]
        env = dict(os.environ, WATCH_AND_DO_RUNTIME=str(runtime), PYTHONDONTWRITEBYTECODE="1")
        def route(*args):
            return subprocess.run([*cmd, *map(str, args)], cwd=self.work, env=env, capture_output=True,
                                  check=True).stdout.decode("utf8", errors="replace").strip()
        actual = {"software": "none", "skills": "none", "capabilities": []}
        result = json.loads(route("capture", "--kind", "success", "--summary", "Manual check", "--evidence", self.proof,
                                  "--task-type", "video", "--basis", "manual", "--check", "Inspect film frame",
                                  "--tools", self.put("manual.json", actual)))
        found = json.loads(route("find-captures", "--task-type", "video"))
        self.assertEqual(found[0]["candidate"], result["candidate"])
        self.assertEqual(route("capture", "--kind", "note", "--summary", "Old signal", "--evidence", "old.txt"),
                         "external recipe runtime")


if __name__ == "__main__":
    unittest.main()
