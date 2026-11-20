# Reference video to an editable film

Read for an actual video deliverable or a revision to one. For analysis-only requests, stop after the evidence brief and requested prompts; do not scaffold, install or render.

## Decide from evidence

Reuse verified source/cache and inspect scene midpoints plus transitions. Record what was observed versus stated or requested. A transcript with no recognized speech is not evidence of silence. Music attribution, beat estimates and suggested instrumentation are separate fields: do not turn a creator's “original sound” label into a verified track name or reproduce a song from guessed instruments.

For text, diagrams, knowledge cards and layered silhouettes, prefer deterministic local animation: HTML/SVG + seekable GSAP timelines rendered with HyperFrames. For realistic moving subjects, this route needs suitable footage or generated clips; do not promise procedural geometry will reproduce them. Use available media tools within the user's cost/provider constraints. No paid account, cloud upload or large model download is a prerequisite for knowledge cards.

Keep the source's aspect ratio, voice/no-voice and pacing unless the user changes them. Save editable copy, scene order, palette, assets, frame boundaries and audio cues. Convert absolute musical times to frames once; independently rounding every scene duration accumulates drift. A preview is an intermediate artifact; the requested MP4 is the deliverable.

## Local render route

1. Inspect the project and local Node/FFmpeg/browser. When using HyperFrames, consult its installed CLI help and the documentation for the version used. An existing editor or renderer can provide the same smoke, editable project, final export and checks. Pin the package version and matching official skill release. Install only necessary items. Optional transcription/TTS/Docker failures in `doctor` do not automatically block local rendering. If the skill installer cannot download the repo, an audited copy of the matching npm release's bundled skills is an alternative; record provenance and verify files.
2. First render a 2–3 second smoke film with a representative Chinese title, visible movement and the actual local music pipeline. Check decoded frames and the muxed audio. Reuse this check only when the render/font/audio environment is unchanged.
3. Make one scene per editable composition. Stable composition ids, paused timelines and local assets are essential. Every audio element needs an id; otherwise it may be absent from the mix. Fonts must be local with their licenses. Avoid live network requests and clock-driven/unseeded animation during rendering.
4. Build the full draft, run `check --json` and inspect snapshots from every scene plus scene boundaries. Diagnose failures rather than disabling the audit broadly. Some intentional text over illustrations requires narrowly scoped layout annotations supported by inspected frames.
5. For an explicit request for a file, continue through internal visual review to final rendering without another approval gate. Preview and final render must use the same sources. Use H.264/yuv420p/AAC for an ordinary MP4 unless the user asks otherwise.

Example commands from the project's directory (pinned local package):

```powershell
$env:DO_NOT_TRACK='1'
npm ci
npm run build
npm run check
npm run render
python <skill-dir>/scripts/verify_video.py output/final.mp4 --width 1080 --height 1920 --fps 30 --duration 34.5 --audio --report output/media-check.json
```

## Local music

For a restrained instrumental score, use editable MIDI and a locally installed synth/soundfont, then mix/fade/normalize with FFmpeg. The supplied `scripts/compose_music.py` is a concrete nine-card arrangement example: adapt its notes, chord progression and instrumentation to the brief, not every future video to this song. Run `python scripts/compose_music.py --project <project-dir> --midi-only` for the MIDI. For WAV output, omit `--midi-only`, provide a licensed SF2 with `--soundfont` and select FluidSynth on PATH or with `--fluidsynth`. The project-local SF2 and Windows synth layout are also supported. Keep MIDI, rendered WAV, sources/licenses, BPM and cue positions.

Source soundfonts from the author or official repo, and retain the actual license. GeneralUser GS author: https://www.schristiancollins.com/generaluser.php ; synth: https://github.com/FluidSynth/fluidsynth . Downloading/rendering a local score needs no paid generation account. If a different audio method is already available or requested, use it instead.

## Verify, deliver, resume

- Program checks: dimensions, duration within one frame, frame rate, video/audio streams, complete decoding; music is non-silent and has no clipping. `scripts/verify_video.py` supplies these measurements, not an aesthetic verdict. Inspect intentional dark or held shots before treating black/static detection as a defect.
- Visual checks: actually view decoded frames and movement at multiple times. Check CJK glyphs and font load, readable dwell, safe areas, overlap, scene transitions and the final state before the exclusive end frame. Preserve a contact sheet and a few motion samples.
- Audio checks: distinguish measured loudness/peak/sync from listening to the final muxed audio. If listening is unavailable, report it as pending; successful synthesis or a WAV file is not an audition.
- Delivery: film, preview/contact sheet, editable project, score source/audio, asset/license manifest, repeatable commands, evidence and remaining human checks. Never call only a prompt, webpage, source file or successful render API call a finished video.
- Revision: recover the same work record, edit the requested shot, render its span for comparison, then re-render/re-mux the full output if required. Recheck boundaries and audio timing; leave unrelated content and user edits intact.

Local tested example and environment details belong in the work record, not universal requirements here. Generic defaults must yield to a new user's actual duration, style, topic, soundtrack and tool choice.


## Photographic layers and aperture transitions

For a reference remake or object substitution involving cutouts, aperture reveals, close wipes or tracked plates, use [分层实拍与边缘连续性](ae-layer-edges.md) during compositing and after the full render. Recheck every frame, shot boundaries and the specific reported symptoms.


### 把成片中的物体换成另一件实拍物件

先画清场景关系：同一地点的可识别参照是什么，哪一件是落地实物，哪一层贴镜，遮挡时视线交给谁。用原参考的完整时间轴标出切镜、进出方向、停顿和切后的余速。视觉相似的原片复现与换物成片各自实看和记录。

从新素材中选取合适的姿态和同地底板，保留地面参照、椅脚接触与阴影。窗口边缘、窗口里面的主体和窗口外整件实物分别测量，确定谁遮住谁、何时变小、何时由另一层接位。换物的几何形状可改变，观众能循着同一动作找到主物是验收重点。有实拍遮挡或缺机位时记录合成近似。原片与新版用同一声音时钟并排播放整片；对照剪点、快慢停顿、可见范围与每个快切前后。光流曲线可定位误差，配合同帧审看判断是否达标。


### 立体换物的接地感

如果用户实看仍觉得主体像贴图，单一背景、阴影图层或剪点对齐都不能推翻此次反馈。改用自建几何时，把物件和实际承托面放进同一光照空间，检查多机位视差，站立与侧卧支点，近物遮挡和接触影。对同一姿态单独开关投影来复查。按目标分辨率看运动中的表面和细边，并在摄像机穿环时核对内层主体位置。


### 镜头内借形换景

从同一素材学习“下一镜先借上一镜的轮廓出现”时，先测亮拍、实体出现、退场各自的帧。镜头运动期间先对准背景机位，再把被遮挡的底片与轮廓内容拆开。线性亮幕需保留纹理；成片中出现逐步倾斜的边缘时，同时拟合边缘角度和宽度。交付时用临时合成关闭选定效果，检查该位置显露的底片及未受影响区域。已验证的同素材重建与换主体的实际验收分别记。
