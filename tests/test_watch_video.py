import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import watch_video as watch


def cli(*args, env=None):
    return subprocess.run([sys.executable, "-B", "-X", "utf8", str(SCRIPTS / "watch_video.py"), *map(str, args)],
                          encoding="utf-8", capture_output=True, env=env)


class ReaderErrors(unittest.TestCase):
    def test_missing_tools_and_invalid_time(self):
        result = cli("example.mkv", "--output", ".", env={**os.environ, "PATH": ""})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ffmpeg is required", result.stderr)
        for start, end in [("00:60:00", "4000"), ("nan", "5"), ("4", "4"), ("4", "2")]:
            result = cli("example.mkv", "--output", ".", "--start", start, "--end", end)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)

    def test_public_failure_and_missing_downloader(self):
        with patch.object(watch.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "yt-dlp is required for public links"):
                watch.public_video("https://example.invalid/test", Path("."), {}, [], True)
        with patch.object(watch, "tool", return_value="yt-dlp"), \
                patch.object(watch, "run", side_effect=ValueError("Unsupported URL")) as runner:
            with self.assertRaisesRegex(ValueError, "Unsupported URL.*local video"):
                watch.public_video("https://example.invalid/test", Path("."), {}, [], True)
        command = runner.call_args.args[0]
        self.assertIn("--ignore-config", command)
        self.assertNotIn("--cookies-from-browser", command)

    def test_public_playlist_rejected_before_media_download(self):
        info = subprocess.CompletedProcess([], 0, '{"_type":"playlist"}', "")
        with patch.object(watch, "tool", return_value="yt-dlp"), patch.object(watch, "run", return_value=info) as runner:
            with self.assertRaisesRegex(ValueError, "single finished video"):
                watch.public_video("https://example.invalid/list", Path("."), {}, [], True)
        self.assertEqual(runner.call_count, 1)

    def test_caption_language_and_cue_overlap(self):
        meta = {"subtitles": {"en": [], "live_chat": []}, "automatic_captions": {"zh-Hans": []}}
        self.assertEqual(watch.subtitle_language(meta), (0, True, "zh-Hans"))
        content = "WEBVTT\n\nidentifier\n00:00.250 --> 00:01.250 align:start\n时间线\n第二行\n\n"
        content += "00:01.250 --> 00:03.400\n下一个\n"
        self.assertEqual(watch.read_cues(content, 1.0, 1.25),
                         [{"start": 0.25, "end": 1.25, "text": "时间线\n第二行"}])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg and ffprobe on PATH")
class LocalReader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.base = Path(temp.name)
        cls.media = cls.base / "示范.mkv"
        srt = cls.base / "原字幕.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:00,500\n窗口前\n\n"
                       "2\n00:00:00,500 --> 00:00:01,700\n剪映关键帧\n\n"
                       "3\n00:00:02,001 --> 00:00:02,500\n窗口后\n", encoding="utf-8")
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error",
                        "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=4:duration=3",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-i", str(srt),
                        "-map", "0:v", "-map", "1:a", "-map", "2:s", "-vf", "select='not(between(n,3,4))'",
                        "-fps_mode", "vfr", "-c:v", "ffv1", "-c:a", "pcm_s16le", "-c:s", "srt",
                        "-metadata:s:s:0", "language=zho", str(cls.media)], check=True)
        cls.sidecar = cls.media.with_suffix(".zh-CN.vtt")
        cls.sidecar.write_text("WEBVTT\n\n00:00.000 --> 00:01.500\n不透明度\n", encoding="gb18030")

    def read(self, *args):
        result = cli(self.media, "--output", self.base, *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = Path(result.stdout.strip())
        return path.parent, json.loads(path.read_text(encoding="utf-8"))

    def test_vfr_frames_pixels_chinese_tracks_and_audio_window(self):
        out, manifest = self.read("--start", "00:00:00.51", "--end", "2.001", "--frames", 4, "--audio")
        frames = manifest["frames"]
        self.assertEqual([f["time"] for f in frames], [1.25, 1.5, 1.75])
        self.assertEqual(frames[0]["target"], 0.51)
        expected = subprocess.run(["ffmpeg", "-v", "error", "-i", str(self.media), "-map", "0:v",
                                   "-vf", "select='eq(n,3)'", "-frames:v", "1", "-c:v", "png",
                                   "-f", "image2pipe", "-"], capture_output=True, check=True).stdout
        self.assertEqual((out / frames[0]["file"]).read_bytes(), expected)
        by_kind = {track["kind"]: track["cues"] for track in manifest["captions"]}
        self.assertEqual([c["text"] for c in by_kind["embedded"]], ["剪映关键帧"])
        self.assertEqual(by_kind["sidecar"], [{"start": 0, "end": 1.5, "text": "不透明度"}])
        with wave.open(str(out / manifest["audio"]["file"]), "rb") as wav:
            self.assertAlmostEqual(wav.getnframes() / wav.getframerate(), 2.001 - .51, places=3)
        self.assertEqual(set(manifest["tools"]), {"ffprobe", "ffmpeg"})
        self.assertFalse(manifest["gaps"], manifest["gaps"])

    def test_explicit_captions_sparse_window_and_repeated_runs(self):
        options = ("--start", ".51", "--end", "0.99", "--frames", "1",
                   "--subtitle", self.sidecar)
        out, first = self.read(*options)
        second_dir, second = self.read(*options)
        self.assertNotEqual(out, second_dir)
        self.assertEqual(first["frames"], [])
        self.assertTrue(any("No source frame" in g for g in first["gaps"]))
        self.assertEqual([t["kind"] for t in first["captions"]], ["sidecar"])
        self.assertIsNone(second["audio"])

    @unittest.skipUnless(shutil.which("yt-dlp"), "requires optional yt-dlp on PATH")
    def test_downloader_over_http_without_external_network(self):
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        source = self.base / "public-sample.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(self.media), "-map", "0:v", "-c:v", "mpeg4",
                        "-t", "0.5", str(source)], check=True)
        with ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(self.base))) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}/{source.name}"
            try:
                result = cli(url, "--output", self.base, "--frames", 1)
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
        self.assertEqual(manifest["source"]["url"], url)
        self.assertEqual(Path(manifest["source"]["file"]).read_bytes(), source.read_bytes())
        self.assertEqual(manifest["frames"][0]["time"], 0)
        self.assertIn("yt-dlp", manifest["tools"])
        self.assertFalse(manifest["has_audio_stream"])


if __name__ == "__main__":
    unittest.main()
