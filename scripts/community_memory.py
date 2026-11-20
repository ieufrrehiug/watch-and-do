"""Offline exchange of public experience cards. The personal store is never synchronized."""
import argparse
import base64
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata
from urllib.request import Request, urlopen

from memory_paths import default_data
from community_tools import local_links, local_tool_view, preflight, tool_terms, tool_view, unknown_tools, validate_tools
import community_queue


TASKS = ("analysis", "video", "web-code", "scene", "tutorial", "install", "reverse")
BASES = ("program", "frames", "listening", "user", "manual")
USAGE = "commercial-use-requires-separate-authorization"
OWNER = "ieufrrehiug"
OWNER_ID = 215894027
REPO = OWNER + "/watch-and-do"
PROMPT = ("你希望怎样分享以后验证过的经验？可以选「自动分享脱敏经验卡到公开的 GitHub 社区」、"
          "「每条先给我看，我批准后再分享」或「只在本机使用」。三种都能使用公共经验，随时可以改。")
SHARING_CHOICES = ("auto", "review", "private")
MAX_BYTES = 4 * 1024 * 1024
CARD = {"id", "author", "task", "kind", "topics", "environment", "method", "check", "basis", "evidence"}
REVIEW = {"format", "card", "card_sha256", "reviewer", "environment", "outcome", "basis", "evidence"}
PACK = {"format", "version", "maintainer", "usage", "reviews"}
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
HANDLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
PRIVATE = re.compile(
    r"(?:[a-z]:[/\\]|\\\\|(?:^|[\s(])/[a-z0-9_.-]+/|~/|file://|https?://"
    r"|[\w.+-]+@[\w.-]+\.[a-z]{2,}|-----BEGIN [\w ]*PRIVATE KEY"
    r"|\b(?:gh[pousr]_|github_pat_|sk-(?:proj-)?)[\w-]{8,}"
    r"|\b(?:authorization|bearer|cookie|password|token|api[_-]?key)\s*[:=]\s*\S+)", re.I)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def fields(data, expected):
    require(isinstance(data, dict) and set(data) == expected, "Unexpected or missing JSON fields")


def public_text(value, field, size=1000):
    require(isinstance(value, str) and value == value.strip() and 0 < len(value) <= size,
            f"Empty, untrimmed or oversized field: {field}")
    checked = unicodedata.normalize("NFKC", value)
    require(not PRIVATE.search(checked) and not any(unicodedata.category(c) in {"Cc", "Cf"} for c in checked),
            f"Remove private locations, links, credentials or control characters from {field}")


def handle(value):
    require(isinstance(value, str) and HANDLE.fullmatch(value), "Use a public GitHub-style handle")


def identifier(value):
    require(isinstance(value, str) and ID.fullmatch(value), "Invalid card id")


def card(data):
    fields(data, CARD | {"tools"} if isinstance(data, dict) and "tools" in data else CARD)
    if "tools" in data:
        validate_tools(data["tools"], public_text)
    identifier(data["id"])
    handle(data["author"])
    require(data["task"] in TASKS and data["kind"] in ("method", "pitfall") and data["basis"] in BASES,
            "Invalid task, kind or evidence basis")
    terms = data["topics"]
    require(isinstance(terms, list) and 1 <= len(terms) <= 12, "Supply 1 to 12 topic terms")
    for term in terms:
        public_text(term, "topic", 64)
    for key in ("environment", "method", "check", "evidence"):
        public_text(data[key], key)
    return data


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf8")


def digest(data):
    return hashlib.sha256(canonical(data)).hexdigest()


def reviewed(data):
    fields(data, REVIEW | {"tools"} if isinstance(data, dict) and "tools" in data else REVIEW)
    if "tools" in data:
        validate_tools(data["tools"], public_text)
    require(data["format"] == "watch-and-do.review.v1", "Unknown review format")
    item = card(data["card"])
    require(data["card_sha256"] == digest(item), "Card changed since review")
    handle(data["reviewer"])
    require(data["reviewer"].casefold() != item["author"].casefold(), "An independent reviewer is required")
    require(data["basis"] in BASES and data["outcome"] in ("reproduced", "failed"), "Invalid review result")
    for key in ("environment", "evidence"):
        public_text(data[key], key)
    return data


def release(data):
    official = data.get("format") == "watch-and-do.pack.v2" if isinstance(data, dict) else False
    fields(data, PACK | {"approvals"} if official else PACK)
    require(data["format"] in ("watch-and-do.pack.v1", "watch-and-do.pack.v2") and data["usage"] == USAGE, "Unknown format or usage terms")
    require(type(data["version"]) is int and 0 < data["version"] < 2**63, "Version must be a positive integer")
    handle(data["maintainer"])
    require(isinstance(data["reviews"], list) and len(data["reviews"]) <= 2000, "Invalid release size")
    cards, witnesses = {}, set()
    for note in data["reviews"]:
        reviewed(note)
        require(note["outcome"] == "reproduced", "Resolve the failed reproduction before release")
        item = note["card"]
        key, sha = item["id"], note["card_sha256"]
        require(cards.setdefault(key, sha) == sha, "Conflicting versions of one card")
        witness = (key, note["reviewer"].casefold())
        require(witness not in witnesses, "Duplicate review for one card")
        witnesses.add(witness)
    if official:
        require(data["maintainer"] == OWNER and isinstance(data["approvals"], dict)
                and set(data["approvals"]) == {digest(n) for n in data["reviews"]}, "Missing official approval receipts")
    return data


def github(resource):
    req = Request("https://api.github.com/repos/" + REPO + "/" + resource,
                  headers={"Accept": "application/vnd.github+json", "User-Agent": "watch-and-do-review"})
    with urlopen(req, timeout=12) as response:
        body = response.read(MAX_BYTES+1)
    require(len(body) <= MAX_BYTES, "GitHub record too large")
    return json.loads(body)


def official_json(path, fetch):
    obj = fetch("contents/" + path + "?ref=main")
    require(obj.get("encoding") == "base64" and isinstance(obj.get("content"), str),
            "Official repository file unavailable")
    return json.loads(base64.b64decode(obj["content"]).decode("utf-8-sig"))


def posted(issue, data, login):
    require("pull_request" not in issue and issue["user"]["type"] == "User"
            and issue["user"]["login"].casefold() == login.casefold(), "GitHub submission author mismatch")
    blocks = re.findall(r"^```json\s*\n(.*?)\n```\s*$", issue["body"].replace("\r\n", "\n"), re.M | re.S)
    require(len(blocks) == 1 and digest(json.loads(blocks[0])) == digest(data), "GitHub submission differs from reviewed data")


def verify_official(pack, fetch=None):
    """Read public records only; no credentials, attachments or contributed code are run."""
    fetch = fetch or github
    cache = {}
    def get(resource):
        if resource not in cache:
            cache[resource] = fetch(resource)
        return cache[resource]
    for note in pack["reviews"]:
        fingerprint = digest(note)
        receipt = pack["approvals"][fingerprint]
        require(isinstance(receipt, str) and re.fullmatch(r"[1-9][0-9]{0,11}:[1-9][0-9]{0,17}", receipt), "Invalid issue:comment receipt")
        number, comment_id = receipt.split(":")
        issue = get("issues/" + number)
        posted(issue, note, note["reviewer"])
        comment = get("issues/comments/" + comment_id)
        require(comment.get("issue_url") == "https://api.github.com/repos/" + REPO + "/issues/" + number
                and comment["user"]["id"] == OWNER_ID and comment["user"]["type"] == "User",
                "Approval must come from the repository owner on the reproduction issue")
        command = re.fullmatch(r"watch-and-do approve ([0-9a-f]{64}) (seed|[1-9][0-9]{0,11}) (https://[^\s]+)",
                               comment["body"].strip())
        require(command and command[1] == fingerprint, "Missing owner approval of exact review and evidence link")
        item = note["card"]
        if command[2] == "seed":
            seed = official_json("seeds/cards.json", get)
            require(any(digest(c) == digest(item) for c in seed["cards"]), "Referenced seed differs")
            author_id = OWNER_ID
        else:
            original = get("issues/" + command[2])
            posted(original, item, item["author"])
            author_id = original["user"]["id"]
        require(author_id != issue["user"]["id"], "Independent GitHub account required")


def sharing(path, setting=None, begin=False):
    require(setting is None or setting in (*SHARING_CHOICES, "invited"), "Unknown sharing choice")
    if not (begin or setting or path.is_file()):
        return {"choice": "new", "ask_now": False}
    with closing(writable(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS sharing_choice (slot INTEGER PRIMARY KEY CHECK(slot=1), choice TEXT NOT NULL)")
        row = db.execute("SELECT choice FROM sharing_choice WHERE slot=1").fetchone()
        choice = row[0] if row else "new"
        ask = begin and choice == "new"
        if ask or (setting and choice != setting):
            choice = setting or "invited"
            db.execute("INSERT OR REPLACE INTO sharing_choice VALUES(1,?)", (choice,))
            db.execute("CREATE TABLE IF NOT EXISTS pending_share (slot INTEGER PRIMARY KEY CHECK(slot=1), digest TEXT NOT NULL)")
            db.execute("DELETE FROM pending_share")
            community_queue.withdraw(db)
    result = {"choice": choice, "ask_now": ask}
    if ask:
        result["question"] = PROMPT
    return result


def preview_share(path, data, confirmation):
    require(path.is_file(), "Sharing is off; keep working locally")
    is_review = isinstance(data, dict) and data.get("format") == "watch-and-do.review.v1"
    if is_review:
        reviewed(data)
    else:
        card(data)
    sha = digest(data)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        choice = None
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='sharing_choice'").fetchone():
            row = db.execute("SELECT choice FROM sharing_choice WHERE slot=1").fetchone()
            choice = row[0] if row else None
        require(choice in ("auto", "review"), "Sharing is off; keep working locally")
        community_queue.schema(db)
        key = community_queue.preview_key(data)
        timing = ()
        prior = None
        if choice == "auto":
            require(confirmation is None, "Sharing choice changed; prepare the current card again")
        elif confirmation is None:
            db.execute("DELETE FROM pending_share")
            prior = db.execute("SELECT issue FROM share_queue WHERE digest=? AND (issue IS NOT NULL OR payload IS NOT NULL)", (sha,)).fetchone()
            if prior:
                db.execute("DELETE FROM share_previews WHERE item_key=?", (key,))
            else:
                community_queue.save_preview(db, key, sha, canonical(data).decode("utf8"))
        else:
            require(confirmation == sha, "Content or sharing choice changed; show a new preview")
            community_queue.mature_previews(db)
            current = db.execute("SELECT created,ready FROM share_previews WHERE item_key=? AND digest=?", (key, sha)).fetchone()
            legacy = db.execute("DELETE FROM pending_share WHERE slot=1 AND digest=?", (sha,)).rowcount
            require(current or legacy, "Content or sharing choice changed; show a new preview")
            timing = current or ()
            db.execute("DELETE FROM share_previews WHERE item_key=? AND digest=?", (key, sha))
        ready = choice == "auto" or confirmation is not None or bool(prior)
        status = community_queue.enqueue(db, sha, canonical(data).decode("utf8"), choice, *timing) if ready else "awaiting-approval"
    return {"payload": data, "sha256": sha, "choice": choice, "ready": ready, "queue_status": status,
            "destination": "https://github.com/" + REPO + "/issues/new/choose",
            "template": "报告复现结果" if is_review else "贡献一条经验"}


def read(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "JSON file exceeds size limit")
    return json.loads(raw.decode("utf-8-sig")), hashlib.sha256(raw).hexdigest()


def export(path, data):
    require(path.suffix.lower() == ".json", "Select a new .json output file")
    raw = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf8")
    require(len(raw) <= MAX_BYTES, "Public file exceeds size limit")
    # Exclusive creation also protects unrelated files selected by mistake.
    with path.open("xb") as stream:
        stream.write(raw)
    return {"file": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def writable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS snapshot (slot INTEGER PRIMARY KEY CHECK(slot=1), version INTEGER, digest TEXT, body TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS disabled (id TEXT PRIMARY KEY)")
    return db


def install(path, pack):
    release(pack)
    if pack["maintainer"].casefold() == OWNER:
        require(pack["format"] == "watch-and-do.pack.v2", "Official community packs require GitHub approval receipts")
        published = official_json(f"community-packs/v{pack['version']}.json", github)
        require(digest(published) == digest(pack), "Pack differs from the official published version")
        verify_official(pack)
    identity = digest(pack)
    with closing(writable(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT version,digest FROM snapshot WHERE slot=1").fetchone()
        if prior:
            require(pack["version"] >= prior[0], "Refusing to downgrade the current snapshot")
            if pack["version"] == prior[0]:
                require(prior[1] == identity, "Published version already exists with different contents")
                return {"version": prior[0], "status": "already installed"}
        db.execute("INSERT OR REPLACE INTO snapshot VALUES(1,?,?,?)",
                   (pack["version"], identity, canonical(pack).decode("utf8")))
    return {"version": pack["version"], "status": "installed"}


def preference(path, key, disable):
    identifier(key)
    with closing(writable(path)) as db, db:
        if disable:
            db.execute("INSERT OR IGNORE INTO disabled VALUES(?)", (key,))
        else:
            db.execute("DELETE FROM disabled WHERE id=?", (key,))
    return {"id": key, "disabled": disable}


def installed_card(path, key):
    identifier(key)
    if path.is_file():
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            row = db.execute("SELECT body FROM snapshot WHERE slot=1").fetchone()
        if row:
            for note in json.loads(row[0])["reviews"]:
                if note["card"]["id"] == key:
                    return note["card"]
    seed = bundled_seed()
    if seed:
        for item in seed["cards"]:
            if item["id"] == key:
                return item
    raise ValueError("Card is absent from the installed release")


def bundled_seed():
    path = Path(__file__).resolve().parents[1] / "seeds" / "cards.json"
    if not path.is_file():
        return None
    data, _ = read(path)
    fields(data, {"format", "usage", "version", "maintainer", "cards"})
    require(data["format"] == "watch-and-do.seed.v1" and data["usage"] == USAGE, "Invalid seed catalog")
    require(type(data["version"]) is int and data["version"] > 0, "Invalid seed version")
    handle(data["maintainer"])
    require(isinstance(data["cards"], list) and len(data["cards"]) <= 2000, "Invalid seed card list")
    ids = set()
    for item in data["cards"]:
        card(item)
        require(item["author"] == data["maintainer"] and item["id"] not in ids, "Invalid seed attribution or duplicate")
        ids.add(item["id"])
    return data


def suggestions(path, task, brief, topics=(), exclude=(), hidden=(), limit=10):
    from scene_memory import hit, inferred, negated, normalize
    blocked_ids = set(hidden)
    entries = []
    if path.is_file():
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as db, db:
            db.execute("BEGIN")
            row = db.execute("SELECT body FROM snapshot WHERE slot=1").fetchone()
            blocked_ids.update(k for k, in db.execute("SELECT id FROM disabled"))
        if row:
            pack = json.loads(row[0])
            entries.extend((n["card"], n, pack) for n in pack["reviews"])
    reviewed_ids = {item["id"] for item, _, _ in entries}
    seed = bundled_seed()
    if seed:
        entries.extend((item, None, seed) for item in seed["cards"] if item["id"] not in reviewed_ids)
    text = normalize(brief)
    blocked_topics = set(map(normalize, exclude))
    relevant = set(map(normalize, topics))
    if task == "scene":
        blocked_topics.update(negated(text))
        relevant.update(inferred(text))
    matches = {}
    for item, note, pack in entries:
        key = item["id"]
        terms = set(map(normalize, item["topics"]))
        if key in blocked_ids or item["task"] != task or terms & blocked_topics:
            continue
        provenance = tool_view(item, digest, public_text)
        search_terms = terms.union(map(normalize, tool_terms(provenance["tools"])))
        if search_terms & blocked_topics:
            continue
        matched = {t for t in search_terms if t in relevant or hit(text, t)}
        if not matched:
            continue
        if key not in matches:
            matches[key] = dict(item, source="community" if note else "maintainer-seed", version=pack["version"], matched=sorted(matched),
                                maintainer=pack["maintainer"], reproductions=[])
            matches[key].update(provenance)
        if note:
            reproduction = {k: note[k] for k in ("reviewer", "environment", "basis", "evidence")}
            reproduction["tools"] = note.get("tools", unknown_tools())
            matches[key]["reproductions"].append(reproduction)
    return sorted(matches.values(), key=lambda m: (-len(m["matched"]), m["id"]))[:limit]


def check_local(dbfile, item):
    from scene_memory import ArchiveLookup, lessons
    entry = next((row for _, row in lessons(dbfile) if row["id"] == item["id"] and row["status"] != "pending"), None)
    expected = "pass" if item["kind"] == "method" else "fail"
    require(entry and entry["status"] == expected and entry["verification"] == item["basis"],
            "Card kind or evidence basis does not match the latest checked local result")
    archive = ArchiveLookup(dbfile)
    require(all(archive.resolve(e) for e in entry["evidence"]), "Local evidence is missing or changed")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--data", type=Path, default=default_data())
    commands = cli.add_subparsers(dest="command", required=True)
    draft = commands.add_parser("community-draft", help="Export an explicitly authored public form")
    draft.add_argument("--input", type=Path, required=True)
    draft.add_argument("--from-scene", action="store_true", help="Check the same local ID without copying private fields")
    review = commands.add_parser("community-review", help="Record an independent attempt on this exact card")
    source = review.add_mutually_exclusive_group(required=True)
    source.add_argument("--card", type=Path)
    source.add_argument("--installed-id", help="Report a result against an installed card")
    review.add_argument("--reviewer", required=True)
    review.add_argument("--environment", required=True)
    review.add_argument("--outcome", choices=("reproduced", "failed"), required=True)
    review.add_argument("--basis", choices=BASES, required=True)
    review.add_argument("--evidence", required=True)
    review.add_argument("--tools", type=Path, help="JSON describing tools actually used by the reviewer")
    probe = commands.add_parser("community-preflight", help="Compare a method's tools with this environment")
    target = probe.add_mutually_exclusive_group(required=True)
    target.add_argument("--card", type=Path)
    target.add_argument("--installed-id")
    target.add_argument("--scene-id", help="Find a personal scene lesson")
    target.add_argument("--capability", help="Explore an alternative for a task without an existing card")
    probe.add_argument("--check", help="Local acceptance criterion when using --capability")
    probe.add_argument("--basis", choices=BASES, help="Acceptance basis when using --capability")
    probe.add_argument("--skill-root", action="append", type=Path, help="Check this skills directory (repeatable)")
    probe.add_argument("--inventory", type=Path, help="Local host observations, including GUI apps or session-only skills")
    make = commands.add_parser("community-release", help="As maintainer, assemble a complete reviewed snapshot")
    make.add_argument("--version", type=int, required=True)
    make.add_argument("--maintainer", required=True)
    make.add_argument("--review", type=Path, action="append", default=[])
    make.add_argument("--approval", action="append", default=[], metavar="ISSUE:COMMENT",
                      help="Owner approval on each GitHub reproduction issue, in --review order")
    make.add_argument("--empty", action="store_true", help="Intentionally withdraw all cards")
    for sub in (draft, review, make):
        sub.add_argument("--out", type=Path, required=True)
    take = commands.add_parser("community-install")
    take.add_argument("--input", type=Path, required=True)
    take.add_argument("--sha256", help="Compare exact file bytes to a digest from the trusted release")
    take.add_argument("--allow-other-maintainer", action="store_true", help="Opt in to an unofficial pack from a maintainer you trust")
    share = commands.add_parser("community-sharing", help="Read or update the local sharing choice")
    choice = share.add_mutually_exclusive_group()
    choice.add_argument("--begin", action="store_true", help="Ask once on first use")
    choice.add_argument("--set", dest="setting", choices=SHARING_CHOICES)
    choice.add_argument("--skip", dest="setting", action="store_const", const="invited", help="Skip sharing and cancel pending submissions")
    send = commands.add_parser("community-share-preview", help="Prepare an issue under the current local sharing choice")
    send.add_argument("--input", type=Path, required=True)
    send.add_argument("--confirmed-sha256", help="Use only after user approved this exact preview")
    community_queue.add_commands(commands)
    find = commands.add_parser("community-find")
    find.add_argument("--brief", required=True)
    find.add_argument("--task", choices=TASKS, required=True)
    find.add_argument("--exclude", nargs="+", default=[])
    for name in ("community-disable", "community-enable"):
        commands.add_parser(name).add_argument("--id", required=True)
    args = cli.parse_args()
    folder = args.data.expanduser().resolve() / "learning"
    db = folder / "community.sqlite3"
    if args.command == "community-draft":
        data = card(read(args.input)[0])
        require("tools" in data, "New cards need tools: name the software, versions, skills and target capabilities; use none or unknown when applicable")
        if args.from_scene:
            require(data["task"] == "scene", "--from-scene requires a scene card")
            check_local(folder / "scenes.sqlite3", data)
        result = export(args.out, data)
    elif args.command == "community-review":
        data = card(read(args.card)[0]) if args.card else installed_card(db, args.installed_id)
        note = dict(format="watch-and-do.review.v1", card=data, card_sha256=digest(data),
                    reviewer=args.reviewer, environment=args.environment, outcome=args.outcome,
                    basis=args.basis, evidence=args.evidence, tools=read(args.tools)[0] if args.tools else unknown_tools())
        result = export(args.out, reviewed(note))
        result["review_sha256"] = digest(note)
    elif args.command == "community-preflight":
        provenance = None
        if args.scene_id:
            from scene_memory import lessons
            personal_db = folder / "scenes.sqlite3"
            data = next((r for _, r in lessons(personal_db) if r["id"] == args.scene_id and r["status"] != "pending"), None)
            require(data, "No checked personal scene lesson with this ID")
            provenance = local_tool_view(data, local_links(personal_db), digest, public_text)
            tools = provenance["tools"]
            check, basis = data["check"], data["verification"]
        elif args.capability:
            require(args.check and args.basis, "--capability needs --check and --basis")
            tools = dict(unknown_tools(), capabilities=[args.capability])
            validate_tools(tools, public_text)
            check, basis = args.check, args.basis
        else:
            data = card(read(args.card)[0]) if args.card else installed_card(db, args.installed_id)
            provenance = tool_view(data, digest, public_text)
            tools = provenance["tools"]
            check, basis = data["check"], data["basis"]
        inventory = read(args.inventory)[0] if args.inventory else []
        result = preflight(tools, check, basis, inventory, args.skill_root)
        if provenance:
            result["tools_source"] = provenance["tools_source"]
    elif args.command == "community-release":
        require(bool(args.review) != args.empty, "Supply --review files, or explicitly choose --empty")
        notes = [reviewed(read(path)[0]) for path in args.review]
        official = args.maintainer.casefold() == OWNER
        if official:
            require(len(notes) == len(args.approval), "Each official review needs --approval ISSUE:COMMENT")
            approvals = {digest(n): ref for n, ref in zip(notes, args.approval)}
        else:
            require(not args.approval, "GitHub approval receipts are for the official repository")
        notes.sort(key=lambda n: (n["card"]["id"], n["reviewer"].casefold()))
        pack = dict(format="watch-and-do.pack.v1", version=args.version, maintainer=args.maintainer, usage=USAGE, reviews=notes)
        if official:
            pack.update(format="watch-and-do.pack.v2", maintainer=OWNER, approvals=approvals)
            verify_official(release(pack))
        result = export(args.out, release(pack))
    elif args.command == "community-install":
        data, sha = read(args.input)
        require(args.sha256 is None or sha == args.sha256.lower(), "Release file SHA-256 mismatch")
        release(data)
        require(args.allow_other_maintainer or data["maintainer"].casefold() == OWNER,
                "Unofficial pack: choose --allow-other-maintainer only for a source you trust")
        result = install(db, data)
    elif args.command == "community-sharing":
        result = sharing(db, args.setting, args.begin)
        if args.begin and result["choice"] in ("auto", "review"):
            community_queue.wake_worker(db)
    elif args.command == "community-share-preview":
        data, _ = read(args.input)
        result = preview_share(db, data, args.confirmed_sha256)
        if result["queue_status"] == "queued":
            community_queue.wake_worker(db)
    elif args.command.startswith("community-queue"):
        result = community_queue.run_command(db, args)
    elif args.command == "community-find":
        if args.task == "scene":
            from scene_memory import lessons, scene_context
            _, _, excluded, topics = scene_context(args.brief, [], args.exclude)
            personal = {r["id"] for _, r in lessons(folder / "scenes.sqlite3") if r["status"] != "pending"}
            result = suggestions(db, args.task, args.brief, topics=topics, exclude=excluded, hidden=personal)
        else:
            result = suggestions(db, args.task, args.brief, exclude=args.exclude)
    else:
        result = preference(db, args.id, args.command == "community-disable")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, sqlite3.Error) as error:
        sys.exit(str(error))
