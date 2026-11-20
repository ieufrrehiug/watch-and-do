# 制作工具、依赖和来源

核心场景、社区和本机操作记录使用 Python 3.11+ 标准库。MIDI 生成也可单独运行。下面是制作路线选择的外部工具，按需在自己的环境配置。其程序、模型、字体、音色库、音乐和剪映资源均由各自权利人提供，并适用各自条款。

| 用途 | 可用工具 | 本包提供的入口 |
| --- | --- | --- |
| 观看教程、采样关键画面、读取字幕 | FFmpeg 与 ffprobe；支持的公开链接另需 yt-dlp | scripts/watch_video.py |
| 分析视频、音轨和编码 | FFmpeg 与 ffprobe，程序可在 PATH 中找到 | scripts/verify_video.py |
| 生成配乐 | MIDI 仅需 Python；渲染 WAV 使用 FluidSynth、授权 SF2 与 FFmpeg | scripts/compose_music.py |
| 合成边缘、透孔与逐帧候选复查 | NumPy、opencv-python-headless（或含 cv2 的 OpenCV）、Pillow | scripts/ae-edge/ |
| 剪映可观察操作 | Windows、本机剪映专业版、Pillow 12+、uiautomation、psutil、pywin32、Windows PowerShell 和指定 OCR 语言 | scripts/native_recipe.py 与 scripts/ocr_server.ps1 |
| 实际制作/导出 | 用户选择的 HyperFrames、After Effects、剪映、Blender 或其他编辑器 | 对应路线保留可编辑源和独立导出检查 |

FFmpeg、FluidSynth 和音色库按官方发布及随附许可获取。可选择自己的 SF2。 [FFmpeg](https://ffmpeg.org/) · [FluidSynth](https://github.com/FluidSynth/fluidsynth) · [GeneralUser GS](https://www.schristiancollins.com/generaluser.php)

既有独立配方运行时曾使用 agent-playbook 0.4.2 (commit be7a9d7d17593abd8cf029d51c87dbd5b445351e, MIT) 管理候选和验证。本包的内置登记、查询和回退由 Python SQLite 实现。可选择通过本机已配置的旧运行时读取其历史记录，保留所用上游程序附带的版权和许可。 [agent-playbook](https://github.com/zhaono1/agent-playbook)

本包的 Windows 配方使用自己的动作检查、WinRT OCR 和窗口定位代码。可选的外部剪映工程适配器有独立许可；若使用对应上游，保留适配器 MIT 署名（luoluoluo22 / chaohutongg-max）及所含 pyJianYingDraft 的 Apache-2.0 许可（GuanYixuan）。本包没有复制这些第三方源码。 [剪映适配器](https://github.com/chaohutongg-max/codex-jianying-skill/tree/45cc6da0c93896d8076ab431ff6a45abc560bfca) · [pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft)

本包不携带第三方账号、视频、模板截图、会员特效或已验证的私人操作轨迹。使用当地授权的素材自行建立项目、采集模板和运行证据。
