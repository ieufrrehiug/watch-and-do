"""Local consent-bound queue and idle GitHub Issue delivery."""
from contextlib import closing, contextmanager
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid


@contextmanager
def transaction(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=10)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        yield db


def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS share_queue (
        digest TEXT PRIMARY KEY, payload TEXT, consent TEXT, created REAL NOT NULL,
        ready INTEGER DEFAULT 0, next_try REAL DEFAULT 0, attempts INTEGER DEFAULT 0,
        lease TEXT, expires REAL DEFAULT 0, uncertain INTEGER DEFAULT 0, issue INTEGER,
        problem TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS share_previews
        (item_key TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
         created REAL NOT NULL, ready INTEGER DEFAULT 0)""")
    db.execute("CREATE TABLE IF NOT EXISTS share_worker (slot INTEGER PRIMARY KEY, ticket TEXT, expires REAL)")


def preview_key(data):
    item = data.get("card", data)
    return json.dumps([item["id"], item["author"].lower(), data.get("reviewer", "").lower()])


def withdraw(db):
    schema(db)
    db.execute("DELETE FROM share_previews")
    # An uncertain, previously started POST may have reached GitHub. Keep its
    # fingerprint for reconciliation if the user later reauthorizes this content.
    db.execute("DELETE FROM share_queue WHERE issue IS NULL AND uncertain=0")
    db.execute("UPDATE share_queue SET payload=NULL, consent=NULL, lease=NULL, expires=0 WHERE issue IS NULL")


def save_preview(db, key, sha, body):
    db.execute("""INSERT INTO share_previews (item_key,digest,payload,created) VALUES(?,?,?,?)
        ON CONFLICT(item_key) DO UPDATE SET digest=excluded.digest, payload=excluded.payload,
        created=excluded.created,ready=0 WHERE share_previews.digest<>excluded.digest""", (key,sha,body,time.time()))


def mature_previews(db, batch_size=3, max_age_hours=24):
    count, oldest = db.execute("SELECT COUNT(*),MIN(created) FROM share_previews WHERE ready=0").fetchone()
    if count and (count >= batch_size or oldest + max_age_hours*3600 <= time.time()):
        db.execute("UPDATE share_previews SET ready=1 WHERE ready=0")


def review_queue(path, selected, skipped, show_all, batch_size, max_age_hours):
    from community_memory import REPO, card, digest, reviewed
    result = {"destination": f"https://github.com/{REPO}/issues", "drafts": [], "approved": [], "skipped": []}
    if not path.is_file() and not (selected or skipped):
        return result
    if len(set(selected + skipped)) != len(selected + skipped):
        raise ValueError("Select each digest once")
    with transaction(path) as db:
        if not table_exists(db) or not db.execute("SELECT 1 FROM sharing_choice WHERE slot=1 AND choice='review'").fetchone():
            if selected or skipped:
                raise ValueError("No current review for these items")
            return result
        mature_previews(db, batch_size, max_age_hours)
        for sha in selected + skipped:
            row = db.execute("SELECT * FROM share_previews WHERE digest=?", (sha,)).fetchone()
            if not row:
                raise ValueError("Content or sharing choice changed; show a new preview")
            db.execute("DELETE FROM share_previews WHERE digest=?", (sha,))
            if sha in selected:
                data = json.loads(row["payload"])
                (reviewed if "reviewer" in data else card)(data)
                if digest(data) != sha:
                    raise ValueError("Content changed; show a new preview")
                enqueue(db, sha, row["payload"], "review", row["created"], row["ready"])
                result["approved"].append(sha)
            else:
                result["skipped"].append(sha)
        for row in db.execute("SELECT digest,payload FROM share_previews WHERE ready=1 OR ? ORDER BY created,digest", (show_all,)):
            result["drafts"].append({"sha256": row["digest"], "payload": json.loads(row["payload"])})
    return result


def enqueue(db, sha, body, choice, created=None, ready=0):
    db.execute("""INSERT INTO share_queue (digest,payload,consent,created,ready) VALUES(?,?,?,?,?)
        ON CONFLICT(digest) DO UPDATE SET payload=excluded.payload, consent=excluded.consent,
        created=excluded.created, ready=excluded.ready, next_try=0, attempts=0, problem=NULL
        WHERE share_queue.payload IS NULL AND share_queue.issue IS NULL""",
               (sha, body, choice, time.time() if created is None else created, ready))
    issue = db.execute("SELECT issue FROM share_queue WHERE digest=?", (sha,)).fetchone()[0]
    return "already-submitted" if issue else "queued"


def table_exists(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='share_queue'").fetchone()


def status(path):
    pending, sent = [], []
    awaiting = 0
    if path.is_file():
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            if table_exists(db):
                awaiting = db.execute("SELECT COUNT(*) FROM share_previews").fetchone()[0]
                for sha, consent, created, uncertain, problem, issue, payload in db.execute(
                        """SELECT digest,consent,created,uncertain,problem,issue,payload IS NOT NULL
                           FROM share_queue ORDER BY created,digest"""):
                    if issue:
                        sent.append({"sha256": sha, "issue": issue})
                    elif payload:
                        pending.append({"sha256": sha, "choice": consent, "queued_at": created,
                                        "reconciling": bool(uncertain), "last_problem": problem})
    if os.environ.get("WATCH_AND_DO_QUEUE_WORKER") == "off":
        worker = "disabled"
    elif not shutil.which("gh"):
        worker = "gh-unavailable"
    elif not idle_supported():
        worker = "idle-signal-unavailable"
    else:
        worker = "available"
    return {"pending": pending, "awaiting_approval": awaiting, "submitted": sent, "automatic_worker": worker}


def idle_supported():
    return (sys.platform in ("win32", "darwin") or
            (os.environ.get("XDG_SESSION_TYPE") == "x11" and bool(shutil.which("xprintidle"))))


def idle_seconds():
    """Time since input in the logged-in desktop session, or None when unknown."""
    try:
        if sys.platform == "win32":
            from ctypes import wintypes

            class LastInput(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

            info = LastInput()
            info.cbSize = ctypes.sizeof(info)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xffffffff) / 1000
        elif sys.platform == "darwin":
            result = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-d", "1"], check=True,
                                    capture_output=True, timeout=5)
            match = re.search(rb'"HIDIdleTime"\s*=\s*(\d+)', result.stdout)
            if match:
                return int(match[1]) / 1e9
        elif os.environ.get("XDG_SESSION_TYPE") == "x11":
            result = subprocess.run(["xprintidle"], check=True, capture_output=True, timeout=5)
            return int(result.stdout.strip()) / 1000
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


class DeliveryError(Exception):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


class GitHubIssues:
    def __init__(self):
        from community_memory import REPO
        self.repo = REPO

    def api(self, resource, payload=None):
        args = ["gh", "api", "--hostname", "github.com", "--method", "POST" if payload else "GET", resource]
        if payload:
            args.extend(["--input", "-"])
        try:
            result = subprocess.run(args, input=json.dumps(payload, ensure_ascii=False) if payload else "",
                                    encoding="utf8", errors="replace", capture_output=True, timeout=30,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                    env=dict(os.environ, GH_PROMPT_DISABLED="1", GH_PAGER="cat",
                                             GH_NO_UPDATE_NOTIFIER="1", GIT_TERMINAL_PROMPT="0"))
        except FileNotFoundError as error:
            raise DeliveryError("gh-unavailable") from error
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DeliveryError("github-unreachable", uncertain=bool(payload)) from error
        if result.returncode:
            # A confirmed rejection can be retried. A lost POST response must
            # be reconciled even when gh itself could not identify the failure.
            refused = re.search(r"\(HTTP (?:400|401|403|404|410|422|429)\)", result.stderr)
            raise DeliveryError("github-refused-or-unavailable", uncertain=bool(payload and not refused))
        try:
            return json.loads(result.stdout)
        except ValueError as error:
            raise DeliveryError("invalid-github-response", uncertain=bool(payload)) from error

    def find(self, data, sha):
        from community_memory import posted
        actor = data.get("reviewer", data.get("author"))
        me = self.api("user")
        if not isinstance(me, dict) or me.get("type") != "User" or str(me.get("login")).lower() != actor.lower():
            raise DeliveryError("github-author-mismatch")
        page = 1
        while True:
            rows = self.api(f"repos/{self.repo}/issues?state=all&creator={actor}&per_page=100&page={page}")
            if not isinstance(rows, list):
                raise DeliveryError("invalid-issue-list")
            for issue in rows:
                try:
                    posted(issue, data, actor)
                except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
                    continue
                if type(issue.get("number")) is int and issue["number"] > 0:
                    return issue["number"]
            if len(rows) < 100:
                return None
            page += 1

    def create(self, data, sha):
        is_review = "reviewer" in data
        key = data.get("card", data)["id"]
        title = ("[复现] " if is_review else "[经验] ") + key
        body = (f"<!-- watch-and-do sha256 {sha} -->\n\n" +
                ("### 独立复现记录" if is_review else "### 经验卡") +
                "\n\n```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```")
        issue = self.api(f"repos/{self.repo}/issues", {"title": title, "body": body})
        if not isinstance(issue, dict) or type(issue.get("number")) is not int or issue["number"] <= 0:
            raise DeliveryError("missing-github-receipt", uncertain=True)
        return issue["number"]


ELIGIBLE = """payload IS NOT NULL AND issue IS NULL
    AND consent IN ('auto','review') AND consent=(SELECT choice FROM sharing_choice WHERE slot=1)"""


def worklist(path, now, batch_size, age):
    with transaction(path) as db:
        if not table_exists(db):
            return []
        count, oldest = db.execute(f"SELECT COUNT(*), MIN(created) FROM share_queue WHERE {ELIGIBLE} AND ready=0").fetchone()
        if count and (count >= batch_size or oldest + age <= now):
            db.execute(f"UPDATE share_queue SET ready=1 WHERE {ELIGIBLE} AND ready=0")
        return [r[0] for r in db.execute(f"""SELECT digest FROM share_queue WHERE {ELIGIBLE}
                   AND ready=1 AND next_try<=? AND expires<=? ORDER BY created,digest""", (now, now))]


def claim(path, sha, now):
    with transaction(path) as db:
        token = uuid.uuid4().hex
        owned = db.execute(f"""UPDATE share_queue SET lease=?, expires=?, attempts=attempts+1
            WHERE digest=? AND {ELIGIBLE} AND ready=1 AND next_try<=? AND expires<=?""",
                           (token, now+120, sha, now, now)).rowcount
        if not owned:
            return None, None
        row = db.execute("SELECT payload,uncertain,attempts FROM share_queue WHERE digest=?", (sha,)).fetchone()
        return token, row


def deliver(path, sha, transport, idle, clock):
    from community_memory import card, digest, reviewed
    token, row = claim(path, sha, clock())
    if not row:
        return "skipped"
    uncertain = bool(row["uncertain"])
    try:
        try:
            data = json.loads(row["payload"])
            (reviewed if "reviewer" in data else card)(data)
            if digest(data) != sha:
                raise ValueError("digest mismatch")
        except (ValueError, TypeError, KeyError) as error:
            raise DeliveryError("invalid-local-payload") from error
        issue = transport.find(data, sha)
        if not issue:
            if uncertain:
                raise DeliveryError("awaiting-github-receipt", uncertain=True)
            if not idle():
                with transaction(path) as db:
                    db.execute("UPDATE share_queue SET lease=NULL,expires=0 WHERE digest=? AND lease=?", (sha, token))
                return "busy"
            with transaction(path) as db:
                now = clock()
                # Commit before POST, so a killed worker can never blindly
                # repeat one. Revocation during lookup invalidates this lease.
                own = db.execute(f"""UPDATE share_queue SET uncertain=1,expires=?
                    WHERE digest=? AND lease=? AND {ELIGIBLE}""", (now+120, sha, token)).rowcount
            if not own:
                return "skipped"
            issue = transport.create(data, sha)
        with transaction(path) as db:
            # If consent was withdrawn during POST, retain only its receipt.
            db.execute("""UPDATE share_queue SET issue=?,payload=NULL,consent=NULL,uncertain=0,
                lease=NULL,expires=0,problem=NULL WHERE digest=? AND (lease=? OR uncertain=1)""", (issue, sha, token))
        return "submitted"
    except DeliveryError as error:
        delay = min(3600, 60 * 2 ** min(row["attempts"] - 1, 6))
        with transaction(path) as db:
            db.execute("""UPDATE share_queue SET uncertain=?, problem=?, lease=NULL, expires=0, next_try=?
                WHERE digest=? AND lease=?""", (uncertain or error.uncertain, str(error), clock()+delay, sha, token))
        return "deferred"


def tick(path, *, idle, batch_size=3, max_age_hours=24, transport=None, clock=time.time):
    counts = {"submitted": 0, "deferred": 0, "skipped": 0}
    if not path.is_file() or not idle():
        return dict(state="inactive", **counts)
    for sha in worklist(path, clock(), batch_size, max_age_hours*3600):
        if not idle():
            break
        outcome = deliver(path, sha, transport or GitHubIssues(), idle, clock)
        if outcome == "busy":
            break
        counts[outcome] += 1
    return dict(state="checked", **counts)


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def add_commands(commands):
    commands.add_parser("community-queue", help="List local pending fingerprints and submitted issue numbers")
    review = commands.add_parser("community-queue-review", help="Show a due group of local drafts or act on an exact selection")
    review.add_argument("--all", action="store_true", help="Show drafts before the group is due")
    review.add_argument("--approve", action="append", default=[], metavar="SHA256")
    review.add_argument("--skip", action="append", default=[], metavar="SHA256")
    retry = commands.add_parser("community-queue-retry", help="Rearm an uncertain POST after checking GitHub for its exact card")
    retry.add_argument("--sha256", required=True)
    one = commands.add_parser("community-queue-tick", help="Run once from an idle/maintenance hook")
    one.add_argument("--host-idle", action="store_true", help="Host guarantees idle for the duration of this callback")
    worker = commands.add_parser("community-queue-worker", help="Wait for desktop inactivity and exit after draining")
    worker.add_argument("--poll-seconds", type=positive, default=60)
    worker.add_argument("--worker-ticket", help=argparse.SUPPRESS)
    for sub in (one, worker, review):
        sub.add_argument("--batch-size", type=positive, default=3)
        sub.add_argument("--max-age-hours", type=positive, default=24)
    for sub in (one, worker):
        sub.add_argument("--idle-seconds", type=positive, default=300)


def reserve_worker(path, ticket=None, lifetime=180):
    if not path.is_file():
        return False
    with transaction(path) as db:
        if not table_exists(db):
            return False
        if not db.execute(f"SELECT 1 FROM share_queue WHERE {ELIGIBLE} LIMIT 1").fetchone():
            if ticket:
                db.execute("DELETE FROM share_worker WHERE slot=1 AND ticket=?", (ticket,))
            return False
        now = time.time()
        if ticket:
            return bool(db.execute("UPDATE share_worker SET expires=? WHERE slot=1 AND ticket=?",
                                   (now+lifetime, ticket)).rowcount)
        ticket = uuid.uuid4().hex
        changed = db.execute("""INSERT INTO share_worker VALUES(1,?,?) ON CONFLICT(slot) DO UPDATE
            SET ticket=excluded.ticket, expires=excluded.expires WHERE share_worker.expires<=?""",
                             (ticket, now+lifetime, now)).rowcount
        return ticket if changed else False


def clear_worker(path, ticket):
    with transaction(path) as db:
        db.execute("DELETE FROM share_worker WHERE slot=1 AND ticket=?", (ticket,))


def wake_worker(path):
    if os.environ.get("WATCH_AND_DO_QUEUE_WORKER") == "off" or not idle_supported() or not shutil.which("gh"):
        return
    ticket = reserve_worker(path)
    if ticket:
        try:
            args = [sys.executable, "-B", str(Path(__file__).with_name("community_memory.py")),
                    "--data", str(path.resolve().parents[1]), "community-queue-worker", "--worker-ticket", ticket]
            opts = ({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
                    if os.name == "nt" else {"start_new_session": True})
            subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **opts)
        except OSError:
            clear_worker(path, ticket)


def run_command(path, args):
    if args.command == "community-queue":
        return status(path)
    if args.command == "community-queue-review":
        result = review_queue(path, args.approve, args.skip, args.all, args.batch_size, args.max_age_hours)
        if result["approved"]:
            wake_worker(path)
        return result
    if args.command == "community-queue-retry":
        with transaction(path) as db:
            if not table_exists(db) or not db.execute(f"""UPDATE share_queue SET uncertain=0,
                problem=NULL,next_try=0 WHERE digest=? AND {ELIGIBLE} AND uncertain=1
                AND expires<=? AND problem='awaiting-github-receipt'""", (args.sha256, time.time())).rowcount:
                raise ValueError("No eligible uncertain submission with a completed negative receipt check")
        wake_worker(path)
        return {"queue_status": "queued", "sha256": args.sha256}

    def idle():
        if getattr(args, "host_idle", False):
            return True
        elapsed = idle_seconds()
        return elapsed is not None and elapsed >= args.idle_seconds

    def run_once():
        return tick(path, idle=idle, batch_size=args.batch_size, max_age_hours=args.max_age_hours)

    if args.command == "community-queue-tick":
        return run_once()
    ticket = args.worker_ticket or reserve_worker(path)
    if ticket:
        try:
            while reserve_worker(path, ticket, lifetime=max(180, 3*args.poll_seconds)):
                run_once()
                if not reserve_worker(path, ticket, lifetime=max(180, 3*args.poll_seconds)):
                    break
                time.sleep(args.poll_seconds)
        finally:
            clear_worker(path, ticket)
    return {"state": "stopped"}
