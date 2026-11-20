"""Retrieve local scene lessons and record what was actually observed on a project."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata
import zipfile

from scene_archive import ArchiveLookup, file_hash, preserve
from memory_paths import default_data
from community_tools import local_links, local_tool_view, tool_terms, unknown_tools, validate_tools

DEFAULT_DATA = default_data()
TOPICS = {
    "urban": "城市 都市 城区 街区 商业街 市中心 商圈 步行街 city urban downtown cityscape",
    "shops": "店 商铺 店铺 市场 市集 摊 集市 餐馆 茶馆 茶楼 酒馆 工坊 书房 商业街 shopping market shop store storefront cafe café bakery tavern workshop florist",
    "walkers": "行人 路人 步态 步行者 人群 居民 村民 旅人 角色 游客 NPC pedestrian pedestrians walker gait humanoid",
    "traffic": "车辆 车流 公交 出租车 巴士 行车 行驶 街车 马车 traffic vehicle vehicles bus taxi carriage",
    "animals": "动物 宠物 小猫 街猫 小狗 鸽 飞鸟 鹿 狐狸 生物 群鸟 羊群 海鸥 海鸟 animal animals pet pets bird birds cat dog deer",
    "explore": "漫游 可玩 互动 交互 操控 人称 游览 探索 步行 走进 进去 可进入 自由飞行 空中俯瞰 walking walkable first-person playable interactive explore",
    "weather": "下雨 雨夜 天气 雷雨 雪天 雨天 积雪 风雪 小雨 细雨 降雪 下雪 雨滴 暴雨 weather rainy rain storm snow",
    "atmosphere": "清晨 傍晚 黄昏 日落 日出 晨曦 晨光 雾 夜色 夜景 夜晚 雨夜 天光 光影 昼夜 early-morning dawn sunrise sunset dusk lighting night fog",
    "sound": "声景 声音 音效 环境声 喧闹 流水 海浪 风声 铃声 sound audio ambience",
    "waterfront": "渡口 码头 湖滨 江边 滨江 临水 河边 栈桥 船 靠岸 渡船 江岸 港口 水面 pier waterfront ferry boat dock wharf water",
}
# Urban briefs often name only a location. Include only the conventions of that
# location; an indoor shop on its own does not imply traffic or a city skyline.
URBAN_DEFAULTS = {"shops", "walkers", "traffic", "animals", "explore", "atmosphere", "sound"}
VERIFY = {"program", "frames", "listening", "user", "observation"}
STATUS = {"pass", "fail", "pending"}
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}$")


def normalize(value):
    return unicodedata.normalize("NFKC", value).casefold().strip()


def hit(text, word):
    if word.isascii():
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text))
    return word in text


def inferred(text):
    result = set()
    for topic, aliases in TOPICS.items():
        if any(hit(text, normalize(word)) for word in aliases.split()):
            result.add(topic)
    return result


def negated(text):
    """Respect literal omissions in a brief even when a broad scene topic matches."""
    omitted = set()
    short = {"walkers": "人 人物", "traffic": "车 汽车", "animals": "鸟 猫 狗",
             "shops": "商店 摊位", "sound": "配音 音乐和音效"}
    for topic, aliases in TOPICS.items():
        words = aliases.split() + short.get(topic, "").split()
        literal = r"(?:" + "|".join(re.escape(normalize(w)) for w in sorted(words, key=len, reverse=True)) + r")"
        cn_prefix = r"(?:不需要|不要|没有|不含|无须|不设|不加|不做|去掉|取消|无)"
        if re.search(cn_prefix + r"(?:任何|添加|加入|出现|设置)?\s*" + literal, text):
            omitted.add(topic)
        elif re.search(r"\b(?:no|without|exclude|exclude all)\s+(?:any\s+)?" + literal + r"\b", text):
            omitted.add(topic)
        elif re.search(r"\b" + literal + r"-free\b", text):
            omitted.add(topic)
        elif re.search(cn_prefix + r"[^。；，,;.!?]{1,12}?(?:或|和|与|、)" + literal, text):
            omitted.add(topic)
    return omitted


def strings(value, field, required=False):
    if not isinstance(value, list) or (required and not value):
        raise ValueError(f"{field} must be a {'nonempty ' if required else ''}list")
    if any(not isinstance(s, str) or not s.strip() for s in value):
        raise ValueError(f"{field} needs nonempty strings")
    return list(dict.fromkeys(s.strip() for s in value))


def indexed_files(values, base):
    result = []
    for value in values:
        location = Path(value)
        path = (base / location).resolve()
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Missing or empty local evidence/resource: {path}")
        result.append({"path": str(path), "sha256": file_hash(path)})
    return sorted(result, key=lambda f: f["path"])


def record(source, base):
    if not isinstance(source, dict):
        raise ValueError("Expected one lesson object per entry")
    required = ("id", "project", "method", "check", "status", "verification")
    if any(not isinstance(source.get(k), str) or not source[k].strip() for k in required):
        raise ValueError("Expected id, project, method, check, status, verification")
    out = {k: source[k].strip() for k in required}
    if not ID.fullmatch(out["id"]) or out["status"] not in STATUS or out["verification"] not in VERIFY:
        raise ValueError("Invalid lesson ID, status or verification")
    if out["status"] == "pass" and out["verification"] == "observation":
        raise ValueError("Record untested observations as pending")
    out["topics"] = sorted({normalize(s) for s in strings(source.get("topics"), "topics", True)})
    out["keywords"] = sorted({normalize(s) for s in strings(source.get("keywords", []), "keywords")})
    for field in ("evidence", "resources"):
        out[field] = indexed_files(strings(source.get(field, []), field, field == "evidence"), base)
    if "source_candidates" in source:
        out["source_candidates"] = sorted(strings(source["source_candidates"], "source_candidates"))
    if "tools" in source:
        from community_memory import public_text
        out["tools"] = validate_tools(source["tools"], public_text)
    return out


def learn(dbfile, manifest):
    raw = json.loads(manifest.read_text(encoding="utf-8-sig"))
    records = [record(row, manifest.parent) for row in (raw if isinstance(raw, list) else [raw])]
    if not records:
        raise ValueError("Empty lesson manifest")
    dbfile.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(dbfile, timeout=10)
    saved = []
    try:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS events (revision INTEGER PRIMARY KEY, id TEXT NOT NULL, identity TEXT NOT NULL UNIQUE, details TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.execute("BEGIN IMMEDIATE")
            for row in records:
                # Replaying a pre-tools manifest must still find its original revision.
                if "tools" not in row:
                    legacy = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    old = db.execute("SELECT revision FROM events WHERE identity=?",
                                     (hashlib.sha256(legacy.encode()).hexdigest(),)).fetchone()
                    if old:
                        saved.append({"id": row["id"], "revision": old[0], "result": "unchanged"})
                        continue
                    row["tools"] = unknown_tools()
                encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                identity = hashlib.sha256(encoded.encode()).hexdigest()
                existing = db.execute("SELECT revision FROM events WHERE identity=?", (identity,)).fetchone()
                if existing:
                    saved.append({"id": row["id"], "revision": existing[0], "result": "unchanged"})
                    continue
                if row["status"] == "pass":
                    earlier = db.execute("SELECT details FROM events WHERE id=? ORDER BY revision DESC", (row["id"],))
                    recent = (d for (data,) in earlier if (d := json.loads(data))["status"] != "pending")
                    last = next(recent, {})
                    if last.get("status") == "fail":
                        old_pass = next((r for r in recent if r["status"] == "pass"), {})
                        used = {f["sha256"] for r in (last, old_pass) for f in r.get("evidence", [])}
                        if all(f["sha256"] in used for f in row["evidence"]):
                            raise ValueError(f"{row['id']}: new evidence is required after a failed check")
                revision = db.execute("INSERT INTO events(id,identity,details) VALUES(?,?,?)", (row["id"], identity, encoded)).lastrowid
                saved.append({"id": row["id"], "revision": revision, "result": "saved"})
    finally:
        db.close()
    return {"store": str(dbfile), "lessons": saved}


def lessons(dbfile):
    if not dbfile.is_file():
        return []
    db = sqlite3.connect(dbfile.as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():
            return []
        return [(n, json.loads(body)) for n, body in db.execute("SELECT revision,details FROM events ORDER BY revision DESC")]
    finally:
        db.close()


def scene_context(brief, topics, exclude):
    text = normalize(brief)
    direct = inferred(text) | set(map(normalize, topics))
    suppressed = set(map(normalize, exclude)) | negated(text)
    allowed = direct - suppressed
    features = set(allowed)
    if "urban" in allowed:
        features.update(URBAN_DEFAULTS - suppressed)
    if "waterfront" in allowed and "sound" not in suppressed:
        features.add("sound")
    return text, direct, suppressed, features


def start(dbfile, brief, topics, exclude, limit=10):
    from community_memory import digest, public_text, suggestions
    text, direct, suppressed, features = scene_context(brief, topics, exclude)
    links = local_links(dbfile)
    unique, checks, failed, unavailable = set(), [], [], []
    archive=ArchiveLookup(dbfile)
    history = lessons(dbfile)
    previous_failures = {}
    for rev, lesson in history:
        if lesson["status"] == "fail":
            previous_failures.setdefault(lesson["id"], (rev, lesson))
    for revision, lesson in history:
        key = lesson["id"]
        if key in unique or lesson["status"] == "pending":
            continue
        unique.add(key)
        topic_set = set(lesson["topics"])
        if topic_set & suppressed:
            continue
        provenance = local_tool_view(lesson, links, digest, public_text)
        tools = set(map(normalize, tool_terms(provenance["tools"])))
        if tools & suppressed:
            continue
        keyword_hits = [w for w in tools.union(lesson["keywords"]) if hit(text, w)]
        matching = topic_set & features
        base = "baseline" in topic_set
        if not (keyword_hits or matching or base):
            continue
        evidence = lesson["evidence"]
        valid_evidence = [path for f in evidence if (path := archive.resolve(f))]
        if len(valid_evidence) != len(evidence):
            unavailable.append({"id": key, "reason": "evidence missing or changed; rerun the check"})
            continue
        resources = [path for f in lesson["resources"] if (path := archive.resolve(f))]
        stale_paths = [f["path"] for f in lesson["resources"] if not archive.resolve(f)]
        view = {k: lesson[k] for k in ("id","project","method","check","verification","status")}
        view.update(provenance)
        view.update(revision=revision, topics=sorted(topic_set), matched=sorted(matching),
                    resources=resources, evidence=valid_evidence)
        if stale_paths:
            view["unavailable_resources"] = stale_paths
        if lesson["status"] == "fail":
            failed.append(view)
            continue
        if key in previous_failures:
            old_rev, old = previous_failures[key]
            if old_rev < revision and all(archive.resolve(f) for f in old["evidence"]):
                failed.append({"id":key,"revision":old_rev,"status":"addressed","project":old["project"],
                               "verification":old["verification"],"failure":old["method"],"check":old["check"],
                               **local_tool_view(old, links, digest, public_text),
                               "evidence":[archive.resolve(f) for f in old["evidence"]]})
        score = 100 if base else len(keyword_hits)*4 + len(topic_set & direct)*3 + len(matching)
        checks.append((score, view))
    checks.sort(key=lambda v:(-v[0],v[1]["id"]))
    shared = suggestions(dbfile.with_name("community.sqlite3"), "scene", brief,
                         topics=features, exclude=suppressed, hidden=unique, limit=limit)
    return {"brief": brief, "topics":sorted(features), "excluded":sorted(suppressed), "lessons":[v for _,v in checks[:limit]],
            "community_suggestions":shared,
            "related_failures":failed, "unavailable":unavailable, "packages":list(archive.used.values()),
            "recovered_files":archive.recovered}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--data", default=DEFAULT_DATA)
    commands = cli.add_subparsers(dest="command", required=True)
    kickoff = commands.add_parser("scene-start", help="Match a brief and find checked guidance")
    kickoff.add_argument("--brief", required=True)
    kickoff.add_argument("--topics", nargs="+", default=[])
    kickoff.add_argument("--exclude", nargs="+", default=[])
    kickoff.add_argument("--limit", type=int, choices=range(1, 31), default=10, metavar="1..30")
    save = commands.add_parser("scene-learn", help="Save a checked observation and its local evidence")
    save.add_argument("--input", type=Path, required=True)
    bundle=commands.add_parser("scene-preserve", help="Preserve a finished distributable source ZIP and selected evidence")
    bundle.add_argument("--input", type=Path, required=True)
    args=cli.parse_args()
    db = Path(args.data).resolve()/"learning"/"scenes.sqlite3"
    if args.command == "scene-start":
        result = start(db, args.brief, args.topics, args.exclude, args.limit)
    elif args.command == "scene-preserve":
        result = preserve(db, args.input.resolve())
    else:
        result = learn(db, args.input.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
