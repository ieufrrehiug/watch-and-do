"""Offline exchange of public experience cards. The personal store is never synchronized."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata

from memory_paths import default_data


TASKS = ("analysis", "video", "web-code", "scene", "tutorial", "install", "reverse")
BASES = ("program", "frames", "listening", "user", "manual")
USAGE = "commercial-use-requires-separate-authorization"
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
    fields(data, CARD)
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
    fields(data, REVIEW)
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
    fields(data, PACK)
    require(data["format"] == "watch-and-do.pack.v1" and data["usage"] == USAGE, "Unknown format or usage terms")
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
    return data


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
        matched = {t for t in terms if t in relevant or hit(text, t)}
        if not matched:
            continue
        if key not in matches:
            matches[key] = dict(item, source="community" if note else "maintainer-seed", version=pack["version"], matched=sorted(matched),
                                maintainer=pack["maintainer"], reproductions=[])
        if note:
            matches[key]["reproductions"].append({k: note[k] for k in ("reviewer", "environment", "basis", "evidence")})
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
    make = commands.add_parser("community-release", help="As maintainer, assemble a complete reviewed snapshot")
    make.add_argument("--version", type=int, required=True)
    make.add_argument("--maintainer", required=True)
    make.add_argument("--review", type=Path, action="append", default=[])
    make.add_argument("--empty", action="store_true", help="Intentionally withdraw all cards")
    for sub in (draft, review, make):
        sub.add_argument("--out", type=Path, required=True)
    take = commands.add_parser("community-install")
    take.add_argument("--input", type=Path, required=True)
    take.add_argument("--sha256", help="Compare exact file bytes to a digest from the trusted release")
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
        if args.from_scene:
            require(data["task"] == "scene", "--from-scene requires a scene card")
            check_local(folder / "scenes.sqlite3", data)
        result = export(args.out, data)
    elif args.command == "community-review":
        data = card(read(args.card)[0]) if args.card else installed_card(db, args.installed_id)
        note = dict(format="watch-and-do.review.v1", card=data, card_sha256=digest(data),
                    reviewer=args.reviewer, environment=args.environment, outcome=args.outcome,
                    basis=args.basis, evidence=args.evidence)
        result = export(args.out, reviewed(note))
    elif args.command == "community-release":
        require(bool(args.review) != args.empty, "Supply --review files, or explicitly choose --empty")
        notes = [reviewed(read(path)[0]) for path in args.review]
        notes.sort(key=lambda n: (n["card"]["id"], n["reviewer"].casefold()))
        pack = dict(format="watch-and-do.pack.v1", version=args.version, maintainer=args.maintainer, usage=USAGE, reviews=notes)
        result = export(args.out, release(pack))
    elif args.command == "community-install":
        data, sha = read(args.input)
        require(args.sha256 is None or sha == args.sha256.lower(), "Release file SHA-256 mismatch")
        result = install(db, data)
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
