"""Local action evidence and validated recipe discovery. No background hooks."""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from contextlib import closing
from memory_paths import default_data
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
DATA = default_data()
TASK_TYPES = ('analysis', 'video', 'web-code', 'tutorial', 'install', 'reverse')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def object_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def parse_numeric(value):
    value=value.replace('O','0').replace('o','0').replace('I','1').replace('|','1')
    number=re.fullmatch(r'\s*([-+]?\d+(?:\.\d+)?)\s*(?:dB|s)?\s*',value,re.I)
    return float(number[1]) if number else None


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def redact(value):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if re.search(r'password|cookie|authorization|token|secret|private.?key', k, re.I)
                else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return re.sub(r'(?i)Bearer\s+\S+', 'Bearer [REDACTED]', value)
    return value


def bind(value, params):
    if isinstance(value, dict): return {k: bind(v, params) for k, v in value.items()}
    if isinstance(value, list): return [bind(v, params) for v in value]
    if isinstance(value, str):
        exact = re.fullmatch(r'\$\{(\w+)\}', value)
        if exact:
            if exact[1] not in params: raise ValueError('Unresolved parameter: ' + exact[1])
            return params[exact[1]]
        def replace(match):
            if match[1] not in params: raise ValueError('Unresolved parameter: ' + match[1])
            return str(params[match[1]])
        return re.sub(r'\$\{(\w+)\}', replace, value)
    return value


def check_keys(keys):
    # Document-editing shortcuts and ordinary text only. Focus is verified again before input.
    allowed = {'{enter}', '{tab}', '{esc}', '{backspace}', '{delete}', '{space}', '{left}', '{right}',
               '{up}', '{down}', '{home}', '{end}'}
    for token in re.findall(r'\{[^{}]*\}[^{}]?|[^{}]+|[{}]', keys):
        if token.startswith('{') and token.split('}')[0].lower()+'}' not in allowed:
            if token.lower() not in {'{ctrl}a','{ctrl}c','{ctrl}v','{ctrl}z','{ctrl}s','{ctrl}y'}:
                raise ValueError('Unsupported native key sequence')


def prepare(recipe, params, recipe_dir=ROOT, replay=True):
    if recipe.get('schema') != 1 or recipe.get('task_type') not in TASK_TYPES:
        raise ValueError('Unsupported recipe schema/task type')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', recipe['id']):
        raise ValueError('Invalid recipe ID')
    params = dict(params)
    for key, rule in recipe.get('params', {}).items():
        if key not in params:
            if 'default' in rule: params[key] = rule['default']
            else: raise ValueError('Missing parameter: ' + key)
        value = params[key]
        kind = rule['type']
        if kind in ('str','file','new-file') and not isinstance(value, str):
            raise ValueError('Expected text parameter: ' + key)
        if kind in ('int','float') and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError('Expected numeric parameter: ' + key)
        if kind in ('int','float') and not math.isfinite(value):raise ValueError('Non-finite parameter: '+key)
        if kind == 'int' and not isinstance(value, int): raise ValueError('Expected integer: ' + key)
        if kind in ('point','rect') and (not isinstance(value,list) or len(value)!=(2 if kind=='point' else 4)
                                         or any(not isinstance(x,int) or x<0 for x in value)):
            raise ValueError('Expected integer screen coordinates: '+key)
        if kind == 'file' and not Path(value).is_file(): raise FileNotFoundError(value)
        if replay and kind == 'new-file' and Path(value).exists(): raise FileExistsError(value)
        if kind not in ('str','file','new-file','int','float','point','rect'):
            raise ValueError('Unknown parameter type: '+kind)
        if 'min' in rule and value < rule['min'] or 'max' in rule and value > rule['max']:
            raise ValueError('Parameter out of range: ' + key)
    resolved = bind(recipe, params)
    if not resolved.get('steps'): raise ValueError('Empty recipe')
    ids = [s['id'] for s in resolved['steps']]
    if not all(isinstance(i, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', i) for i in ids):
        raise ValueError('Invalid step ID')
    if len(set(ids)) != len(ids): raise ValueError('Duplicate step IDs')
    for step in resolved['steps']:
        if not step.get('after'): raise ValueError('Each action requires observed postconditions')
    if 'native' in resolved:
        env = resolved['environment']
        native = resolved['native']
        if (resolved.get('app') != 'jianying' or not isinstance(params.get('project'), str) or
                not env.get('project') or env['project'] != params.get('project') or
                env.get('foreground') is not True or env.get('unknown_dialog') is not False or
                not env.get('dpi') or not resolved.get('version') or
                env.get('version') != resolved['version'] or native.get('version') != resolved['version']):
            raise ValueError('Native recipes require a pinned Jianying version, project, DPI and foreground/dialog guards')
        width,height=env['layout']
        if not all(isinstance(n, int) and n > 0 for n in (width, height)):
            raise ValueError('Invalid native layout')
        def point(p):
            if not (len(p)==2 and 0<=p[0]<width and 0<=p[1]<height):raise ValueError('Native point outside window')
        for step in resolved['steps']:
            action=step['action']
            if ('project' in step.get('before', {}) and step['before']['project'] != env['project']):
                raise ValueError('Step changes the bound project')
            if action['op'] not in ('observe','click','right_click','drag','keys','set_text'):raise ValueError('Unknown native operation')
            if 'point' in action:point(action['point'])
            if action['op']=='drag':point(action['to'])
            for fixed in ('version', 'dpi', 'foreground', 'unknown_dialog'):
                if any(fixed in st and st[fixed] != env[fixed] for st in (step.get('before', {}),step['after'])):
                    raise ValueError('Step changes an input guard: '+fixed)
            if action['op'] == 'keys':
                check_keys(action['keys'])
            if action['op'] == 'set_text' and action.get('commit'):
                check_keys(action['commit'])
        reserved = {'version','dpi','layout','foreground','unknown_dialog','unknown_windows','external_focus',
                    'window_title','automation_id','image','image_sha256'}
        for name, probe in native.get('probes',{}).items():
            if (not re.fullmatch(r'[A-Za-z0-9_-]{1,72}', name) or name in reserved or
                    name == 'project' and set(probe) - {'rect','compact','invert','language'}):
                raise ValueError('Invalid or reserved probe name')
            if 'point' in probe:point(probe['point'])
            if 'rect' in probe:
                x,y,right,bottom = probe['rect']
                if not (0 <= x < right <= width and 0 <= y < bottom <= height):
                    raise ValueError('Native probe rectangle outside window')
            if 'template' in probe:
                template = (Path(recipe_dir)/probe['template']).resolve()
                if not template.is_file():raise FileNotFoundError(template)
                probe['template'] = str(template)
    return resolved, params


def matches(actual, expected):
    return all(actual.get(k) == v for k, v in expected.items())


def assert_state(actual, expected):
    differences = {k: {'expected': v, 'observed': actual.get(k)}
                   for k, v in expected.items() if actual.get(k) != v}
    if differences: raise RuntimeError('State mismatch: ' + json.dumps(differences, ensure_ascii=False))


def run_recipe(recipe, params, adapter, output, recipe_dir=ROOT):
    resolved, params = prepare(recipe, params, recipe_dir)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    run_id = uuid.uuid4().hex
    trace = output/'actions.jsonl'
    started = time.perf_counter()
    result = {'schema': 1, 'run_id': run_id, 'recipe_id': recipe['id'],
              'recipe_hash': object_hash(recipe), 'params': redact(params),
              'project': params.get('project'), 'real_device': adapter.real_device,
              'status': 'running', 'created': dt.datetime.now(dt.timezone.utc).isoformat(),
              'version': recipe['version'], 'steps_completed': 0,
              'template_hashes': {k:digest(p['template']) for k,p in resolved.get('native',{}).get('probes',{}).items() if 'template' in p}}
    write(output/'recipe.json', recipe)
    write(output/'result.json', result)
    def log(event):
        with trace.open('a', encoding='utf8') as f:
            f.write(json.dumps(redact(dict(event, run_id=run_id, elapsed=time.perf_counter()-started)), ensure_ascii=False)+'\n')
            f.flush(); os.fsync(f.fileno())
    for step in resolved['steps']:
        action_started = False
        try:
            before = adapter.snapshot(output/(step['id']+'-before'))
            assert_state(before, resolved.get('environment', {}))
            assert_state(before, step.get('before', {}))
            log({'step':step['id'], 'status':'started', 'action':step['action'], 'before':before})
            action_started = True
            adapter.execute(step['action'])
            timeout = min(float(step.get('timeout', 5)), 180)
            deadline = time.monotonic() + timeout
            while True:
                after = adapter.snapshot(output/(step['id']+'-after'))
                # Never resume input after an unknown dialog or a lost focus, even if transient.
                guard_keys = ('version','foreground','unknown_dialog','project','layout','dpi')
                expected={k:step['after'].get(k, resolved['environment'][k])
                          for k in guard_keys if k in resolved.get('environment',{})}
                expected.update(step['after'])
                wait_keys=step.get('wait_for_transition',[])
                if any(k not in ('project','layout') or k not in step['after'] for k in wait_keys):
                    raise ValueError('Only explicit project/layout transitions may settle')
                assert_state(after, {k:expected[k] for k in guard_keys if k in expected and k not in wait_keys})
                if after.get('external_focus'): raise RuntimeError('Focus moved outside the target application')
                if matches(after, expected): break
                if time.monotonic() >= deadline: assert_state(after, expected)
                time.sleep(.15)
            log({'step':step['id'], 'status':'committed', 'after':after})
            result['steps_completed'] += 1
        except Exception as error:
            log({'step':step['id'], 'status':'unknown' if action_started else 'blocked',
                 'error':str(error), 'action':step['action']})
            result.update(status='interrupted', recovery={'step':step['id'], 'error':str(error),
                          'instruction':'Inspect current state before any retry. Do not replay an uncertain insertion.'})
            break
    else: result['status'] = 'complete'
    result.update(seconds=time.perf_counter()-started, trace_sha256=digest(trace))
    write(output/'result.json', result)
    return result


def check_quality(kind, quality, recipe_hash=None):
    if kind == 'audio' and quality.get('listening') not in ('actually-listened-pass','user-approved'):
        raise ValueError('Audio recipe requires actual listening approval')
    if kind == 'visual' and quality.get('visual') not in ('actually-reviewed-pass','user-approved'):
        raise ValueError('Visual recipe requires actual visual review')
    if kind in ('audio','visual'):
        if not recipe_hash or quality.get('recipe_hash')!=recipe_hash:raise ValueError('Quality approval belongs to another recipe')
        output=Path(quality.get('output',''))
        if not output.is_file() or digest(output)!=quality.get('output_sha256'):
            raise ValueError('Quality approval requires unchanged accepted output')
        if not quality.get('confirmation_source'):raise ValueError('Quality approval needs a specific observation/user confirmation source')


def verify_receipts(recipe, paths, recipe_dir=ROOT):
    if not recipe.get('native'): raise ValueError('Promotion requires a native recipe')
    if recipe.get('exploratory'): raise ValueError('Exploratory actions need semantic postconditions before promotion')
    receipts = []
    for path in paths:
        path = Path(path); r = read(path); trace = path.parent/'actions.jsonl'
        if not trace.is_file() or digest(trace) != r.get('trace_sha256'):
            raise ValueError('Changed or missing trace')
        if not r.get('real_device'): raise ValueError('Promotion requires real device receipts')
        if r.get('status') != 'complete': raise ValueError('Incomplete run')
        if r.get('recipe_hash') != object_hash(recipe): raise ValueError('Recipe changed after execution')
        if r.get('version') != recipe['version']: raise ValueError('Version mismatch')
        events = [json.loads(line) for line in trace.read_text(encoding='utf8').splitlines()]
        resolved,params=prepare(recipe,r.get('params',{}),recipe_dir,replay=False)
        templates = {k:digest(p['template']) for k,p in resolved.get('native',{}).get('probes',{}).items() if 'template' in p}
        if templates != r.get('template_hashes', {}):raise ValueError('Native template changed')
        if r.get('project')!=params.get('project') or not r.get('project'):raise ValueError('Receipt project is not bound to parameters')
        expected_events=[(s['id'],status) for s in recipe['steps'] for status in ('started','committed')]
        if [(e['step'],e['status']) for e in events]!=expected_events:raise ValueError('Missing observed steps')
        if r.get('recipe_id')!=recipe['id'] or r.get('steps_completed')!=len(recipe['steps']):raise ValueError('Receipt identity/count mismatch')
        for i,step in enumerate(resolved['steps']):
            before,after=events[2*i:2*i+2]
            if before.get('run_id')!=r['run_id'] or after.get('run_id')!=r['run_id']:raise ValueError('Trace belongs to another run')
            if before.get('action')!=redact(step['action']):raise ValueError('Executed action differs from bound recipe')
            expected_before={**resolved.get('environment',{}),**step.get('before',{})}
            expected_after={**resolved.get('environment',{}),**step['after']}
            if not matches(before.get('before',{}),expected_before) or not matches(after.get('after',{}),expected_after):
                raise ValueError('Observed states do not match receipt parameters or recipe')
        receipts.append(r)
    if len({r['run_id'] for r in receipts}) < 2 or len({r['project'] for r in receipts}) < 2:
        raise ValueError('Requires independent native projects/runs')
    return receipts


def catalog(data):
    path = Path(data)/"learning/local-recipes.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS signals
                  (candidate TEXT PRIMARY KEY, kind TEXT, summary TEXT, evidence TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS recipes
                  (hash TEXT PRIMARY KEY, status TEXT, updated TEXT, entry TEXT, reason TEXT)""")
    return db


def capture(kind, summary, evidence, data=DATA):
    candidate = "cand-"+uuid.uuid4().hex
    with closing(catalog(data)) as db, db:
        db.execute("INSERT INTO signals VALUES (?, ?, ?, ?)", (candidate, kind, redact(summary), redact(evidence)))
    return {"status":"candidate", "candidate":candidate}


def find_recipes(task_type, app=None, version=None, query="", data=DATA, limit=3):
    if not (Path(data)/"learning/local-recipes.sqlite3").is_file():
        return []
    with closing(catalog(data)) as db:
        rows = list(db.execute("SELECT entry FROM recipes WHERE status='applied'"))
    found = []
    for row in rows:
        entry = json.loads(row["entry"])
        path = Path(entry["path"])
        try:
            recipe = read(path)
        except (OSError, ValueError):
            continue
        if object_hash(recipe) != entry["recipe_hash"] or recipe["task_type"] != task_type:
            continue
        if app and recipe["app"] != app or version and recipe["version"] != version:
            continue
        haystack = json.dumps(recipe, ensure_ascii=False).casefold()
        score = sum(term.casefold() in haystack for term in query.split())
        found.append(dict(entry, score=score))
    return sorted(found, key=lambda row:(-row["score"], row["id"]))[:limit]


def regression_sources():
    paths = [ROOT/"experience.py", ROOT/"native_recipe.py", ROOT/"native_windows.py", ROOT/"ocr_server.ps1",
             ROOT.parent/"tests/test_recipes.py"]
    return {p.name:digest(p) for p in paths}


def verify_negative_tests(path):
    suite = read(path)
    if (suite.get("failures") != 0 or suite.get("errors") != 0 or suite.get("tests", 0) < 13 or
            suite.get("source_hashes") != regression_sources()):
        raise ValueError("Run the bundled native regression suite for the installed runtime")


def finalize_recipe(recipe_path, run_paths, negative_tests, quality_path=None, data=DATA):
    recipe_path = Path(recipe_path).resolve()
    recipe = read(recipe_path)
    rh = object_hash(recipe)
    with closing(catalog(data)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT * FROM recipes WHERE hash=?", (rh,)).fetchone()
        if old and old["status"] == "applied":
            return dict(json.loads(old["entry"]), status="already-applied")
        candidate = "cand-"+uuid.uuid4().hex
        db.execute("INSERT INTO signals VALUES (?, ?, ?, ?)",
                   (candidate, "evaluation", recipe["id"], str(recipe_path)))
        try:
            receipts = verify_receipts(recipe, run_paths, recipe_path.parent)
            if old and any(dt.datetime.fromisoformat(r["created"]) <= dt.datetime.fromisoformat(old["updated"]) for r in receipts):
                raise ValueError("A rolled back recipe needs fresh runs on two native projects")
            verify_negative_tests(negative_tests)
            quality = read(quality_path) if quality_path else {}
            check_quality(recipe.get("kind", "operation"), quality, rh)
        except (ValueError, OSError, KeyError) as e:
            return {"status":"candidate", "candidate_id":candidate, "reason":str(e)}
        entry = {"id":recipe["id"], "candidate_id":candidate, "recipe_hash":rh, "path":str(recipe_path),
                 "kind":recipe.get("kind","operation"), "version":recipe["version"],
                 "evidence":[str(Path(p).resolve()) for p in run_paths], "quality":quality}
        db.execute("INSERT OR REPLACE INTO recipes VALUES (?, ?, ?, ?, ?)",
                   (rh, "applied", dt.datetime.now(dt.timezone.utc).isoformat(), json.dumps(entry), ""))
        return dict(entry, status="applied")


def deactivate_recipe(recipe, reason, data=DATA):
    rh = object_hash(recipe)
    with closing(catalog(data)) as db, db:
        updated = db.execute("UPDATE recipes SET status=?, updated=?, reason=? WHERE hash=? AND status='applied'",
                             ("rolled_back", dt.datetime.now(dt.timezone.utc).isoformat(), redact(reason), rh))
        return {"status":"rolled_back" if updated.rowcount else "not-applied", "recipe_hash":rh}


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--data', default=str(DATA))
    sub = p.add_subparsers(dest='command', required=True)
    f = sub.add_parser('find'); f.add_argument('--task-type', required=True, choices=TASK_TYPES)
    f.add_argument('--app'); f.add_argument('--version'); f.add_argument('--query', default='')
    v = sub.add_parser('verify'); v.add_argument('--recipe', required=True); v.add_argument('--runs', nargs='+', required=True)
    v.add_argument('--quality'); v.add_argument('--negative-tests')
    c = sub.add_parser('capture'); c.add_argument('--kind', default='success'); c.add_argument('--summary', required=True)
    c.add_argument('--evidence', required=True)
    final=sub.add_parser('finalize');final.add_argument('--recipe',required=True)
    final.add_argument('--runs',nargs='+',required=True);final.add_argument('--negative-tests',required=True)
    final.add_argument('--quality')
    rollback=sub.add_parser('deactivate');rollback.add_argument('--recipe',required=True);rollback.add_argument('--reason',required=True)
    args = p.parse_args()
    if args.command == 'find': result = find_recipes(args.task_type,args.app,args.version,args.query,Path(args.data))
    elif args.command == 'capture': result = capture(args.kind, args.summary, args.evidence, Path(args.data))
    elif args.command == 'finalize':result=finalize_recipe(args.recipe,args.runs,args.negative_tests,args.quality,Path(args.data))
    elif args.command == 'deactivate':result=deactivate_recipe(read(args.recipe),args.reason,Path(args.data))
    else:
        recipe = read(args.recipe); receipts = verify_receipts(recipe,args.runs,Path(args.recipe).resolve().parent)
        check_quality(recipe.get('kind','operation'),read(args.quality) if args.quality else {},object_hash(recipe))
        if args.negative_tests:
            verify_negative_tests(args.negative_tests)
        result = {'status':'verified','runs':len(receipts),'recipe_hash':object_hash(recipe)}
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__': main()
