"""Build or verify the publicly distributable skill ZIP from its reviewed manifest."""
import argparse
from pathlib import Path, PurePosixPath
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "watch-and-do-pilot-v1.zip"


def sources():
    names = (ROOT / "release-files.txt").read_text(encoding="utf-8").splitlines()
    if not names or len(names) != len(set(names)) or "release-files.txt" not in names:
        raise ValueError("Invalid or incomplete release-files.txt")
    result = {}
    for name in names:
        rel = PurePosixPath(name)
        path = (ROOT / rel).resolve(strict=True)
        if (not rel.parts or rel.is_absolute() or ":" in name or "\\" in name or ".." in rel.parts
                or not path.is_relative_to(ROOT) or not path.is_file() or path == BUNDLE):
            raise ValueError(f"Unexpected release path: {name}")
        result["watch-and-do/" + name] = path
    return result


def check(bundle, files):
    with zipfile.ZipFile(bundle) as archive:
        if sorted(archive.namelist()) != sorted(files):
            raise ValueError("The ZIP file list differs from release-files.txt")
        for name, source in files.items():
            if archive.read(name) != source.read_bytes():
                raise ValueError(f"The ZIP is outdated: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check file names and bytes without writing")
    parser.add_argument("--output", type=Path, default=BUNDLE)
    args = parser.parse_args()
    files = sources()
    if args.check:
        check(args.output, files)
    else:
        with tempfile.NamedTemporaryFile(dir=args.output.parent, suffix=".zip", delete=False) as tmp:
            temp = Path(tmp.name)
        try:
            with zipfile.ZipFile(temp, "w") as archive:
                for name, source in sorted(files.items()):
                    info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
            check(temp, files)
            temp.replace(args.output)
        finally:
            temp.unlink(missing_ok=True)
    print(f"Verified {len(files)} files in {args.output.name}")


if __name__ == "__main__":
    main()
