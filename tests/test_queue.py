"""Exercise the idle queue with a local transport. Never sends a real Issue."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import community_memory as cm
import community_queue as q


class LocalIssues:
    def __init__(self):
        self.remote = {}
        self.posts = []
        self.finds = []

    def find(self, data, sha):
        self.finds.append(sha)
        return self.remote.get(sha)

    def create(self, data, sha):
        self.posts.append(sha)
        self.remote[sha] = 100 + len(self.posts)
        return self.remote[sha]


class QueueTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.path = Path(root.name) / "learning" / "community.sqlite3"
        self.card = json.loads((ROOT/"references/community-card.example.json").read_text(encoding="utf8"))
        self.remote = LocalIssues()
        self.now = time.time()+2
        self.never_launch = patch.dict(os.environ, WATCH_AND_DO_QUEUE_WORKER="off")
        self.never_launch.start()
        self.addCleanup(self.never_launch.stop)

    def enqueue(self, count=1):
        cm.sharing(self.path, "auto")
        for i in range(count):
            cm.preview_share(self.path, dict(self.card, id=f"card-{i}"), None)

    def tick(self, idle=lambda: True, **kwargs):
        return q.tick(self.path, idle=idle, transport=self.remote, clock=lambda: self.now, **kwargs)

    def test_three_or_oldest_and_unknown_idle(self):
        self.enqueue(2)
        self.assertEqual(self.tick()["submitted"], 0)
        self.now += 24*3600
        self.assertEqual(self.tick(idle=lambda: None)["submitted"], 0)
        self.assertFalse(self.remote.finds)
        self.assertEqual(self.tick()["submitted"], 2)
        self.enqueue(5)  # two repeated SHA values retain their receipts
        self.assertEqual(self.tick(idle=lambda: False)["submitted"], 0)
        self.assertEqual(self.tick()["submitted"], 3)
        self.assertEqual(len(q.status(self.path)["submitted"]), 5)

    def test_mode_switch_and_skip_delete_only_unsent(self):
        self.enqueue(3)
        self.tick()
        self.enqueue(4)
        cm.sharing(self.path, "review")
        self.assertEqual(q.status(self.path)["pending"], [])
        preview = cm.preview_share(self.path, self.card, None)
        self.assertEqual(preview["queue_status"], "awaiting-approval")
        another = dict(self.card, id="new-id")
        other = cm.preview_share(self.path, another, None)
        cm.sharing(self.path, "review")  # same setting keeps exact approvals
        cm.preview_share(self.path, self.card, preview["sha256"])
        cm.preview_share(self.path, another, other["sha256"])
        cm.sharing(self.path, "invited")
        self.assertEqual(q.status(self.path)["pending"], [])
        self.assertEqual(len(q.status(self.path)["submitted"]), 3)
        self.assertFalse(cm.sharing(self.path, begin=True)["ask_now"])
        self.assertEqual(self.tick(batch_size=1)["submitted"], 0)

    def test_review_upgrade_current_content_and_edit_invalidates_older_preview(self):
        self.path.parent.mkdir()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE sharing_choice(slot INTEGER PRIMARY KEY, choice TEXT)")
            db.execute("INSERT INTO sharing_choice VALUES (1,'review')")
            db.execute("CREATE TABLE pending_share(slot INTEGER PRIMARY KEY,digest TEXT)")
            db.execute("INSERT INTO pending_share VALUES (1,?)", (cm.digest(self.card),))
        self.assertEqual(cm.preview_share(self.path, self.card, cm.digest(self.card))["queue_status"], "queued")
        first = cm.preview_share(self.path, self.card, None)
        revised = dict(self.card, evidence="New observation")
        second = cm.preview_share(self.path, revised, None)
        with self.assertRaisesRegex(ValueError, "new preview"):
            cm.preview_share(self.path, self.card, first["sha256"])
        cm.preview_share(self.path, revised, second["sha256"])
        self.assertEqual(len(q.status(self.path)["pending"]), 2)

    def test_review_group_persists_and_selected_mature_cards_do_not_restart_the_clock(self):
        cm.sharing(self.path, "review")
        drafts = [dict(self.card, id=f"draft-{i}") for i in range(3)]
        shas = list(map(cm.digest, drafts))
        cm.preview_share(self.path, drafts[0], None)
        self.assertFalse(q.review_queue(self.path, [], [], False, 3, 24)["drafts"])
        early = q.review_queue(self.path, [], [], True, 3, 24)
        self.assertEqual(early["drafts"], [{"sha256":shas[0], "payload":drafts[0]}])
        for data in drafts[1:]:
            cm.preview_share(self.path, data, None)
        self.assertEqual(q.status(self.path)["awaiting_approval"], 3)
        self.assertEqual(self.tick(batch_size=1)["submitted"], 0)
        self.assertEqual(len(q.review_queue(self.path, [], [], False, 3, 24)["drafts"]), 3)
        with self.assertRaisesRegex(ValueError, "new preview"):
            q.review_queue(self.path, [shas[0], "stale"], [], False, 3, 24)
        result = q.review_queue(self.path, [shas[0]], [shas[2]], False, 3, 24)
        self.assertEqual(result["approved"], shas[:1])
        self.assertEqual(result["skipped"], shas[2:])
        self.assertEqual(result["drafts"], [{"sha256":shas[1], "payload":drafts[1]}])
        self.assertEqual(self.tick()["submitted"], 1)
        # Identical data already sent should never reappear for review.
        self.assertEqual(cm.preview_share(self.path, drafts[0], None)["queue_status"], "already-submitted")
        self.assertEqual(q.status(self.path)["awaiting_approval"], 1)

    def test_review_age_survives_repeated_preview_and_single_approval(self):
        cm.sharing(self.path, "review")
        preview = cm.preview_share(self.path, self.card, None)
        with q.transaction(self.path) as db:
            db.execute("UPDATE share_previews SET created=created-86401")
        cm.preview_share(self.path, self.card, None)
        result = q.review_queue(self.path, [], [], False, 3, 24)
        self.assertEqual(result["drafts"][0]["sha256"], preview["sha256"])
        cm.preview_share(self.path, self.card, preview["sha256"])
        self.assertEqual(self.tick()["submitted"], 1)

    def test_idle_and_consent_checked_again_after_lookup(self):
        self.enqueue(3)
        idle = Mock(side_effect=[True, True, False])
        self.assertEqual(self.tick(idle=idle)["submitted"], 0)
        self.assertEqual(self.remote.posts, [])
        def revoke(data, sha):
            cm.sharing(self.path, "private")
            cm.sharing(self.path, "auto")
            return None
        self.remote.find = revoke
        self.assertEqual(self.tick()["submitted"], 0)
        self.assertEqual(self.remote.posts, [])

    def test_two_concurrent_workers_no_duplicate(self):
        self.enqueue()
        arrived, resume = threading.Event(), threading.Event()
        find = self.remote.find
        def paused(data, sha):
            arrived.set()
            if not resume.wait(5):
                raise AssertionError("second worker did not finish")
            return find(data, sha)
        self.remote.find = paused
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.tick, batch_size=1)
            self.assertTrue(arrived.wait(5))
            self.assertEqual(self.tick(batch_size=1)["submitted"], 0)
            resume.set()
            self.assertEqual(first.result()["submitted"], 1)
        self.assertEqual(len(self.remote.posts), 1)

    def test_failed_get_backoff_and_retry_after_partial_batch(self):
        self.enqueue(3)
        with patch.object(self.remote, "find", side_effect=[q.DeliveryError("offline"), None, None]):
            self.assertEqual(self.tick()["submitted"], 2)
        self.assertEqual(self.tick()["submitted"], 0)
        self.now += 61
        self.assertEqual(self.tick()["submitted"], 1)
        self.assertEqual(len(self.remote.posts), 3)

    def test_lost_create_receipt_reconciles_without_posting_twice(self):
        self.enqueue()
        create = self.remote.create
        def lost(data, sha):
            create(data, sha)
            raise q.DeliveryError("github-unreachable", uncertain=True)
        with patch.object(self.remote, "create", side_effect=lost):
            result = self.tick(batch_size=1)
        self.assertEqual(result["deferred"], 1)
        self.assertTrue(q.status(self.path)["pending"][0]["reconciling"])
        self.now += 61
        self.assertEqual(self.tick()["submitted"], 1)
        self.assertEqual(len(self.remote.posts), 1)

    def test_ambiguous_post_and_revocation_keep_no_payload_and_no_blind_retry(self):
        self.enqueue()
        with patch.object(self.remote, "create", side_effect=q.DeliveryError("timeout", uncertain=True)):
            self.tick(batch_size=1)
        cm.sharing(self.path, "private")
        self.assertEqual(q.status(self.path)["pending"], [])
        self.enqueue()
        self.now += 61
        self.assertEqual(self.tick(batch_size=1)["deferred"], 1)
        self.assertEqual(self.remote.posts, [])
        row = q.status(self.path)["pending"][0]
        self.assertEqual(row["last_problem"], "awaiting-github-receipt")
        q.run_command(self.path, argparse.Namespace(command="community-queue-retry", sha256=row["sha256"]))
        self.assertEqual(self.tick()["submitted"], 1)

    def test_gh_exact_public_issue_reconciliation_and_post_body(self):
        api = Mock()
        api.side_effect = [
            {"login": self.card["author"], "type": "User"},
            [{"number": 3, "user": {"login": self.card["author"], "type": "User"}, "body":"different"}]*100,
            [{"number": 8, "user": {"login": self.card["author"], "type": "User"},
              "body": "```json\n" + json.dumps(self.card) + "\n```"}],
            {"number": 15},
        ]
        gh = q.GitHubIssues()
        with patch.object(gh, "api", api):
            self.assertEqual(gh.find(self.card, cm.digest(self.card)), 8)
            self.assertEqual(gh.create(self.card, cm.digest(self.card)), 15)
        endpoint, payload = api.call_args.args
        self.assertEqual(endpoint, f"repos/{cm.REPO}/issues")
        cm.posted({"user": {"type": "User", "login": self.card["author"]}, "body": payload["body"]},
                  self.card, self.card["author"])
        with patch.object(gh, "api", return_value={"type":"User","login":"other"}), self.assertRaises(q.DeliveryError):
            gh.find(self.card, cm.digest(self.card))

    def test_gh_subprocess_noninteractive_with_local_standin(self):
        standin = self.path.parents[1] / "gh_standin.py"
        standin.write_text("""import json, os, sys
assert sys.argv[1:4] == ['api','--hostname','github.com']
assert os.environ['GH_PROMPT_DISABLED'] == '1' and os.environ['GIT_TERMINAL_PROMPT'] == '0'
method, endpoint = sys.argv[5:7]
if endpoint == 'user':
    print(json.dumps({'type':'User','login':'example-author'}))
elif method == 'GET':
    assert endpoint.startswith('repos/ieufrrehiug/watch-and-do/issues?state=all&creator=example-author')
    print('[]')
else:
    assert endpoint == 'repos/ieufrrehiug/watch-and-do/issues'
    assert sys.argv[-2:] == ['--input','-']
    payload = json.loads(sys.stdin.buffer.read())
    assert 'watch-and-do sha256' in payload['body'] and '经验' in payload['title']
    print('{"number":42}')
""", encoding="utf8")
        run = subprocess.run
        def fake_gh(args, **kwargs):
            self.assertEqual(args[0], "gh")
            return run([sys.executable, "-X", "utf8", str(standin), *args[1:]], **kwargs)
        self.enqueue()
        with patch.object(q.subprocess, "run", side_effect=fake_gh):
            result = q.tick(self.path, idle=lambda: True, transport=q.GitHubIssues(), batch_size=1)
        self.assertEqual(result["submitted"], 1)
        self.assertEqual(q.status(self.path)["submitted"][0]["issue"], 42)

    def test_worker_launcher_deduplicates_and_cli_resumes_backlog(self):
        self.enqueue()
        with patch.dict(os.environ, WATCH_AND_DO_QUEUE_WORKER="on"), patch.object(q, "idle_supported", return_value=True), \
                patch.object(q.shutil, "which", return_value="gh"), patch.object(q.subprocess, "Popen") as spawn:
            q.wake_worker(self.path)
            q.wake_worker(self.path)
            self.assertEqual(spawn.call_count, 1)
            self.assertIn("community-queue-worker", spawn.call_args.args[0])
            ticket = spawn.call_args.args[0][-1]
            self.assertTrue(q.reserve_worker(self.path, ticket))
            args = argparse.Namespace(command="community-queue-worker", worker_ticket=ticket, poll_seconds=60,
                                      idle_seconds=300, batch_size=1, max_age_hours=24)
            with patch.object(q, "idle_seconds", return_value=301), patch.object(q, "GitHubIssues", return_value=self.remote):
                self.assertEqual(q.run_command(self.path, args)["state"], "stopped")
        self.assertEqual(len(q.status(self.path)["submitted"]), 1)
        run = subprocess.run([sys.executable, "-B",str(ROOT/"scripts/community_memory.py"),
                              "--data", str(self.path.parents[1]), "community-queue"], capture_output=True,
                             check=True, encoding="utf8", env=dict(os.environ, PYTHONUTF8="1"))
        self.assertEqual(json.loads(run.stdout)["pending"], [])

    def test_detached_process_reopens_the_database_and_renews_its_lease(self):
        self.enqueue()  # Below both default thresholds, so even an idle desktop cannot send.
        children = []
        initial = []
        popen = subprocess.Popen

        def launch(args, **kwargs):
            with q.transaction(self.path) as db:
                initial.append(db.execute("SELECT expires FROM share_worker").fetchone()[0])
            children.append(popen(args, **kwargs))
            return children[-1]

        with patch.dict(os.environ, WATCH_AND_DO_QUEUE_WORKER="on"), patch.object(q, "idle_supported", return_value=True), \
                patch.object(q.shutil, "which", return_value="gh"), patch.object(q.subprocess, "Popen", side_effect=launch):
            q.wake_worker(self.path)
        self.assertEqual(len(children), 1)
        child = children[0]
        try:
            deadline = time.monotonic()+5
            while time.monotonic() < deadline:
                with q.transaction(self.path) as db:
                    renewed = db.execute("SELECT expires FROM share_worker").fetchone()[0]
                if renewed > initial[0]:
                    break
                self.assertIsNone(child.poll())
                time.sleep(0.02)
            self.assertGreater(renewed, initial[0])
            self.assertEqual(len(q.status(self.path)["pending"]), 1)
        finally:
            child.terminate()
            child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
