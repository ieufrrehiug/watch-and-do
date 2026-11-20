"""Render native-pixel detail strips for every high-priority seam candidate."""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw
from seam_qa import cv


def collect(report):
    summary = json.loads((report / "summary.json").read_text("utf8"))
    rows = [json.loads(line) for line in (report / "candidates.jsonl").read_text("utf8").splitlines()]
    if [row["frame"] for row in rows] != list(range(summary["frames"])):
        raise ValueError("The report is missing indexed frames")
    entries = [(row["frame"], hit) for row in rows for hit in row["hits"]
               if hit["score"] >= summary["review_score_threshold"]]
    return summary, entries


def gather(path, requests, summary):
    width, height = summary["dimensions"]
    cap = cv.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError(f"Cannot open {path}")
        if (round(cap.get(cv.CAP_PROP_FRAME_WIDTH)), round(cap.get(cv.CAP_PROP_FRAME_HEIGHT))) != (width, height):
            raise ValueError(f"Native dimensions differ in {path}")
        if abs(cap.get(cv.CAP_PROP_FPS) - summary["fps"]) > 0.02 or round(cap.get(cv.CAP_PROP_FRAME_COUNT)) != summary["frames"]:
            raise ValueError(f"Frame rate or duration differs in {path}")
        tiles = {}
        for frame in range(max(requests, default=-1) + 1):
            if not cap.grab():
                raise ValueError(f"Frame {frame} missing in {path}")
            if frame not in requests:
                continue
            ok, bgr = cap.retrieve()
            if not ok:
                raise ValueError(f"Frame {frame} unavailable")
            for idx, left, top in requests[frame]:
                tile = bgr[top:top+94, left:left+128]
                tiles[(idx, frame)] = Image.fromarray(cv.cvtColor(tile, cv.COLOR_BGR2RGB))
        return tiles
    finally:
        cap.release()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("report", type=Path)
    p.add_argument("--previous", type=Path, help="Previous version of the same composition")
    p.add_argument("--recheck", type=Path, help="Examine the same coordinates in a later render")
    p.add_argument("--out", type=Path, help="Output directory for native-size strips")
    args = p.parse_args()
    if args.recheck and not args.out:
        p.error("--recheck requires --out to preserve the earlier evidence")
    summary, entries = collect(args.report)
    width, height = summary["dimensions"]
    requests = defaultdict(list)
    samples = []
    for idx, (frame, hit) in enumerate(entries):
        l, t, r, b = hit["box"]
        x = max(0, min(width-128, (l+r)//2-64))
        y = max(0, min(height-94, (t+b)//2-47))
        times = [max(0, frame-1), frame, min(summary["frames"]-1, frame+1)]
        samples.append(times)
        for n in set(times):
            requests[n].append((idx, x, y))
    source = args.recheck or Path(summary["video"])
    video = gather(source, requests, summary)
    ref = gather(summary["reference"], requests, summary) if summary["reference"] else None
    prev = gather(args.previous, requests, summary) if args.previous else None
    out = args.out or args.report / "native-review"
    out.mkdir(parents=True, exist_ok=True)
    labels = (["ref"] if ref is not None else []) + (["old"] if prev is not None else []) + ["F-1", "F", "F+1"]
    for start in range(0, len(entries), 8):
        count = min(8, len(entries)-start)
        sheet = Image.new("RGB", (len(labels)*128, count*113), "#171b1e")
        pen = ImageDraw.Draw(sheet)
        for row in range(count):
            idx = start+row
            frame, hit = entries[idx]
            parts = []
            if ref is not None:
                parts.append(ref[idx, frame])
            if prev is not None:
                parts.append(prev[idx, frame])
            parts += [video[idx, n] for n in samples[idx]]
            for col, im in enumerate(parts):
                sheet.paste(im, (col*128, row*113))
            pen.text((2, row*113+94), f"F{frame} {hit['kind']} {hit['box']}   {' / '.join(labels)}", fill="white")
        sheet.save(out/f"proof-{start:04d}.jpg", quality=96)
    index = {"frames": sorted(set(f for f, hit in entries)), "regions": len(entries), "columns": labels,
             "render": str(source.resolve()), "coordinates_from": str(args.report.resolve())}
    (out/"index.json").write_text(json.dumps(index, indent=2), "utf8")
    print(f"{len(index['frames'])} frames, {len(entries)} native candidate strips in {out}")


if __name__ == "__main__":
    main()
