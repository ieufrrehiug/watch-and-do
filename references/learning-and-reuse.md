# 把本次操作变成可复验的经验

按目标选择 analysis（观察）、video（成片）、web-code（可运行的交互）、tutorial（跟做）、install（安装）或 reverse（辨认已有工程和格式）。场景开工先查[本机场景经验](scene-learning.md)。其他路线查已安装的[社区经验](community-learning.md)。社区卡只有文字建议，不会成为桌面输入。

## 查找同环境配方

在技能根目录运行。当前平台没有 PowerShell 时，直接用 Python 入口。

```bash
python scripts/experience.py find --task-type video --app jianying --version 11.8.0.14778 --query "gain"
python scripts/experience.py find-captures --task-type video --query "剪映"
```

find 最多返回三项已经验证且内容摘要仍匹配的配方。用应用版本、正确工程、前台窗口、DPI、布局、可见控件与源文件再核对。find-captures 返回最近最多十条匹配的个人项目记录，包括失败和回退。详细截图和动作轨迹留在自己的工程或个人数据目录内。

## 项目做完怎样留一条可复用经验

以剪映视频项目为例，在工程内保留一份验收记录，写明实际检查了哪一段、看见或听见什么。按[工具记录格式](tools-and-skills.md)填写 `project-tools.json`，每项用途只写实际操作。下面用的是示例结论，运行时换成这一次的观察。原生保存重开后查看画面属于 frames，查草稿数据属于 program，真实试听才用 listening。

```bash
python scripts/experience.py capture --task-type video --kind success --basis frames --summary "重开草稿后字幕仍位于画面下方" --check "重开成片工程，在两个指定时刻逐帧检查字幕位置" --tools ./work/project-tools.json --evidence ./work/verification.md
```

命令把本机证据文件位置、SHA-256 和工具记录连同结论写入个人库，返回 `candidate`。未通过填 `--kind failure`，回退填 `rollback`。只在本机使用时，结项到此即可。下次用 `find-captures` 找回记录，再把 ID 传给 `community-preflight --capture-id` 核对环境。旧的三参数 `capture --kind … --summary … --evidence …` 仍可记录自由文本候选信号。

分享时，先确认署名、公开权利与现有分享选择。参照[公开卡示例](community-card.example.json)单写一份脱敏表单，换成实际 task、kind、topics、method、check、basis、evidence、environment、id 和 author。省去 `tools`，让下面的命令从该次结项记录取回工具；有冲突会提示核对。把 `CANDIDATE_ID` 换成刚返回的值。

```bash
python scripts/community_memory.py community-draft --from-capture CANDIDATE_ID --input ./work/public-form.json --out ./work/card.json
python scripts/community_memory.py community-share-preview --input ./work/card.json
```

导出时会重验本地证据摘要，公开正文只含作者填写的公开表单和工具记录。逐条批准模式可用 `community-queue-review --all` 在本机看完整待审稿。独立复现者另记自己使用的工具和验收结果，维护者审核入包后，其他设备可用 `community-find` 检索，按 `community-preflight --installed-id` 核对其本机条件。详见[社区投稿和复现](community-learning.md)。

## 剪映专业版桌面配方

[音量操作示例](native-audio-gain.example.json)展示选择音频段、核对界面裁片及选中边缘、输入增益、用微调按钮提交并回读的步骤。示例按一个 Windows 剪映专业版版本、DPI 和布局填写。将副本放入自己的工程，按本机实际观察调整窗口、控件位置和参数。准备自己工程里的面板与音轨标签裁片。程序检查输入的 dB 值，实际试听另行验收。发布包没有预激活的原生配方。

params.json 按示例中 params 的定义填写。project 为已打开草稿的准确标题，clip_name 为音频段标识，clip_point 是可点击位置，label_rect 是左上/右下边界，border 是选中态取色点，clip_template、gain_panel_template 是自己截取的两张图的绝对路径，gain 为目标 dB 值。所有点按窗口原生像素。模板字段中固定的相对路径以配方目录为基准。仅对已经核对过的自有配方执行输入。

```bash
python scripts/native_recipe.py --recipe ./work/gain.json --params ./work/params.json --dry-run
python scripts/native_recipe.py --recipe ./work/gain.json --params ./work/params.json --out ./work/run-one
```

预检只需 Python 3.11+。实际操作需 Windows、对应版本的本机剪映专业版、Pillow 12+、uiautomation、psutil、pywin32 及配方语言的 Windows OCR。直接使用已经打开的目标窗口；需要明确将目标置前时加 `--activate`。运行目录必须是新目录。每一步保存前后状态、控件读数、局部截图、耗时和摘要。切换到其他窗口、弹出未知对话框、项目不符或布局变化时停止输入，保留 interrupted 结果。可能已执行的操作先检查时间线再决定如何恢复。

## 验证、启用和回退

从一份真实工程运行，再在另一份独立工程副本运行相同版本的配方。在原生软件保存并重开，核对实际输出与各段状态。用本版自带测试生成当前运行时代码的回归记录，然后提供两份 result.json。执行后用 find 回读。

```bash
python tests/test_recipes.py --report ./work/regression.json
python scripts/experience.py finalize --recipe ./work/gain.json --runs ./work/run-one/result.json ./work/run-two/result.json --negative-tests ./work/regression.json
python scripts/experience.py deactivate --recipe ./work/gain.json --reason "New replay failed on matching layout"
```

verify 使用同样的 `--recipe`、`--runs`、`--negative-tests` 先做独立核对。两次真实运行、项目、步骤、模板与轨迹摘要必须匹配。kind 为 visual 或 audio 时，另用 `--quality ./work/accepted.json` 提供 recipe_hash、实际输出的绝对路径 output、output_sha256、confirmation_source 和 visual（actually-reviewed-pass 或 user-approved）或 listening（actually-listened-pass 或 user-approved）。保留自动指标、实际看到或听到的结果与用户意见。

通过后 SQLite 事务同时登记启用状态及证据位置。配方被更改后，旧摘要不会被查出。失败的已启用回放会停用对应摘要，再次启用需要回退后取得的新证据。deactivate 管理本机推荐记录。保留原生工程备份以便恢复实际编辑。

## 本地存储和旧运行时

默认个人数据目录见 [README](../README.md)。`WATCH_AND_DO_DATA` 或前置参数 `--data` 可以指定目录。新配方登记在 `learning/local-recipes.sqlite3`。过去使用独立运行时的用户可设置 `WATCH_AND_DO_RUNTIME`，或将其绝对目录写在个人目录的 `.config/watch-and-do/runtime-root.txt`，然后通过 `scripts/experience.ps1` 查找、验证、写回该运行时原来的配方记录。优先级依次为环境变量、用户配置、随包运行时。场景与社区数据由各自入口管理。
