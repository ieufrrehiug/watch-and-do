"""Run from an extracted public checkout with Python 3.11+ and no extra packages."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import base64
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import community_memory as cm


class PublicPilot(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data = Path(temp.name) / "empty-user"

    def run_cli(self, name, *args):
        env = dict(os.environ, WATCH_AND_DO_DATA=str(self.data), PYTHONUTF8="1", PYTHONPATH="")
        res = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / name), *args],
                             cwd=self.data.parent, env=env, check=True, capture_output=True, encoding="utf8")
        return json.loads(res.stdout)

    def recall(self, key, query, task="scene"):
        rows = self.run_cli("community_memory.py", "community-find", "--task", task, "--brief", query)
        card = next(row for row in rows if row["id"] == key)
        self.assertEqual((card["source"], card["reproductions"]), ("maintainer-seed", []))
        self.assertTrue(card["method"] and card["check"] and card["matched"])
        self.assertFalse(self.data.exists())
        return card

    def test_sharing_invitation_and_reversible_per_item_choice(self):
        db = self.data / "learning" / "community.sqlite3"
        info = self.run_cli("community_memory.py", "community-sharing")
        self.assertEqual(info["choice"], "new")
        self.assertFalse(self.data.exists())
        with ThreadPoolExecutor(2) as workers:
            invitations = list(workers.map(lambda _: cm.sharing(db, begin=True), range(2)))
        self.assertEqual(sum(i["ask_now"] for i in invitations), 1)
        item = json.loads((ROOT / "references/community-card.example.json").read_text(encoding="utf8"))
        with self.assertRaisesRegex(ValueError, "Sharing is off"):
            cm.preview_share(db, item, None)
        cm.sharing(db, "private")
        self.assertFalse(cm.sharing(db, begin=True)["ask_now"])
        rows = self.run_cli("community_memory.py", "community-find", "--task", "scene", "--brief", "摆长")
        self.assertTrue(rows)
        cm.sharing(db, "review")
        preview = cm.preview_share(db, item, None)
        self.assertFalse(preview["ready"])
        with self.assertRaisesRegex(ValueError, "new preview"):
            cm.preview_share(db, dict(item, evidence="Different observation"), preview["sha256"])
        cm.sharing(db, "private")
        cm.sharing(db, "review")
        with self.assertRaisesRegex(ValueError, "new preview"):
            cm.preview_share(db, item, preview["sha256"])
        fresh = cm.preview_share(db, item, None)
        self.assertTrue(cm.preview_share(db, item, fresh["sha256"])["ready"])
        with self.assertRaisesRegex(ValueError, "new preview"):
            cm.preview_share(db, item, fresh["sha256"])

    def test_official_review_binds_real_accounts_content_and_owner_evidence(self):
        item = json.loads((ROOT/"references/community-card.example.json").read_text(encoding="utf8"))
        note = dict(format="watch-and-do.review.v1", card=item, card_sha256=cm.digest(item),
                    reviewer="peer", environment="Desktop", outcome="reproduced", basis="frames", evidence="Both ends fit.")
        sha = cm.digest(note)
        def issue(data, name, uid):
            return {"body": "### JSON\n\n```json\n"+json.dumps(data)+"\n```\n\n### Context\nOK",
                    "user": {"type":"User", "login": name, "id": uid}}
        records = {"issues/8":issue(note, "peer", 22), "issues/4":issue(item, item["author"], 11),
                   "issues/comments/33":{"issue_url":"https://api.github.com/repos/"+cm.REPO+"/issues/8",
                                        "user":{"type":"User", "id":cm.OWNER_ID},
                                        "body":f"watch-and-do approve {sha} 4 https://example.org/evidence"}}
        pack = {"format":"watch-and-do.pack.v2","usage":cm.USAGE,"maintainer":cm.OWNER,"version":1,
                "reviews":[note],"approvals":{sha:"8:33"}}
        cm.verify_official(cm.release(pack), records.__getitem__)
        for key, attr, value in (("issues/8","user",{"type":"User","id":11,"login":"peer"}),
                                  ("issues/8","body","different report"),
                                  ("issues/comments/33","user",{"type":"User","id":9}),
                                  ("issues/comments/33","body","looks fine")):
            changed = dict(records, **{key:dict(records[key], **{attr:value})})
            with self.subTest(key=key, attr=attr), self.assertRaises(ValueError):
                cm.verify_official(pack, changed.__getitem__)
        db = self.data / "community.sqlite3"
        def listing(content):
            return {"encoding":"base64","content":base64.b64encode(cm.canonical(content)).decode()}
        records["contents/community-packs/v1.json?ref=main"] = listing(dict(pack, reviews=[], approvals={}))
        with patch.object(cm, "github", side_effect=records.__getitem__), self.assertRaisesRegex(ValueError,"differs"):
            cm.install(db, pack)
        self.assertFalse(db.exists())
        records["contents/community-packs/v1.json?ref=main"] = listing(pack)
        with patch.object(cm, "github", side_effect=records.__getitem__):
            self.assertEqual(cm.install(db, pack)["status"], "installed")

    def test_fixed_step_with_different_frame_rates(self):
        self.recall("motion-study-second-step", "帧率变化时弹簧回位不一致")
        def simulate(fps, fixed):
            pos, vel = 2.0, -0.7
            rate = 360 if fixed else fps
            for frame in range(fps):
                for step in range((frame+1)*rate//fps - frame*rate//fps):
                    vel += (-17*pos - 2*vel) / rate
                    pos += vel / rate
            return pos
        self.assertGreater(abs(simulate(24, False) - simulate(90, False)), 0.005)
        self.assertEqual(simulate(24, True), simulate(90, True))

    def test_two_link_arm_inside_and_beyond_reach(self):
        self.recall("motion-study-second-ik", "骨骼 反向运动学")
        a, b = 63.0, 41.0
        for target in (5.0, 57.0, 140.0):
            distance = min(a+b, max(abs(a-b), target))
            x = (a*a - b*b + distance*distance) / (2*distance)
            height = math.sqrt(max(0, a*a-x*x))
            for y in (height, -height):
                self.assertAlmostEqual(math.hypot(x, y), a)
                self.assertAlmostEqual(math.hypot(distance-x, y), b)
            if target == 57.0:
                self.assertGreater(2*height, 1)
        self.assertEqual(distance, a+b)

    def test_glider_with_new_start_position(self):
        self.recall("motion-library-life", "细胞 滑翔机")
        start = {(9,4),(10,5),(8,6),(9,6),(10,6)}
        cells = start
        for _ in range(4):
            counts = Counter((x+dx, y+dy) for x,y in cells for dx in (-1,0,1) for dy in (-1,0,1) if dx or dy)
            cells = {p for p,n in counts.items() if n == 3 or (n == 2 and p in cells)}
        self.assertEqual(cells, {(x+1,y+1) for x,y in start})

    def test_pendulum_period_by_numerical_crossings(self):
        self.recall("motion-study-second-pendulum", "改变摆长后周期怎样变化")
        def period(length):
            angle, speed, down = 0.07, 0.0, []
            for i in range(14000):
                old = angle
                speed -= 9.81/length * math.sin(angle) * 0.001
                angle += speed * 0.001
                if old > 0 >= angle:
                    down.append(i*0.001)
                if len(down) == 2:
                    return down[1]-down[0]
            self.fail("No complete cycle")
        self.assertAlmostEqual(period(1.6)/period(0.4), 2.0, delta=0.003)

    def test_staggered_text_on_a_different_timeline(self):
        self.recall("motion-library-letters", "逐字入场")
        def opacity(t, i, gap):
            return max(0, min(1, (t-i*gap)/180))
        self.assertEqual(opacity(250, 5, 65), 0)
        self.assertEqual(opacity(5*65+180, 5, 65), 1)
        self.assertGreater(opacity(250, 5, 28), 0.5)

    def test_scene_entry_video_pitfall_and_local_opt_out(self):
        rows = self.run_cli("scene_memory.py", "scene-start", "--brief", "微缩建筑 手机选层")
        self.assertIn("isometric-cutaway-floor-focus", [c["id"] for c in rows["community_suggestions"]])
        key = "ae-gdigrab-black-compositor"
        self.assertEqual(self.recall(key, "AE 合成窗口 录屏黑屏", "video")["kind"], "pitfall")
        self.run_cli("community_memory.py", "community-disable", "--id", key)
        found = self.run_cli("community_memory.py", "community-find", "--task", "video", "--brief", "AE 录屏")
        self.assertNotIn(key, [r["id"] for r in found])


if __name__ == "__main__":
    unittest.main(verbosity=2)
