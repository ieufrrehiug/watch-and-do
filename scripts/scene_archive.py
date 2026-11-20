"""Content-addressed fallback for explicitly listed, distributable project files."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tempfile
import zipfile


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(256 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(name):
    parts=PurePosixPath(name).parts
    if not parts or "\\" in name or name.startswith("/") or any(
            p in {"..","."} or ":" in p or p.rstrip(" .")!=p or p.upper().split(".")[0] in
            {"CON","PRN","AUX","NUL",*(f"COM{i}" for i in range(1,10)),*(f"LPT{i}" for i in range(1,10))}
            for p in parts):
        raise ValueError(f"Unsafe ZIP member: {name}")
    return PurePosixPath(*parts).as_posix()


def members(archive):
    result={}
    folded=set()
    for item in archive.infolist():
        name=safe_name(item.filename)
        if stat.S_ISLNK(item.external_attr >> 16) or name.casefold() in folded:
            raise ValueError(f"Duplicate or link in archive: {name}")
        folded.add(name.casefold())
        if not item.is_dir():
            result[name]=item
    return result


def install_zip(folder, source=None, files=None):
    folder.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=folder,suffix=".tmp",delete=False) as temp:
        staged=Path(temp.name)
    try:
        if source:
            shutil.copyfile(source,staged)
        else:
            with zipfile.ZipFile(staged,"w",compression=zipfile.ZIP_DEFLATED) as out:
                for name,path in sorted(files.items()):
                    info=zipfile.ZipInfo(name, date_time=(2000,1,1,0,0,0))
                    info.compress_type=zipfile.ZIP_DEFLATED
                    with path.open("rb") as src,out.open(info,"w") as dest:
                        shutil.copyfileobj(src,dest)
        with zipfile.ZipFile(staged) as archive:
            members(archive)
            if archive.testzip() is not None:
                raise ValueError("ZIP failed CRC verification")
        digest=file_hash(staged); path=folder/(digest+".zip")
        if path.exists():
            if file_hash(path)!=digest:
                raise ValueError(f"Archived package changed: {path}")
        else:
            os.replace(staged,path)
        return digest,path
    finally:
        staged.unlink(missing_ok=True)


def preserve(dbfile, manifest):
    form=json.loads(manifest.read_text(encoding="utf-8-sig"))
    root=(manifest.parent/Path(form["root"])).resolve()
    if not root.is_dir() or not isinstance(form.get("project"),str) or not form["project"].strip():
        raise ValueError("Expected a project name and an existing project root")
    selected=form.get("files")
    if not isinstance(selected,list) or not selected:
        raise ValueError("Explicit nonempty list of files required")
    files={}
    for raw in selected:
        name=safe_name(raw)
        path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Missing or external selected file: {name}")
        files[name]=path
    hashes={name:file_hash(path) for name,path in files.items()}
    repo=dbfile.parent/"scene-archives"; entries=[]; outputs=[]
    package=form.get("source_zip")
    if package:
        source=(root/safe_name(package)).resolve()
        if not source.is_relative_to(root):raise ValueError("Source archive outside project")
        digest,path=install_zip(repo,source=source)
        outputs.append({"kind":"source","sha256":digest,"archive":str(path),"original":str(source)})
        with zipfile.ZipFile(path) as archive:
            contents=members(archive)
            for name in sorted(files.keys() & contents.keys()):
                with archive.open(contents[name]) as member:
                    actual=hashlib.file_digest(member,"sha256").hexdigest()
                if actual!=hashes[name]:
                    raise ValueError(f"Source archive and current file differ: {name}")
                entries.append((str(files.pop(name)), actual, digest, name, str(source), "source"))
    if files:
        digest,path=install_zip(repo,files=files)
        outputs.append({"kind":"selected-files","sha256":digest,"archive":str(path),"original":str(root)})
        with zipfile.ZipFile(path) as archive:
            for name,original in files.items():
                with archive.open(name) as member:
                    actual=hashlib.file_digest(member,"sha256").hexdigest()
                if actual!=hashes[name]: raise ValueError(f"File changed during archive: {name}")
                entries.append((str(original),actual,digest,name,str(root),"selected-files"))
    db=sqlite3.connect(dbfile,timeout=10)
    try:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS archived (original TEXT NOT NULL, digest TEXT NOT NULL, package TEXT NOT NULL, member TEXT NOT NULL, origin TEXT NOT NULL, kind TEXT NOT NULL, PRIMARY KEY(original,digest,package))")
            db.executemany("INSERT OR IGNORE INTO archived VALUES(?,?,?,?,?,?)",entries)
    finally:db.close()
    return {"project":form["project"],"indexed_files":len(entries),"packages":outputs}


class ArchiveLookup:
    def __init__(self,dbfile):
        self.repo=dbfile.parent/"scene-archives"; self.available={};self.used={};self.restored={}
        self.verified={}; self.cache={}; self.recovered=[]
        if dbfile.is_file():
            db=sqlite3.connect(dbfile.as_uri()+"?mode=ro",uri=True)
            try:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='archived'").fetchone():
                    for original,digest,package,member,origin,kind in db.execute("SELECT * FROM archived ORDER BY kind DESC"):
                        self.available.setdefault((original,digest),[]).append((package,member,origin,kind))
            finally:db.close()

    def unpack(self,path,digest,member,expected):
        # Cache only inside the scene memory data directory. A module recovered
        # from a source ZIP sees its siblings, source notices and package lock.
        cache_root=self.repo.parent/"scene-restored"; cache_root.mkdir(exist_ok=True)
        if digest in self.restored:
            verified=self.restored[digest]/member
            return verified if verified.is_file() and file_hash(verified)==expected else None
        dst=cache_root/digest
        target=dst/member
        def unchanged(directory):
            if not directory.is_dir() or directory.is_symlink():return False
            with zipfile.ZipFile(path) as archive:
                for name,item in members(archive).items():
                    saved=directory/name
                    if (not saved.is_file() or saved.is_symlink()
                            or not saved.resolve().is_relative_to(directory.resolve())
                            or saved.stat().st_size!=item.file_size):
                        return False
                    with archive.open(item) as data:
                        if file_hash(saved)!=hashlib.file_digest(data,"sha256").hexdigest():return False
            return (directory/member).is_file() and file_hash(directory/member)==expected
        for prior in [dst,*cache_root.glob(digest+"-*")]:
            if unchanged(prior):
                self.restored[digest]=prior
                return prior/member
        temp=Path(tempfile.mkdtemp(prefix=".recover-",dir=cache_root))
        try:
            with zipfile.ZipFile(path) as archive:
                for name,item in members(archive).items():
                    f=temp/name;f.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open(item) as src,f.open("wb") as dest:shutil.copyfileobj(src,dest)
            checked=temp/member
            if not checked.is_file() or file_hash(checked)!=expected:return None
            if not dst.exists():
                try:
                    temp.rename(dst)
                    self.restored[digest]=dst
                    return dst/member
                except OSError:
                    if not dst.exists():raise
            if unchanged(dst):
                self.restored[digest]=dst
                return target
            # Never overwrite an already edited recovery directory.
            alternate=cache_root/(digest+"-"+temp.name.removeprefix(".recover-"))
            temp.rename(alternate);self.restored[digest]=alternate
            return alternate/member
        finally:
            if temp.exists() and temp.name.startswith(".recover-") and temp.resolve().parent==cache_root.resolve():
                shutil.rmtree(temp)

    def resolve(self,ref):
        original,expected=ref["path"],ref["sha256"];key=(original,expected)
        if key in self.cache:return self.cache[key]
        try: local_ok=Path(original).is_file() and file_hash(Path(original))==expected
        except OSError:local_ok=False
        result=original if local_ok else None
        for package,member,origin,kind in self.available.get(key,[]):
            path=self.repo/(package+".zip")
            try:
                if package not in self.verified:
                    self.verified[package]=path.is_file() and file_hash(path)==package
                if not self.verified[package]:continue
                self.used[package]={"path":str(path),"sha256":package,"original":origin,"kind":kind}
                if not local_ok:
                    found=self.unpack(path,package,member,expected)
                    if found is None:continue
                    result=str(found)
                    self.recovered.append({"original":original,"path":result,"sha256":expected,"package_sha256":package,"member":member})
                break
            except (OSError,PermissionError,zipfile.BadZipFile,ValueError):
                continue
        self.cache[key]=result
        return result
