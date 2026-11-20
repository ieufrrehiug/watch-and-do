# Video evidence

## Obtain the right material

1. Identify the exact video or file and the relevant segment. If this is a continuation, check the saved source identity and cached artifacts before opening the link again. Reuse valid material only for the matching source; a caption cache and an audio file cannot substitute for the visuals.
2. Use the installed `watch` workflow for video acquisition, frame extraction, and transcription; resolve its SKILL.md from the active catalog or an installed skills root. Use its documented arguments and existing dependencies. Choose local extraction by default when handling a local or private recording. Use cloud video analysis only when it is already authorized for that material. Local extraction still allows selected evidence to enter the current model context. For a visual-only pass with the installed watch CLI, use its documented `--engine local --no-whisper` options. For a summary-only request, use already available evidence or tools. If needed, check readiness with watch’s documented check-only command (for the current CLI: `setup.py --check`). Skip the first-run setup wizard on that path; do not install a backend or opt into uploads as a side effect of viewing.
3. Pick a small useful window and sample enough frames to establish order, motion, and changes. For a visual effect, see before/during/after and inspect closer frames around transitions. For speech-heavy teaching, start with captions or approved transcription. For a tool name or menu value, inspect readable pixels and reconcile them with speech and the public description. Keep all times relative to the source. For long clips, start with the requested section or a chapter overview, then deepen only where the goal needs it.
4. If direct acquisition fails, use the available browser to inspect the public original post or use a verified local copy. If `watch` is missing, use an available lawful video viewer, existing ffprobe/FFmpeg, and captions as appropriate. Use available access; do not bypass access restrictions or silently switch to a cloud service. An inaccessible video with a usable description or screenshots can support work within that evidence; no usable evidence calls for a valid link, local copy or relevant excerpt.

## Mixed video/photo tutorial posts

For Douyin `/note/` and similar posts, enumerate the original post's demonstration video(s), tutorial images in displayed order, and description separately. Bind every asset to the canonical post ID, its media role, image ordinal or video timecode, and a retained file/hash. Page state may contain recommended videos; never take an arbitrary `play_addr` or the first array item as the reference without matching post identity and visible content. A still cover is not proof of animation.

If the downloader reports an unsupported photo URL, use the public original page and browser evidence rather than repeatedly updating dependencies. Cache usable public assets and preserve the acquisition limitation. Review readable source pixels for effect names and numbers. If text says “范围 50” but the screenshot shows 70, retain both readings and make a controlled comparison; never silently choose or treat UI percentages as normalized API values. Screen-recording duration is not necessarily the source timeline duration, and `00:00:02:10` is a frame timecode whose meaning needs its fps.

## Make a usable brief

- **Observed**: exact source, timestamp or honest range, keyframe reference, visible state/action/result. Use several frames before describing motion.
- **Stated**: what the narrator, captions, or public description claim, with attribution. An empty transcription means no speech was captured, not that no audio or speech exists.
- **Proposed**: implementation, defaults, parameters or version adaptations that the evidence does not establish. If code is cropped, mark reconstructed sections. For a candidate package, transcribe the name or URL and verify it independently.
- **Requested**: user choices, changes, acceptance criteria. Maintain these independently of the source.
- **Gaps**: what could not be inspected, why it matters and what evidence would resolve it. If useful work can continue, proceed on the confirmed portion.

Use the smallest set of evidence that supports the decision. Refer to source timestamps and retained files instead of pasting long transcripts or private material. When tools disagree, compare the original pixels, speech and primary sources; keep unresolved differences visible.
