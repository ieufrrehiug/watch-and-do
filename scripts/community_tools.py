"""Record demonstrated tools and compare them with read-only local observations."""
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import sys


def unknown_tools():
    return {"software": "unknown", "skills": "unknown", "capabilities": []}


def validate_tools(tools, check_text):
    if not isinstance(tools, dict) or set(tools) != {"software", "skills", "capabilities"}:
        raise ValueError("tools requires software, skills and capabilities")
    for group in ("software", "skills", "capabilities"):
        rows = tools[group]
        if group != "capabilities" and rows in ("none", "unknown"):
            continue
        if not isinstance(rows, list) or len(rows) > 24 or (group != "capabilities" and not rows):
            raise ValueError(f"Supply up to 24 {group} entries; for unknown or unused tools say unknown or none")
        seen = set()
        for row in rows:
            if group == "software":
                if not isinstance(row, dict) or set(row) != {"name", "version"}:
                    raise ValueError("Each software entry requires a name and version (or unknown)")
                check_text(row["version"], "software.version", 64)
                name = row["name"]
            else:
                name = row
            check_text(name, group, 96)
            if group == "skills" and not re.fullmatch(r"[\w-]+(?::[\w-]+)?", name):
                raise ValueError("Use the installed skill name or plugin:skill identifier")
            if name.casefold() in seen or name.casefold() in ("none", "unknown"):
                raise ValueError(f"Duplicate or reserved {group} name")
            seen.add(name.casefold())
    return tools


@lru_cache(maxsize=1)
def seed_profiles():
    path = Path(__file__).resolve().parents[1] / "seeds" / "tool-profiles.json"
    return json.loads(path.read_text(encoding="utf8")) if path.is_file() else {}


def seed_annotation(card_sha, check_text):
    catalog = seed_profiles()
    profile_id = catalog.get("cards", {}).get(card_sha)
    if profile_id:
        profile = catalog["profiles"][profile_id]
        return {"tools": validate_tools(profile["tools"], check_text), "tools_source": profile["source"]}
    return {"tools": unknown_tools(), "tools_source": "unrecorded"}


def tool_view(item, digest, check_text):
    """An annotation is bound to the exact original card, never part of its digest."""
    if "tools" in item:
        return {"tools": item["tools"], "tools_source": "author"}
    return seed_annotation(digest(item), check_text)


def local_links(dbfile):
    path = dbfile.with_name("scene-tool-profiles.json")
    if not path.is_file():
        return {}, "unrecorded"
    try:
        with path.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) <= 1024 * 1024:
            data = json.loads(raw.decode("utf-8-sig"))
            if (isinstance(data, dict) and data.get("format") == "watch-and-do.local-seed-tools.v1"
                    and isinstance(data.get("links"), dict)):
                return data["links"], "unrecorded"
    except (OSError, ValueError):
        pass
    return {}, "local annotation file unreadable"


def local_tool_view(lesson, links, digest, check_text):
    if "tools" in lesson:
        return {"tools": lesson["tools"], "tools_source": "personal-record"}
    mapping, unrecorded = links
    card_sha = mapping.get(digest(lesson)) if mapping else None
    if isinstance(card_sha, str):
        result = seed_annotation(card_sha, check_text)
        if result["tools_source"] != "unrecorded":
            result["tools_source"] = "private evidence link · " + result["tools_source"]
            return result
    return {"tools": unknown_tools(), "tools_source": unrecorded}


def tool_terms(tools):
    terms = list(tools["capabilities"])
    if isinstance(tools["software"], list):
        terms.extend(s["name"] for s in tools["software"])
    if isinstance(tools["skills"], list):
        terms.extend(tools["skills"])
    return terms


# Only fixed executable names are looked up. A card can never supply a command.
EXECUTABLES = {
    "adobe photoshop": ("Photoshop",), "adobe after effects": ("AfterFX",), "剪映专业版": ("JianyingPro",),
    "gimp": ("gimp", "gimp-3.0", "gimp-2.10"), "blender": ("blender",),
    "ffmpeg": ("ffmpeg",), "ffprobe": ("ffprobe",), "node.js": ("node",),
    "microsoft edge": ("msedge", "microsoft-edge", "microsoft-edge-stable"),
    "google chrome": ("chrome", "google-chrome", "google-chrome-stable"),
    "firefox": ("firefox",), "obs studio": ("obs64", "obs"),
}
WINDOWS_APPS = {
    "microsoft edge": ("Microsoft/Edge/Application/msedge.exe",),
    "google chrome": ("Google/Chrome/Application/chrome.exe",),
    "gimp": ("GIMP 3/bin/gimp-3.0.exe", "GIMP 2/bin/gimp-2.10.exe"),
    "firefox": ("Mozilla Firefox/firefox.exe",), "obs studio": ("obs-studio/bin/64bit/obs64.exe",),
}
WINDOWS_PRODUCTS = {
    "剪映专业版": (r"剪映专业版(?:\s+\d+(?:\.\d+)*)?", "JianyingPro.exe"),
    "adobe after effects": (r"Adobe After Effects(?:\s+(?:CC\s+)?\d{4})?", "AfterFX.exe"),
}


def registered_products(pattern, executable):
    import winreg
    def value(handle, key):
        try:
            text = winreg.QueryValueEx(handle, key)[0]
            return text.strip() if isinstance(text, str) else ""
        except OSError:
            return ""
    records, paths = [], []
    base = r"Software\Microsoft\Windows\CurrentVersion"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            access = winreg.KEY_READ | view
            try:
                with winreg.OpenKey(hive, base + "\\App Paths\\" + executable, 0, access) as product:
                    paths.append(value(product, ""))
            except OSError:
                pass
            try:
                with winreg.OpenKey(hive, base + r"\Uninstall", 0, access) as parent:
                    for i in range(winreg.QueryInfoKey(parent)[0]):
                        try:
                            with winreg.OpenKey(parent, winreg.EnumKey(parent, i), 0, access) as product:
                                name = value(product, "DisplayName")
                                if re.fullmatch(pattern, name, re.I):
                                    rec = tuple(value(product, k) for k in ("DisplayVersion", "InstallLocation", "DisplayIcon"))
                                    if (name, *rec) not in records:
                                        records.append((name, *rec))
                        except OSError:
                            continue
            except OSError:
                continue
    return records, paths


def registry_path(value):
    # Registry entries may contain shell commands or icons. Treat only absolute local paths as data.
    location = os.path.expandvars(value).strip().strip('"')
    path = Path(location)
    if not path.is_absolute() or location.startswith(("\\\\", "//")) or '"' in location or "\x00" in location:
        return None
    return path


def windows_product(key, wanted):
    pattern, executable = WINDOWS_PRODUCTS[key]
    records, app_paths = registered_products(pattern, executable)
    # Use the recorded version when several editions coexist, otherwise prefer the newest registration.
    def priority(row):
        version = row[1]
        same = bool(version and wanted and (version == wanted or wanted.startswith(version + "x")))
        parts = tuple(int(n) for n in re.findall(r"\d{1,9}", version))
        return same, parts
    records.sort(key=priority, reverse=True)
    candidates = []
    version = "unknown"
    if records:
        name, version, location, icon = records[0]
        version = version or "unknown"
        root = registry_path(location)
        icon = registry_path(re.sub(r",\s*-?\d+$", "", icon.strip()))
        if root:
            candidates.extend((root / executable, root / "Support Files" / executable, root / name / "Support Files" / executable))
        if icon:
            candidates.append(icon.parent / executable)
    # With multiple registrations an unrelated default App Path cannot confirm a particular version.
    if len(records) <= 1:
        candidates.extend(p for raw in app_paths if (p := registry_path(raw)))
    for path in candidates:
        if path.name.casefold() == executable.casefold() and path.is_file():
            return {"status": "found", "source": "windows-registry-and-file", "version": version,
                    "evidence": f"Application executable exists at {path}. " +
                                (f"Uninstall registration: {name}, DisplayVersion {version}. " if records else "Registered App Path. ") +
                                "Launch and build-specific behavior have not been tested."}
    if records:
        return {"status": "registered", "source": "windows-uninstall-registry", "version": version,
                "evidence": f"Uninstall registration: {name}, DisplayVersion {version}. Verify the executable path and launch locally."}
    return None

ROUTES = {
    "subject-cutout": (
        ("GIMP", "在原图上用前景选择描出主体，细修蒙版后导出透明 PNG。"),
        ("Adobe Photoshop", "对原图建立主体选区，微调图层蒙版并导出透明 PNG。")),
    "video-matte": (("Blender", "在影片剪辑编辑器中为轮廓蒙版设置关键帧，通过合成器导出带透明度的帧。"),),
    "browser-rendering": (
        ("Google Chrome", "在相同视口运行成品，复查相同输入、时刻及相机。"),
        ("Microsoft Edge", "在相同视口运行成品，复查相同输入、时刻及相机。"),
        ("Firefox", "在相同视口运行成品，复查所需网页 API、画面和交互。")),
    "window-capture": (("OBS Studio", "选择系统支持的窗口捕获后端，试录实际运动，再回放已写出片段。"),),
}

SKILL_ROUTES = {
    "subject-cutout": (("imagegen", "核对本次会话有可用的图像编辑工具。用抠出的透明度作蒙版覆回原图，对比主体细节、边缘与原尺寸。"),),
    "browser-rendering": (("agent-browser", "核对技能可连接本机浏览器，打开同一成品并按原卡设置视口和取样时刻。"),),
}


def skill_roots():
    home = Path.home()
    codex = Path(os.getenv("CODEX_HOME") or home / ".codex")
    return [codex / "skills", home / ".agents" / "skills", Path.cwd() / ".agents" / "skills"]


def inventory_entries(inventory):
    """Host-supplied observations cover GUI apps and session-only plugin skills."""
    if not isinstance(inventory, list) or len(inventory) > 512:
        raise ValueError("Local inventory must be a list of observations")
    entries = {}
    for row in inventory:
        if (not isinstance(row, dict) or set(row) - {"kind", "name", "status", "version", "evidence", "capabilities"}
                or row.get("kind") not in ("software", "skill") or row.get("status") not in ("found", "missing")
                or not all(isinstance(row.get(k), str) and row[k].strip() for k in ("name", "evidence"))
                or not isinstance(row.get("version", "unknown"), str)
                or not isinstance(row.get("capabilities", []), list)
                or not all(isinstance(c, str) and c.strip() for c in row.get("capabilities", []))):
            raise ValueError("Each inventory entry needs kind, name, found/missing status and observed evidence")
        key = (row["kind"], row["name"].casefold())
        if key in entries:
            raise ValueError("Duplicate local inventory entry")
        entries[key] = row
    return entries


def observe(kind, name, entries, roots, wanted=None):
    key = name.casefold()
    row = entries.get((kind, key))
    if row:
        return {"status": row["status"], "evidence": row["evidence"], "version": row.get("version", "unknown"),
                "source": "local-inventory"}
    if kind == "skill":
        # Namespaced skills may be available only through the plugin/session catalog.
        for root in roots:
            if ":" not in name and any((root / p / name / "SKILL.md").is_file() for p in ("", ".system")):
                return {"status": "found", "source": "skill-file", "evidence": f"Located {name}/SKILL.md under {root}"}
        return {"status": "not-detected", "evidence": "No matching SKILL.md in checked roots; check the active session catalog."}
    if key == "python":
        return {"status": "found", "source": "interpreter", "version": ".".join(map(str, sys.version_info[:3])),
                "evidence": "Running Python interpreter: " + sys.executable}
    if os.name == "nt" and key in WINDOWS_PRODUCTS:
        registered = windows_product(key, wanted)
        if registered:
            return registered
    for exe in EXECUTABLES.get(key, ()):
        path = shutil.which(exe)
        if path:
            return {"status": "found", "source": "PATH", "version": "unknown", "evidence": path}
    if os.name == "nt":
        for base in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            if not os.getenv(base):
                continue
            for suffix in WINDOWS_APPS.get(key, ()):
                path = Path(os.environ[base]) / suffix
                if path.is_file():
                    return {"status": "found", "source": "application-file", "version": "unknown", "evidence": str(path)}
    clue = ("No executable found in the checked locations." if key in EXECUTABLES
            else "No bundled probe for this software.")
    return {"status": "not-detected", "version": "unknown", "evidence": clue + " Check the app or supply local inventory."}


def preflight(tools, check, basis, inventory=(), roots=None):
    entries = inventory_entries(list(inventory) if isinstance(inventory, tuple) else inventory)
    roots = skill_roots() if roots is None else list(roots)
    result = {"software": [], "skills": [], "alternatives": [], "original_tools": tools,
              "acceptance": {"check": check, "basis": basis, "status": "needs-local-test"}}
    incomplete = False
    original_tools = set()
    missing_skill = False
    for group, kind in (("software", "software"), ("skills", "skill")):
        rows = tools[group]
        if isinstance(rows, str):
            incomplete |= rows == "unknown"
            continue
        for entry in rows:
            name = entry["name"] if kind == "software" else entry
            observed = observe(kind, name, entries, roots, entry["version"] if kind == "software" else None)
            original_tools.add((kind, name.casefold()))
            if kind == "software":
                wanted, found = entry["version"], observed.get("version", "unknown")
                observed["recorded_version"] = wanted
                comparison = "unrecorded" if wanted == "unknown" else "unconfirmed"
                if wanted != "unknown" and found != "unknown" and observed["status"] in ("found", "registered"):
                    if wanted.casefold() == found.casefold():
                        comparison = "same"
                    elif re.fullmatch(r"\d+(?:\.\d+)*", wanted) and found.startswith(wanted + "."):
                        comparison = "matches-recorded-precision"
                    elif re.fullmatch(r"\d+(?:\.\d+)*", found) and re.fullmatch(re.escape(found) + r"(?:x\d+|\.\d+(?:\.\d+)*)", wanted, re.I):
                        comparison = "unconfirmed"
                    else:
                        comparison = "different"
                observed["version_check"] = comparison
                incomplete |= comparison in ("unconfirmed", "different")
            incomplete |= observed["status"] != "found"
            missing_skill |= kind == "skill" and observed["status"] != "found"
            result[group].append(dict(name=name, **observed))
    result["route"] = "check-original-or-alternatives" if incomplete else "try-original"
    if incomplete:
        for cap in tools["capabilities"]:
            choices = [("software", n, m) for n, m in ROUTES.get(cap, ())]
            choices.extend(("skill", n, m) for n, m in SKILL_ROUTES.get(cap, ()))
            choices.extend((row["kind"], row["name"], "按本机能力记录试做同一输入，并按原卡验收。")
                           for row in entries.values() if row["status"] == "found" and cap in row.get("capabilities", []))
            seen = set()
            for kind, name, method in choices:
                key = (kind, name.casefold())
                if key in seen:
                    continue
                seen.add(key)
                observed = observe(kind, name, entries, roots)
                if key in original_tools and not (kind == "software" and missing_skill and observed["status"] == "found"):
                    continue
                result["alternatives"].append(dict(capability=cap, kind=kind, name=name, method=method, **observed))
        result["alternatives"].sort(key=lambda row: row["status"] != "found")
        result["next_step"] = "先试本机已找到且支持目标能力的路线。如无合适候选，按能力查询软件或技能并核对可用性；使用原输入和原卡验收方法后记录结果。"
    return result
