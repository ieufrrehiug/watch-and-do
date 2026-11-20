# 等到空闲再分享

做作品时，Agent 只把已经验证、核对过署名和公开权限的脱敏文字卡或复现报告交给本机队列。默认攒够 **3 条**，或最早一条已等 **24 小时**，就可以在空闲时投递。每条各自成为一个候选 Issue，方便独立复现、审核和撤回。达到门槛后重新使用电脑，后面的条目会等到下次空闲。

| 本机分享选择 | 收集经验时 | 到了处理时间 |
| --- | --- | --- |
| 自动分享 | 合格卡片直接入队 | 后台按卡片署名使用已登录的 GitHub 账号发送 |
| 逐条批准 | 保存完整的待审文字，可关闭会话后再看 | Agent 在自然停顿时集中展示目的地和每张卡。用户可以一次选几张、跳过几张，其余留待以后 |
| 仅本机或跳过分享 | 继续使用个人经验和公共经验 | 清除未发送的正文和待审草稿 |

改选任何其他模式都会清除上个模式的草稿和待发正文。已经发往 GitHub 的请求可能仍会完成，公开 Issue 可以在 GitHub 上另行处理。已提交的摘要和 Issue 号保留在本机，供再次遇到相同卡片时去重。收件结果不明的请求也保留摘要，以便日后重新授权时查回执。

## 在任务中收集

每次技能开始时运行 `community-sharing --begin`，由返回值决定是否需要首次询问。三种设置沿用 `--set auto`、`--set review`、`--set private`，跳过用 `--skip`。形成可分享的文字后运行：

```sh
python scripts/community_memory.py community-share-preview --input card.json
python scripts/community_memory.py community-queue
```

`queue_status` 为 `queued` 表示已写入本机，为 `awaiting-approval` 表示已保存待审稿，为 `already-submitted` 表示已有投递回执。Agent 收到 `ready: true` 后继续当前工作；发送由队列处理。`community-queue` 离线列出待发摘要、待审数量、回执和后台运行条件。等待中的正文存放在个人数据目录的 `learning/community.sqlite3`。数据库沿用 `WATCH_AND_DO_DATA`、`--data` 和已有分享选择。

## 一次看一组，逐张决定

在当前工作告一段落、用户有空看时运行下列第一条。只要达到 3 条或 24 小时，就返回成熟的一组待审稿。用户主动说“现在给我看”时可以加 `--all` 提前查看。向用户展示每张完整正文、区别和公开目的地；用户可以用序号选择，Agent 将序号映射回各自的精确摘要。

```sh
python scripts/community_memory.py community-queue-review
python scripts/community_memory.py community-queue-review --approve SHA_A --approve SHA_C --skip SHA_B
```

将示例中的 SHA 换成对应的 64 位摘要。省略的卡留在待审区；选择的任一摘要已失效，整组选取均不生效。相同作者、同一经验 ID 的待审稿改写后需要查看新内容。已到期的一组即使只批准一张，这张也可在下次空闲时投递。用户单独查看某张卡并批准后，也可以沿用 `community-share-preview --input card.json --confirmed-sha256 SHA`。

## 后台发送如何运行

自动投递使用当前账户已经登录的 GitHub CLI（`gh`），要求它可在 PATH 中运行、能向官方仓库创建 Issue，且账号与卡片作者或复现者一致。工具只调用非交互式 `gh api`；本机库不保存令牌。未配置 CLI 时卡片继续留在队列；配置后于下次技能开始时恢复。只使用聊天产品内 GitHub 连接器的账户，如要启用此后台发送器，也需在运行技能的机器上配置 CLI。[GitHub CLI 安装](https://cli.github.com/) · [gh api 手册](https://cli.github.com/manual/gh_api)

在支持的系统上，第一张已授权的待发卡会唤醒一个独立的后台 Python 进程，后续入队沿用同一个。默认每 60 秒检查一次，连续 5 分钟没有桌面输入才处理。Windows 读取当前交互会话的最近输入时间，macOS 读取 HID 空闲时间，Linux 的 X11 桌面使用已安装的 `xprintidle`。取不到空闲时间就继续等待。这里的桌面空闲仅指没有输入，长时间渲染可能仍在进行。进程交由所在宿主管理，队列排空后退出；关机、注销或宿主回收子进程后，下次 `community-sharing --begin` 或有已授权卡入队时恢复。

有可靠任务空闲回调的 Agent 可以设置环境变量 `WATCH_AND_DO_QUEUE_WORKER=off` 关闭自动进程，在每次空闲回调中调用：

```sh
python scripts/community_memory.py community-queue-tick --host-idle
```

使用 `--host-idle` 表示宿主能保证本次回调期间处于空闲。需要逐条感知键鼠活动时省去此参数。也可以在已有后台运行环境中主动启动 `community-queue-worker`，由它读取本机桌面空闲信号。两个发送入口均接受 `--batch-size 3 --max-age-hours 24 --idle-seconds 300`，后台进程另接受 `--poll-seconds 60`。待审列表的门槛可以通过 `community-queue-review --batch-size 3 --max-age-hours 24` 调整。自定义门槛时由宿主统一传参。技能不安装开机服务。

## 断网和重复投稿

每次投递先检查账号，在官方仓库分页查询该账号已打开和已关闭的 Issue，比较现有 JSON 正文的完整摘要。有相同内容就登记原 Issue 号；其他情况重新核对当前授权与空闲状态，再创建 Issue。每张卡在同一份本机库中只能由一个后台进程持有投递权。发送成功后只留摘要和回执。

断网、账号不符或权限错误会保留待发卡，间隔从 1 分钟逐步延长到最多 1 小时。创建请求发出后如果响应丢失，下次空闲会先核对 GitHub 的记录。一直查不到回执时，`community-queue` 会显示 `awaiting-github-receipt`。此时可以对照该账号已关闭及已打开的 Issue，确认之前的请求确实未发布，再运行 `community-queue-retry --sha256 SHA`。重新投递前仍会检查远端。
