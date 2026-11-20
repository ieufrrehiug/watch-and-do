# 记录工具，换一台设备复用

每次实做后，在个人经验和新的公开卡里填写 `tools`。写出本次实际用过的软件、影响结果的库、可查到的版本，以及实际调用的技能。搜索到、装在电脑上、或看起来可以替代的技能，都不能记成已用。另一个人复现时另记自己的工具，再按原卡标准给出结果。

```json
{
  "software": [{"name": "剪映专业版", "version": "unknown"}],
  "skills": ["jianying-local"],
  "capabilities": ["subtitle-placement"],
  "uses": [
    {"kind": "software", "name": "剪映专业版", "purpose": "重开草稿并逐帧检查字幕位置。"},
    {"kind": "skill", "name": "jianying-local", "purpose": "建立可编辑的字幕轨并设置入点与出点。"}
  ]
}
```

这是剪映字幕项目的格式示例。软件版本从本次运行记录或实际使用的应用核对；版本不详时保留软件名并将 `version` 填为 `"unknown"`。技能写实际调用的名称，例如 `["jianying-local"]`。明确未使用写 `"none"`，无法从历史材料确定写 `"unknown"`。新的项目结项在 `uses` 中给每个具名工具写一个用途，名称与上面一致；同一个工具做了几步可合在一句。用途将进入公开表单，请用可分享的操作描述，个人目录、客户名、工程名和日志另存本机。旧卡可省略 `uses`。能力填简短任务词；内置替代路线识别 `subject-cutout`（静态图抠像）、`video-matte`（视频蒙版）、`window-capture`（录窗）和 `browser-rendering`（浏览器渲染）。

## 查到经验后

```powershell
python scripts/community_memory.py community-preflight --installed-id ae-gdigrab-black-compositor
python scripts/community_memory.py community-preflight --card my-card.json --inventory local-inventory.json
python scripts/community_memory.py community-preflight --scene-id my-personal-lesson
python scripts/community_memory.py community-preflight --capture-id CANDIDATE_ID
python scripts/community_memory.py community-preflight --capability subject-cutout --check "缩放到 100%，在黑底白底检查发丝、边缘光晕、透明区域和主体完整性" --basis frames
```

运行输出列出原软件和技能、本机观测依据、版本对照、可尝试的替代步骤与原验收条件。默认检查运行中的 Python、部分已知程序的 PATH / Windows 常用安装位置，以及当前账户的 Codex 和 Agent 技能目录。可重复传 `--skill-root DIR` 指定其他技能根。插件或当前会话提供的技能，以实际技能清单为准。工具文件存在只表明找到了入口；试做还需确认当前会话可以调用、相应功能可用。命令只读取本机记录，不执行卡中的命令，不安装软件或技能。

若常规检查没有找到图形软件、某个具体版本或插件技能，请先从当地软件“关于”、项目锁文件、当前会话工具清单等实际核对，再把观测作为 `--inventory` 的本地 JSON 输入。多条可同时传入，例如下面的**格式示例**，请换成实际观测。软件与技能的 `kind` 分别是 `software` 和 `skill`，状态是 `found` 或经指定范围核对的 `missing`。CLI 的 `not-detected` 表示检查范围内没有找到证据。库存和运行输出可能带本机路径，留在本机。

Windows 上的剪映专业版和 Adobe After Effects 还会查询当前用户及本机的 32 位、64 位卸载登记和 App Paths，并核对指向的实际主程序。仅找到卸载登记时显示 `registered`，建议在本机核实路径。版本来自该登记的 DisplayVersion；例如登记为 25.6.6 时，原经验中的 25.6.6x4 构建仍显示待核。启动软件和实做验收需另外验证。

```json
[
  {"kind": "software", "name": "GIMP", "status": "found", "version": "3.0", "evidence": "打开应用后从关于对话框读出版本。", "capabilities": ["subject-cutout"]},
  {"kind": "skill", "name": "cutout-workflow", "status": "missing", "evidence": "本次会话的技能清单和本机技能目录均没有此项。"}
]
```

复用抠图经验时，如果缺原软件或技能，可用本机已有 GIMP 的前景选择加图层蒙版，或 Photoshop 的主体选择加图层蒙版。使用原图同一尺寸，重新打开带透明度的导出文件，在深浅两种背景检查发丝、轮廓和孔洞，再按原卡的全部标准判断。动态视频还需要检查跨帧边缘和遮挡处的连续性，可在 Blender 中制作有关键帧的蒙版。只找到软件或生成透明文件不能登记为复现成功。[GIMP 前景选择](https://docs.gimp.org/3.0/en/gimp-tool-foreground-select.html) · [Photoshop 图层蒙版](https://helpx.adobe.com/photoshop/desktop/create-masks/layer-masks/add-layer-masks.html) · [Blender 动态蒙版](https://docs.blender.org/manual/en/5.3/movie_clip/masking/introduction.html)

若替代方式需要其他配套技能，先查看当前会话已装技能的说明与依赖；同一能力的本机软件或技能可以通过库存中的 `capabilities` 参与匹配。返回的候选会把已有本机证据的方案排在前面；仍需自己执行样例。无匹配时，按目标能力查可获取的软件或技能，列出候选、来源和需要的条件，在用户明确要求安装时再进入安装流程。

## 记录新的证据

视频、教程等项目通过 `capture --tools project-tools.json` 在结项时记录软件和技能。个人场景在 `scene-learn` 清单的 `tools` 键填写同一对象。生成公开卡时，分别用 `community-draft --from-capture CANDIDATE_ID` 或 `community-draft --from-scene` 配合 `--input` 和 `--out` 从个人记录带出工具。表单可省去整个 `tools`，填写了冲突值则需先核对。直接撰写公开卡时，将对象放入卡片的 `tools` 键。独立复现用 `community-review --tools my-tools.json` 指定复现者自己的软件、版本、技能和用途，配合 `--card`、`--reviewer`、`--environment`、`--outcome`、`--basis`、`--evidence`、`--out` 参数。详细步骤见[项目结项和经验复用](learning-and-reuse.md)。

旧卡仍按原始内容核对 SHA-256。45 条随包卡的历史工具补注来自原项目的实测脚本、制作记录、实际依赖或已有卡片，按原卡内容摘要单独匹配。检索结果中的 `tools_source` 给出出处类型；无法对应的旧卡显示 `unrecorded`。软件与技能记录不齐全时继续保留未知项。

已逐条核对的个人旧记录，可以在本机数据目录的 `learning/scene-tool-profiles.json` 保存私有对应关系，供 `scene-start` 和 `community-preflight --scene-id` 读取。文件格式为 `{"format":"watch-and-do.local-seed-tools.v1","links":{"个人记录摘要":"对应原始种子卡摘要"}}`。个人记录摘要覆盖当时的完整详情及其中的证据摘要。只有核过这次私有实做与该种子使用同一工具链时才建立关联。同名记录、更改后的修订及其他设备上的独立复现不会按 ID 自动套用。此文件属于个人数据，不随技能分发或投稿。
