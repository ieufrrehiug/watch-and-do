# 场景开工和收工

本机场景库位于个人数据目录的 `learning/scenes.sqlite3`。可用 `WATCH_AND_DO_DATA` 指定个人数据目录。命令读取用户已有的场景经验和实际文件。随技能调用执行，后台不监视其他项目。

## 开工先取做法

在开始搭建和选择技术栈之前，以当次目标作为 brief 运行一次。先查看当前工程的记录，再用当前参考画面和地点、主体、交互判定适用范围。即使用户这次只说“照着这段视频做”，也把已经观察到的题材和动作写进 brief。根据返回的 method、resources 选择实际要复用的实现，把 check 放入这次首版的实机验收；先看明确标出的旧失败发生在哪里。不同画风借用方法、空间关系或检查，不照搬当地的店名、颜色和交通。

```powershell
python scripts/scene_memory.py scene-start --brief '风雪村庄的客栈，可推门进屋，还有山鹿穿过林间小路'
```

可用 --topics 和 --exclude 分别补充参考画面里实际可见或明确排除的内容。例如 shops、traffic、walkers、animals、atmosphere、explore、sound、weather、urban、waterfront，或历史经验里用过的新主题名。--limit 调整召回数量。若匹配很少，仍按当前参考自主建立方案。数据库中的方法给出可借鉴的局部；实际复用前核对技术、素材授权和新场景尺寸。查找会依 SHA-256 先核对当前文件，无法匹配时查已归档的版本。recovered_files 给出新路径、原路径、整包和成员摘要；unavailable 及 unavailable_resources 指仍需要重新定位或实测的项。

## 收工写回

完成、收到验收意见、失败或回退时，若出现可复用的新决定、反例或对既有做法的修正，在项目工作记录旁生成一份 UTF-8 JSON。命令同时接受单个对象和数组。用同一个稳定 id 修正同一方法，给新主题使用新 id；保存观察到的变化和检查入口。连续提交同一内容只留一项。证据与可用模板必须是实际存在的本地文件。相对路径以这份 JSON 所在目录为准；路径有多个依赖时保留原工程入口或模板依赖说明。私人素材正文、凭据和聊天记录不入库。

```json
{
  "id": "shop-entry",
  "project": "本次场景项目名",
  "topics": ["shops"],
  "keywords": ["门洞", "店铺"],
  "method": "这里填本次实际验证的布置或发现的失败条件",
  "check": "这里填如何从运行成品复查该结果",
  "status": "pass",
  "verification": "program",
  "evidence": ["evidence/shop-walk.json"],
  "resources": ["src/shopfronts.js"]
}
```

```powershell
python scripts/scene_memory.py scene-learn --input './scene-lessons.json'
python scripts/scene_memory.py scene-start --brief '能够从街边走进去的唱片行'
```

示例文件名应改成本次已有的路径。示例 scene-lessons.json 位于工程根目录。确认返回的修订号，并回读下一相似需求能取到这次实际学到的内容，再更新本次工作记录。

status 的 pass 表示所声明的检查通过；fail 会停止推荐这个 id 的旧做法，直到后续带新证据的验证恢复；pending 单独保留待验证观察。verification 区分 program（运行或数字输出）、frames（实际画面比对）、listening（已实际试听）、user（对应用户明确验收或否定）和 observation（尚未证实的观察）。正向做法能附带同一 id 的历史反例。数据库保留每次变化及其来源，查找时核对证据和模板 SHA-256。原有的 capture 与 finalize 继续承担候选信号及原生软件操作配方，场景检索不会将任意记录升级为可自动执行的桌面动作。

## 使验证过的模板在原工程移动后仍可用

对之后确实要复用的实现，从本次已交付、可在本机使用且允许保存的源码包中挑选实际引用的资源，并只选择证明相关的原始输出。凭据、私人素材、未获许可的参考原片、工作目录和依赖缓存都留在原处。完成场景后通常运行以下命令一次，不需要用户重新提示。没有可分发的源码包时，files 显式列出下一次要用的模块及其依赖、说明和许可。

```json
{
  "project": "项目名",
  "root": "..",
  "source_zip": "output/已交付的可编辑工程.zip",
  "files": ["src/shopfronts.js", "街铺模板.md", "evidence/shops-walk.json"]
}
```

将这份清单放在项目的 evidence/ 目录，按实际文件填写，然后运行 `python scripts/scene_memory.py scene-preserve --input './evidence/场景归档.json'`。root 相对于清单，其他路径相对于 root，source_zip 可省略。若源码与已有 ZIP 不一致，先重建并核验实际交付包。完整源码包保留其技术说明、构建依赖清单和第三方许可。只在必要时把清单里包外的证据或独立模块另存成一个小归档。重复提交相同内容复用同一份存档。

场景数据库、按摘要存放的 ZIP 位于同一个 learning/ 目录。原目录更名时，正常的 scene-start 会从已核对摘要的归档恢复，返回可打开的文件和在地的完整源码工作树。可将源码工作树复制到新项目后再修改；已有编辑的恢复副本通过另建的干净目录保留。
