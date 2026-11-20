# 看懂就做 · Watch and Do

让 Agent 从参考视频里提取可验证的做法，用来搭 3D 场景、制作和修改短片，并在下一个项目里复用。公开安装包包含制作流程、场景记忆、媒体检查与社区投稿工具，随包附 45 张经验卡（40 张场景、5 张视频）。每个人的项目、素材和学习记录保存在自己的设备上。

## 两分钟试一次

下载仓库 ZIP 并解压，或运行以下命令。需要 Python 3.11 或更新版本，基本检索和社区命令使用标准库。制作时根据所选经验检查软件和 Skill。

```sh
git clone https://github.com/ieufrrehiug/watch-and-do.git
cd watch-and-do
python scripts/scene_memory.py scene-start --brief "微缩建筑 手机选层"
python scripts/community_memory.py community-find --task video --brief "AE 合成窗口 录屏黑屏"
python -B -m unittest discover -s tests -p "test_*.py"
```

支持目录型 Skills 的 Agent 可以将仓库作为一个名为 `watch-and-do` 的技能目录加载。其他能调用 Python 的 Agent 可以直接调用以上入口，按 JSON 里的 `method` 尝试，用 `check` 检查当前作品。查询按任务类型和关键词匹配，可用更具体的词重新查找。[经验卡数据](seeds/cards.json) · [技能入口](SKILL.md)

## 让 Agent 看一段剪映教程

可以直接说「用 watch-and-do 看这段剪映教程，照着做第 3 到 6 秒的效果，给我一个能继续编辑的草稿」。从技能目录也可以单独试读一段本地视频：

```sh
python scripts/watch_video.py tutorial.mp4 --output evidence --start 3 --end 6 --frames 5
```

包内自带视频读取脚本。装好 FFmpeg（含 ffprobe）后，Agent 可以打开带时间点的画面，核对菜单、参数和效果变化。传入支持的公开视频链接还需 yt-dlp。讲解依赖声音时，可提供字幕，或用本地转写工具处理提取的音频。复现可编辑剪映工程还需要兼容的剪映专业版和能操作它的工具，例如 `jianying-local`。收工时把读视频、编辑、验收各步实际用的软件、版本和 Skill 写入同一条经验，下一位使用者能据此检查自己的环境。

## 能验证到什么程度

首发卡的 `source` 为 `maintainer-seed`。36 张依据程序或数值检查，7 张依据画面对照，2 张依据原项目用户反馈。公开测试用新的参数重做了固定步长、双关节、摆长、逐字入场和细胞滑翔机实验，另测场景、视频和本地停用。独立使用者可以提交成功或失败的具体结果。使用别人的真实作品、不同软件版本或不同设备复验时，请写清差异。

## 在另一台电脑复现

选中一条经验后，先看当时实际用了哪些软件、版本、Skill，各自完成哪一步。让 Agent 对照本机检查；例如原工程要求交付可继续编辑的剪映草稿，替代工具还要通过草稿重开这项检查。旧卡缺少的版本或工具会保留为未知。用法见[经验卡依赖检查](references/tools-and-skills.md)和[制作软件与原生格式](references/production-dependencies.md)。

## 在空闲时分享

首次使用可以选「自动分享」「逐条批准」或「只在本机使用」，随时可以更改。前两种都先将已验证、可公开的文字卡放到本机排队。默认攒到 **3 张**，或者最早一张等满 **24 小时**，才在空闲时尝试发送。桌面默认连续 5 分钟没有输入才算空闲。后台自动投递使用已登录、能向该仓库提交 Issue 的 GitHub CLI；接入前，经验会留在队列。逐条模式可以一次查看多张、分别决定分享哪几张。首次选择本机或跳过同样能使用全部制作和检索流程。

投稿会进入 GitHub 的候选 Issue。独立复现和维护者审核通过后才进入正式经验包。用户也可直接使用 [GitHub 投稿表单](https://github.com/ieufrrehiug/watch-and-do/issues/new/choose)。[后台运行条件和队列用法](references/idle-sharing.md) · [复现与入库](references/community-learning.md)

本仓库按非商业条款公开源码。使用受保护的项目内容开展商业业务须事先取得相关权利人的书面授权。第三方软件、模型和素材沿用各自许可。[使用条款](LICENSE.md)
