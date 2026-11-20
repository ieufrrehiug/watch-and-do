# 看懂就做 · Watch and Do

把一次制作中实际有用的做法交给下一个人的 AI。这个公开试用版随包提供 45 张首发经验卡，其中场景 40 张、视频 5 张，含 2 条踩坑记录。作者在整理时逐条核对了原项目的记录和证据文件。卡片只包含方法、检验办法、适用环境与结果摘要。原项目的观测数字用于复现时对照，换设备、素材和参数可能得到不同数值。

## 两分钟试一次

下载仓库 ZIP 并解压，或运行以下命令。需要 Python 3.11 或更新版本，检索与自测均使用标准库。

```sh
git clone https://github.com/ieufrrehiug/watch-and-do.git
cd watch-and-do
python scripts/scene_memory.py scene-start --brief "微缩建筑 手机选层"
python scripts/community_memory.py community-find --task video --brief "AE 合成窗口 录屏黑屏"
python -B tests/test_public.py
```

支持目录型 Skills 的 Agent 可以将仓库作为一个名为 `watch-and-do` 的技能目录加载。其他能调用 Python 的 Agent 可以直接调用以上入口，按 JSON 里的 `method` 尝试，用 `check` 检查当前作品。查询按任务类型和关键词匹配，可用更具体的词重新查找。[经验卡数据](seeds/cards.json) · [技能入口](SKILL.md)

## 能验证到什么程度

首发卡的 `source` 为 `maintainer-seed`。36 张依据程序或数值检查，7 张依据画面对照，2 张依据原项目用户反馈。公开测试用新的参数重做了固定步长、双关节、摆长、逐字入场和细胞滑翔机实验，另测场景、视频和本地停用。独立使用者可以提交成功或失败的具体结果。使用别人的真实作品、不同软件版本或不同设备复验时，请写清差异。

## 一起补充

在 [Issues](https://github.com/ieufrrehiug/watch-and-do/issues/new/choose) 选择“贡献一条经验”或“报告复现结果”。同意公开后粘贴你的卡片或复现记录。维护者可把独立复现的卡片发布为新版经验包，使用者可以单独更新，也可以在本机停用某张卡。首发种子卡随这份仓库直接可用。[操作指南](references/community-learning.md)

允许非商业学习、修改和分享，商用请联系维护者另行取得书面授权。[使用条款](LICENSE.md)
