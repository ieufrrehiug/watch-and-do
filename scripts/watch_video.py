"""Extract local, source-timed evidence for an agent to inspect with its media tools."""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import wave


def run(command, *, cwd=None):
    result = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
                            encoding="utf-8", errors="replace")
    if result.returncode:
        detail = result.stderr.strip().splitlines()[-3:]
        raise ValueError(f"{Path(command[0]).name} failed. " + " ".join(detail))
    return result


def tool(name, versions):
    path = shutil.which(name)
    if not path:
        role = "public links" if name == "yt-dlp" else "local media extraction"
        raise ValueError(f"{name} is required for {role}. Install it on PATH and retry.")
    flag = "--version" if name == "yt-dlp" else "-version"
    versions[name] = run([path, flag]).stdout.splitlines()[0]
    return path


def seconds(value):
    value = str(value).strip().replace(",", ".")
    if value.startswith("."):
        value = "0" + value
    if not re.fullmatch(r"(?:\d+:){0,2}\d+(?:\.\d+)?", value):
        raise ValueError(f"Invalid time {value!r}. Use seconds or HH:MM:SS.sss.")
    parts = [float(x) for x in value.split(":")]
    if any(p >= 60 for p in parts[1:]):
        raise ValueError(f"Invalid clock time {value!r}.")
    total = sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
    if not math.isfinite(total):
        raise ValueError("Time must be finite.")
    return total


def subtitle_language(info):
    choices = []
    for key in ("subtitles", "automatic_captions"):
        for lang in info.get(key) or {}:
            if lang == "live_chat":
                continue
            base = lang.lower().split("-")[0]
            rank = 0 if base in ("zh", "cmn", "yue") else 1 if base == "en" else 2
            choices.append((rank, key == "automatic_captions", lang))
    return min(choices) if choices else None


def public_video(url, directory, versions, gaps, fetch_captions):
    ytdlp = tool("yt-dlp", versions)
    common = [ytdlp, "--ignore-config", "--no-playlist", "--playlist-end", "1",
              "--encoding", "utf-8", "--no-progress", "--socket-timeout", "20"]
    try:
        metadata = run([*common, "--flat-playlist", "--dump-single-json", "--", url])
        info = json.loads(metadata.stdout)
        if info.get("_type") in ("playlist", "multi_video") or info.get("is_live"):
            raise ValueError("Select a single finished video.")
        download = run([*common, "--quiet", "--output", "source.%(ext)s",
                        "--print", "after_move:filepath", "--", url], cwd=directory)
        media = Path(download.stdout.strip().splitlines()[-1])
        media = (directory / media).resolve()
        if media.parent != directory or not media.is_file():
            raise ValueError("Downloader produced no local media file.")
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Public video unavailable. {exc} Supply a local video or excerpt.") from exc
    chosen = subtitle_language(info) if fetch_captions else None
    if chosen:
        _, automatic, lang = chosen
        try:
            run([*common, "--skip-download", "--write-auto-subs" if automatic else "--write-subs",
                 "--sub-langs", re.escape(lang), "--sub-format", "vtt/srt",
                 "--output", "source.%(ext)s", "--", url], cwd=directory)
        except ValueError as exc:
            gaps.append(f"Online captions unavailable. {exc}")
    return media, {"url": url, "extractor": info.get("extractor_key"), "id": info.get("id"),
                   "downloaded_caption_kind": ("automatic" if chosen[1] else "publisher") if chosen else None}


CUE = re.compile(r"^\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d+)\s*-->\s*"
                 r"((?:\d+:)?\d{1,2}:\d{2}[.,]\d+)(?:\s.*)?$")


def read_cues(content, start, end):
    cues = []
    for block in re.split(r"\n[ \t]*\n", content.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip("\ufeff \n\t").split("\n")
        if lines[0].startswith(("NOTE ", "NOTE\t")) or lines[0] in ("NOTE", "STYLE", "REGION"):
            continue
        for i, line in enumerate(lines):
            match = CUE.fullmatch(line)
            if match:
                begin, finish = map(seconds, match.groups())
                body = "\n".join(lines[i + 1:]).strip()
                if begin < end and finish > start and finish > begin and body:
                    cues.append({"start": begin, "end": finish, "text": body})
                break
    return cues


def read_sidecar(path):
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("gb18030")


def caption_tracks(media, streams, explicit, ffmpeg, start, end, gaps):
    tracks = []
    if explicit:
        sidecars = [explicit]
    else:
        prefix = media.stem.casefold() + "."
        sidecars = sorted(p for p in media.parent.iterdir() if p.is_file()
                          and p.name.casefold().startswith(prefix) and p.suffix.lower() in (".srt", ".vtt"))
    for path in sidecars:
        try:
            if path.suffix.lower() not in (".srt", ".vtt"):
                raise ValueError("Expected SRT or WebVTT.")
            text = read_sidecar(path)
            tracks.append({"kind": "sidecar", "source": str(path.resolve()), "cues": read_cues(text, start, end)})
        except (ValueError, OSError) as exc:
            gaps.append(f"Could not read subtitle {path.name}. {exc}")
    for s in streams:
        if explicit or s["codec_type"] != "subtitle":
            continue
        try:
            result = run([ffmpeg, "-v", "error", "-nostdin", "-copyts", "-start_at_zero",
                          "-protocol_whitelist", "file,pipe", "-i", str(media), "-map", f"0:{s['index']}",
                          "-c:s", "srt", "-f", "srt", "pipe:1"])
            tracks.append({"kind": "embedded", "stream": s["index"], "language": s.get("tags", {}).get("language"),
                           "cues": read_cues(result.stdout, start, end)})
        except ValueError as exc:
            gaps.append(f"Could not extract subtitle stream {s['index']} ({s['codec_name']}). {exc}")
    if not any(t["cues"] for t in tracks):
        gaps.append("No readable timed captions in this window. Speech has not been transcribed.")
    return tracks


def sample_frames(ffmpeg, media, stream, start, end, count, directory, gaps):
    frames = []
    seen = set()
    for i in range(count):
        target = start + (end - start) * i / count
        name = directory / f"frame-{i + 1:03}.png"
        # Seeking is input-relative. Preserve the original timeline shifted to the container start.
        filt = f"select='gte(t,{target:.9f})*lt(t,{end:.9f})',showinfo"
        try:
            result = run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "info", "-ss", f"{target:.9f}",
                          "-t", f"{end - target + 1:.9f}", "-copyts", "-start_at_zero",
                          "-protocol_whitelist", "file,pipe", "-i", str(media),
                          "-map", f"0:{stream}", "-vf", filt, "-frames:v", "1", "-fps_mode", "vfr",
                          "-update", "1", str(name)])
            match = re.search(r"\bn:\s*0\s+pts:\s*(-?\d+)\s+pts_time:", result.stderr)
            base = re.search(r"config in time_base:\s*(\d+)/(\d+)", result.stderr)
            if not (name.is_file() and match and base):
                raise ValueError("No source frame starting in the remaining window.")
            pts = int(match[1])
            actual = pts * int(base[1]) / int(base[2])
            if not start - 1e-9 <= actual < end:
                raise ValueError("Decoded timestamp outside the requested window.")
            if pts in seen:
                name.unlink()
                continue
            seen.add(pts)
            frames.append({"file": name.name, "target": target, "time": actual})
        except ValueError as exc:
            name.unlink(missing_ok=True)
            gaps.append(f"Frame at or after {target:.6f}s unavailable. {exc}")
    return frames


def audio_clip(ffmpeg, media, stream, start, end, directory, gaps):
    name = directory / "audio.wav"
    try:
        run([ffmpeg, "-nostdin", "-v", "error", "-ss", str(start), "-protocol_whitelist", "file,pipe",
             "-i", str(media), "-map", f"0:{stream}", "-t", str(end - start), "-af", "aresample=async=1:first_pts=0",
             "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(name)])
        with wave.open(str(name), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
        if duration <= 0:
            raise ValueError("No audio samples.")
        return {"file": name.name, "stream": stream, "duration": duration}
    except (ValueError, wave.Error, EOFError) as exc:
        name.unlink(missing_ok=True)
        gaps.append(f"Audio extraction failed. {exc}")
        return None


def extract(args):
    start = seconds(args.start)
    end = seconds(args.end) if args.end is not None else None
    if end is not None and end <= start:
        raise ValueError("End time must be after start time.")
    if not 1 <= args.frames <= 64:
        raise ValueError("Choose between 1 and 64 frames per run.")
    versions, gaps = {}, []
    ffmpeg = tool("ffmpeg", versions)
    ffprobe = tool("ffprobe", versions)
    online = args.source.lower().startswith(("http://", "https://"))
    media = None if online else Path(args.source).expanduser().resolve()
    if media is not None and not media.is_file():
        raise ValueError(f"Local video was not found: {media}")
    out = args.output.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="watch-", dir=out))
    source = {}
    if online:
        media, source = public_video(args.source, directory, versions, gaps, not args.subtitle)
    source.update(file=str(media), size=media.stat().st_size, mtime_ns=media.stat().st_mtime_ns)
    probe = json.loads(run([ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_format",
                            "-show_streams", "-of", "json", str(media)]).stdout)
    streams = probe["streams"]
    video = next((s for s in streams if s["codec_type"] == "video" and
                  not s.get("disposition", {}).get("attached_pic")), None)
    if not video:
        raise ValueError("This source has no video stream to inspect.")
    container = probe["format"]
    if video.get("duration") not in (None, "N/A"):
        duration = (float(video.get("start_time") or 0) - float(container.get("start_time") or 0)
                    + float(video["duration"]))
    elif "matroska" in container["format_name"] and video.get("tags", {}).get("DURATION"):
        duration = seconds(video["tags"]["DURATION"]) - float(container.get("start_time") or 0)
    else:
        duration = float(container.get("duration") or 0)
    if duration > 0:
        end = min(end, duration) if end is not None else duration
    if end is None:
        raise ValueError("Duration unavailable. Supply an explicit --end time.")
    if end <= start:
        raise ValueError("Start time is outside the video.")
    frames = sample_frames(ffmpeg, media, video["index"], start, end, args.frames, directory, gaps)
    tracks = caption_tracks(media, streams, args.subtitle, ffmpeg, start, end, gaps)
    sound = next((s for s in streams if s["codec_type"] == "audio"), None)
    audio = None
    if sound is None:
        gaps.append("No audio stream found.")
    elif args.audio:
        audio = audio_clip(ffmpeg, media, sound["index"], start, end, directory, gaps)
    manifest = {"format": "watch-and-do.video-evidence.v1", "source": source, "tools": versions,
                "window": {"start": start, "end": end}, "video_stream": video["index"], "frames": frames,
                "captions": tracks, "has_audio_stream": sound is not None, "audio": audio, "gaps": gaps}
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Local video or a single public video URL supported by yt-dlp")
    parser.add_argument("--output", type=Path, required=True, help="Parent of the new evidence directory")
    parser.add_argument("--start", default="0", help="Inclusive source time, seconds or HH:MM:SS.sss")
    parser.add_argument("--end", help="Exclusive source time, default is end of video")
    parser.add_argument("--frames", type=int, default=8, help="Number of evenly spaced sample targets (1–64)")
    parser.add_argument("--audio", action="store_true", help="Extract the selected window as a stereo listening WAV")
    parser.add_argument("--subtitle", type=Path, help="Read this SRT/VTT instead of automatic subtitle selection")
    args = parser.parse_args()
    try:
        print(extract(args))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Video evidence unavailable. {exc}\n")


if __name__ == "__main__":
    main()
