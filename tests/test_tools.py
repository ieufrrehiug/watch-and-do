from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import community_memory as cm
import community_tools as ct
import scene_memory as sm


class ToolProvenance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.data = self.base / "personal"
        self.original, _ = cm.read(ROOT / "references/community-card.example.json")
        self.tools = {"software": [{"name": "Adobe Photoshop", "version": "26.1"}],
                      "skills": ["cutout-workflow"], "capabilities": ["subject-cutout"]}
        self.card = dict(self.original, tools=self.tools, check="Inspect hair edges on black and white backgrounds.")

    def cli(self, *args, module="community_memory", ok=True):
        command = [sys.executable, "-B", "-X", "utf8", str(ROOT / "scripts" / (module + ".py")),
                   "--data", str(self.data), *map(str, args)]
        run = subprocess.run(command, cwd=self.base, encoding="utf8", capture_output=True)
        if ok:
            self.assertEqual(run.returncode, 0, run.stderr)
            return json.loads(run.stdout)
        self.assertNotEqual(run.returncode, 0)
        return run.stderr

    def put(self, name, data):
        path = self.base / name
        path.write_text(json.dumps(data), encoding="utf8")
        return path

    def test_45_annotations_match_exact_legacy_content(self):
        seed, _ = cm.read(ROOT / "seeds/cards.json")
        index = ct.seed_profiles()["cards"]
        self.assertEqual(set(index), {cm.digest(c) for c in seed["cards"]})
        for c in seed["cards"]:
            self.assertNotIn("tools", c)
            tools = ct.tool_view(c, cm.digest, cm.public_text)["tools"]
            self.assertIsInstance(tools["software"], list)
            self.assertTrue(tools["capabilities"])
        ae = next(c for c in seed["cards"] if c["id"] == "ae-gdigrab-black-compositor")
        result = self.cli("community-preflight", "--installed-id", ae["id"])
        self.assertEqual(result["software"][0]["recorded_version"], "25.6.6x4")
        self.assertEqual(result["acceptance"]["check"], ae["check"])
        self.assertEqual(ct.tool_view(dict(ae, method="Changed method"), cm.digest, cm.public_text)["tools_source"], "unrecorded")
        self.assertFalse(self.data.exists())

    def test_draft_validation_and_legacy_pack_replay(self):
        raw = dict(self.card)
        raw.pop("tools")
        self.assertIn("New cards need tools", self.cli("community-draft", "--input", self.put("old.json", raw), "--out", self.base/"a.json", ok=False))
        note = dict(format="watch-and-do.review.v1", card=raw, card_sha256=cm.digest(raw),
                    reviewer="observer", environment="Desktop", outcome="reproduced", basis="frames", evidence="Legible.")
        pack = dict(format="watch-and-do.pack.v1", version=1, usage=cm.USAGE, maintainer="tester", reviews=[note])
        db = self.data / "learning" / "community.sqlite3"
        self.assertEqual(cm.install(db, pack)["status"], "installed")
        self.assertEqual(cm.install(db, pack)["status"], "already installed")
        self.assertEqual(cm.installed_card(db, raw["id"]), raw)
        row = next(r for r in cm.suggestions(db, "scene", "cover") if r["id"] == raw["id"])
        self.assertEqual(row["tools"], ct.unknown_tools())
        self.assertEqual(row["reproductions"][0]["tools"], ct.unknown_tools())
        self.assertEqual(note["card_sha256"], cm.digest(cm.installed_card(db, raw["id"])))

    def test_recorded_tool_fields_and_reviewer_do_not_share_histories(self):
        card_path = self.base / "draft.json"
        self.cli("community-draft", "--input", self.put("input.json", self.card), "--out", card_path)
        alt = dict(self.tools, software=[{"name": "GIMP", "version": "3.0"}], skills="none")
        review = self.base / "review.json"
        self.cli("community-review", "--card", card_path, "--reviewer", "observer", "--environment", "Desktop",
                 "--tools", self.put("review-tools.json", alt), "--outcome", "reproduced", "--basis", "frames",
                 "--evidence", "Inspected the cutout on both backgrounds.", "--out", review)
        note, _ = cm.read(review)
        self.assertEqual(note["tools"], alt)
        self.assertEqual(note["card"]["tools"], self.tools)
        self.assertEqual(note["card_sha256"], cm.digest(self.card))
        invalid = dict(self.tools, software=[{"name":"Photoshop", "version":"C:/Users/secret"}])
        with self.assertRaises(ValueError):
            cm.card(dict(self.card, tools=invalid))
        with self.assertRaises(ValueError):
            cm.card(dict(self.card, tools=dict(self.tools, skills=["../../private"])))

    def test_cutout_missing_program_and_skill_found_alternative_must_be_verified(self):
        observed = [{"kind":"software","name":"Adobe Photoshop","status":"missing","evidence":"Checked application list."},
                    {"kind":"skill","name":"cutout-workflow","status":"missing","evidence":"Checked active skills."},
                    {"kind":"software","name":"GIMP","status":"found","version":"3.0","evidence":"About dialog."},
                    {"kind":"skill","name":"other-mask-skill","status":"found","evidence":"Active session declared masking.",
                     "capabilities":["subject-cutout"]}]
        fallback_skill = self.base / "skills" / ".system" / "imagegen" / "SKILL.md"
        fallback_skill.parent.mkdir(parents=True)
        fallback_skill.write_text("Fixture for a discovered skill", encoding="utf8")
        result = self.cli("community-preflight","--card",self.put("cutout.json",self.card),"--inventory",self.put("local.json",observed),
                          "--skill-root",self.base / "skills")
        self.assertEqual(result["skills"][0]["status"], "missing")
        self.assertEqual(result["software"][0]["evidence"], "Checked application list.")
        self.assertEqual({r["name"] for r in result["alternatives"] if r["status"] == "found"}, {"GIMP","imagegen","other-mask-skill"})
        self.assertEqual(result["acceptance"], {"basis":"frames","check":self.card["check"],"status":"needs-local-test"})
        self.assertFalse(self.data.exists())
        observed[0].update(status="found", version="26.1")
        result = ct.preflight(self.tools, "inspect edges", "frames", observed, [])
        self.assertIn("Adobe Photoshop", [r["name"] for r in result["alternatives"]])

    def test_skill_files_versions_and_lookup_limits(self):
        self.tools["software"] = [{"name":"Python", "version":str(sys.version_info.major)}]
        skill = self.base / "skills" / "cutout-workflow" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("Local skill entry", encoding="utf8")
        output = ct.preflight(self.tools, "inspect", "frames", roots=[self.base/"skills"])
        self.assertEqual(output["route"], "try-original")
        self.assertEqual(output["skills"][0]["source"], "skill-file")
        self.assertEqual(output["software"][0]["version_check"], "matches-recorded-precision")
        self.tools["software"][0]["version"] = "0.1"
        output = ct.preflight(self.tools, "inspect", "frames", roots=[])
        self.assertEqual(output["software"][0]["version_check"], "different")
        self.assertEqual(output["skills"][0]["status"], "not-detected")
        with self.assertRaisesRegex(ValueError, "evidence"):
            ct.preflight(self.tools, "inspect", "frames", [{"kind":"skill","name":"x","status":"found"}], [])

    def test_windows_registration_matches_product_and_checks_actual_executable(self):
        import re
        pattern, _ = ct.WINDOWS_PRODUCTS["剪映专业版"]
        self.assertIsNone(re.fullmatch(pattern, "CapCut", re.I))
        ae_pattern, _ = ct.WINDOWS_PRODUCTS["adobe after effects"]
        self.assertIsNone(re.fullmatch(ae_pattern, "Adobe After Effects 2025 Language Pack", re.I))
        self.assertTrue(re.fullmatch(ae_pattern, "Adobe After Effects 2025", re.I))
        editor = self.base / "JianyingPro.exe"
        editor.touch()
        rows = [("剪映专业版","11.8.0.14778","",f'"{self.base / "uninst.exe"}",0')]
        with patch.object(ct,"registered_products", return_value=(rows,[])):
            verified = ct.windows_product("剪映专业版","11.8.0.14778")
            self.assertEqual((verified["status"],verified["version"]),("found","11.8.0.14778"))
            self.assertIn(str(editor), verified["evidence"])
            editor.unlink()
            self.assertEqual(ct.windows_product("剪映专业版",None)["status"], "registered")
        ae = self.base/"AfterFX.exe"
        ae.touch()
        rows = [("Adobe After Effects 2025","25.6.6","","")]
        with patch.object(ct,"registered_products",return_value=(rows,[f'"{ae}"'])):
            result = ct.windows_product("adobe after effects","25.6.6x4")
        self.assertEqual(result["source"],"windows-registry-and-file")
        setup = {"software":[{"name":"Adobe After Effects","version":"25.6.6x4"}],"skills":"none","capabilities":[]}
        with patch.object(ct,"observe",return_value=result):
            self.assertEqual(ct.preflight(setup,"inspect","frames")["software"][0]["version_check"],"unconfirmed")
        with patch.object(ct,"registered_products",return_value=([],[f'"{ae}" --argument'])):
            self.assertIsNone(ct.windows_product("adobe after effects",None))

    def test_personal_capture_and_old_revision_idempotence(self):
        self.put("frame.json", {"seen":"opaque edges"})
        raw = {"id":"example-scene", "project":"Private example", "status":"pass","verification":"frames",
               "method":"Inspect the image.", "check":"Inspect both backgrounds.", "topics":["baseline"],
               "evidence":["frame.json"]}
        old = sm.record(raw, self.base)
        encoded = json.dumps(old, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        db = self.data / "learning" / "scenes.sqlite3"
        db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("CREATE TABLE events(revision INTEGER PRIMARY KEY,id TEXT,identity TEXT UNIQUE,details TEXT)")
            conn.execute("INSERT INTO events VALUES (1,?,?,?)", (raw["id"], hashlib.sha256(encoded.encode()).hexdigest(), encoded))
        self.assertEqual(sm.learn(db, self.put("old.json",raw))["lessons"][0]["result"],"unchanged")
        unknown = sm.start(db,"封面",[],[])["lessons"][0]["tools"]
        self.assertEqual(unknown, ct.unknown_tools())
        seed = next(c for c in cm.bundled_seed()["cards"] if c["id"] == "waterfront-berthing")
        linked = {"format":"watch-and-do.local-seed-tools.v1", "links":{cm.digest(old):cm.digest(seed)}}
        sidecar = db.with_name("scene-tool-profiles.json")
        sidecar.write_text(json.dumps(linked), encoding="utf8")
        view = sm.start(db,"Three.js",[],[])["lessons"][0]
        self.assertIn("private evidence link", view["tools_source"])
        self.assertEqual(view["tools"]["skills"],["watch-and-do"])
        local = self.cli("community-preflight", "--scene-id", raw["id"])
        self.assertEqual(local["original_tools"], view["tools"])
        self.assertEqual(local["acceptance"]["check"], raw["check"])
        changed = dict(old, method="A different method")
        self.assertEqual(ct.local_tool_view(changed,ct.local_links(db),cm.digest,cm.public_text)["tools_source"], "unrecorded")
        row = dict(raw, tools=self.tools)
        self.assertEqual(sm.learn(db,self.put("local.json",row))["lessons"][0]["revision"],2)
        self.assertEqual(sm.start(db,"封面",[],[])["lessons"][0]["tools"],self.tools)
        result = self.cli("community-preflight","--scene-id",raw["id"])
        self.assertEqual(result["original_tools"], self.tools)
        self.assertEqual(result["acceptance"]["check"], raw["check"])
