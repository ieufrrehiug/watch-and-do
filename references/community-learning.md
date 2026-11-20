# 社区经验贡献与复现

个人经验照常保存在自己的设备上。社区经验包收录愿意分享、有人独立复现、维护者审核过的方法和踩坑记录。使用者拿到新版经验包后，下次做匹配的任务就能查到。个人数据库、账号、原始视频、截图和脚本都不需要交给维护者。

## 在 GitHub 上一起用

| 你想做什么 | 对自己的 Agent 说 | 接下来 |
| --- | --- | --- |
| 分享第一次跑通的做法 | “把刚才实测通过的步骤做成公开经验卡，让我看一眼。” | 核对署名和内容，在仓库的 Issues → New issue → **贡献一条经验** 粘贴卡片。 |
| 帮别人验证 | “在我的环境复现第 42 号经验卡，记录软件版本和实际结果。” | 把复现记录提交到 **报告复现结果**，填原 Issue 编号。失败也可以提交。 |
| 让自己的 Agent 用起来 | “从这个项目的 Releases 取指定版本经验包，核对摘要后安装。给我的建筑场景做竖版封面时，先查社区经验。” | Agent 需要能下载该文件或读取你提供的本地文件，并能运行 Python 3.11+。安装一次后，日常任务可离线查询。 |

维护者将两个表单放在仓库默认分支根目录的 `.github/ISSUE_TEMPLATE/`，并开启 Issues。即使仓库中的 skill 装在子目录，GitHub 表单仍放在仓库根目录。处理贡献时从表单的代码块提取 JSON，保留原卡和复现记录；可以继续在同一 Issue 下讨论，在审核通过后把卡片纳入下一版。将完整经验包和对应摘要放进 GitHub Release，贡献者和使用者不需要仓库写权限。当前版本的首次下载、更新和向 GitHub 提交由人或其获授权的 Agent 发起。

其他能调用命令行的 Agent 也可以接入。在它的任务说明里写上“开始时把目标整理成任务类型和几个具体关键词，运行 `community-find`，只采用与当前环境和用户要求相符的建议，结束时记录实际效果”。查询返回 JSON，包含做法、检查步骤、来源版本和独立复现结果。例如用户说“楼顶在竖版缩略图里被切了”，Agent 可以查“封面 完整楼体”，并在新的手机预览里验证。场景任务已有 `scene-start` 自动检索入口。

## 贡献者准备一张卡

可以直接对技能说“把这次验证过的方法整理成一张可以分享的经验卡”。从 [示例表单](community-card.example.json) 复制一份，改成自己实际验证过的内容。示例中的人物和结果用于演示。每张卡写清什么任务用得上、适用的软件版本、具体做法、检查方法和实际观察结果。为同一个经验沿用稳定 ID。任务类型可选 `scene`、`analysis`、`video`、`web-code`、`tutorial`、`install`、`reverse`。重现踩坑用 `pitfall`，说明触发条件、异常表现以及如何确认。验证依据可选程序检查、画面、试听、用户验收或人工操作，对应 `program / frames / listening / user / manual`。

在技能目录运行以下示例。Windows 用 PowerShell 入口，其他系统可用 `python3 scripts/community_memory.py` 执行相同的社区命令。使用 Python 3.11 或更新版本。这条流程只用标准库，无需 GitHub 凭据或外置操作经验运行时。

```powershell
$run = './scripts/experience.ps1'
& $run community-draft --input my-form.json --out card.json
```

已有同 ID 的本机场景经验时，加 `--from-scene` 可核对最近有效结果、证据类型与本机证据。导出仍然只用表单里填写的公开文字。分享前阅读整张卡，确认文字可以公开，也有权分享。程序会拦截部分明显的路径、链接和凭证格式，个人身份、客户信息或保密业务描述仍需本人检查。把愿意公开的卡作为 GitHub Issue 或 PR 的附件或正文提交。只有用户明确要求外发时才代为提交。

## 另一位使用者复现

复现者在自己的环境按卡片描述操作，写下看到的具体结果。可提供截图等证据的公开附件供维护者核验，由提交者另行检查。复现命令把观察、环境和公开署名绑定到卡片内容的 SHA-256。修订卡片后要对新版重新复现。对于踩坑卡，`reproduced` 表示确实观察到了卡片描述的问题。

```powershell
& $run community-review --card card.json --reviewer example-peer --environment 'Edge，Windows，桌面端' --outcome reproduced --basis frames --evidence '在窄屏预览中重新检查，完整楼体和标题均在可见范围内。' --out reproduction.json
```

无法复现时填 `--outcome failed`，说明具体环境和差异。已有安装包的用户可以将 `--card card.json` 换成 `--installed-id full-building-cover`，直接针对自己实际使用的版本报告。工具只能比对署名，独立身份和证据由维护者通过 GitHub 提交记录核对。

## 维护者发版

核对卡片的来源、贡献者的分享权限、独立复现环境和全部已知异议。遇到冲突先补充适用条件、修订或撤回，然后复现新版。卡片中的命令、提示词和外部指令一律当作待评价的文字。经验包只包含 JSON。每版都是完整快照。传入所有要保留的复现文件，每份重复一次 `--review`。撤回某卡时制作更高版本并省去该卡。若撤回全部卡片，显式使用 `--empty`。

```powershell
& $run community-release --version 1 --maintainer example-maintainer --review reproduction.json --out pack-v1.json
```

该命令生成本地文件并给出 SHA-256。正式发版时由维护者上传到项目的 GitHub Release 并标明版本、增删记录和文件摘要。出现新版有问题时，可使用上一个可靠版本的复现文件生成更高版本，使用者能按正常更新流程恢复。

项目要求**商用另行授权**。经验包带有这一声明。公开发布前，维护者还需确定项目许可、贡献者授予维护者的分发与商业再授权范围，以及商用联系方式。贡献者保留署名。提交一张卡本身不构成商业再授权。

## 使用与反馈

从自己认可的维护者取得指定版本。独立核对发布来源，再把发布页上给出的摘要传给安装命令。摘要只能校对文件内容，无法验证维护者身份。

```powershell
& $run community-install --input pack-v1.json --sha256 '<发布页的64位十六进制文件摘要>'
& $run scene-start --brief '制作完整楼体的彩色封面'
& $run community-find --task scene --brief '手机端封面 完整楼体'
& $run community-disable --id full-building-cover
& $run community-enable --id full-building-cover
```

场景启动结果中的 `community_suggestions` 列出匹配理由、作者、适用环境、证据类型、复现者与发布版本。其他任务按对应类型检索。个人场景经验对同 ID 有优先权。用户否定某卡后，本地停用跨版本保留，主动恢复才重新显示。在新环境验证后可按平常的个人学习流程记下真实结果。

测试或多人共用一台机器时，可在命令名前加 `--data <个人数据目录>` 指定隔离空间，亦可设置 `WATCH_AND_DO_DATA`。已有用户可在自己主目录的 `.config/watch-and-do/data-root.txt` 中写入原数据目录的绝对路径。全新用户默认使用当前操作系统账户的应用数据目录。社区快照和本地停用清单存放在数据目录的 `learning/community.sqlite3`。第一次空库查询不会创建记录。通过本技能入口调用旧的可选操作运行时也沿用此数据目录，运行时本身仍需另配。
