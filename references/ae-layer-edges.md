# 分层实拍、透孔与贴镜的边缘连续性

设计时先标出源画框、实体轮廓、开口和前后遮挡关系。源素材里截断的实体，应选择完整摄影姿态或让截断处在输出画框外。摄影背景使用足够的真实余量，位移、缩放、旋转之后检查四角。运动和透视置换前在源层延伸摄影边界，并让颜色与透明度在同一坐标空间内采样。

一个实体轮廓只合成一次。空景修补在确定不透明的实体下方收口；把可见背景一起挖走会沿轮廓露出修补色。需要通过的孔直接沿用摄影源的透明开口，内景遮罩延伸进实体下面。两层使用同一父级、孔心、源帧、亚像素变换及采样时刻。带透明度的素材须明确 straight / premultiplied 解释。先合成相交表面，再对需要的整体施加方向模糊或光晕。亮边应来自真实轮廓。

遇到从一个姿态叠化到另一个的转场，先检查整体曝光或显影。整体叠化可用连续透明度；局部置信度只处理实际遮挡，避免把一张平整表面切成小岛。背景中新露出的区域优先用同一机位群的真实摄影供体复原。

导出后以源帧率检查整条时间线，另检查画框四边、开口内外与快切相邻帧。用户截图作定位与回归样例，不充当全片抽查范围。用脚本生成候选，再实际回看候选附近的数帧；保留预期的家具线、地砖、镜头硬切和有意的青色边光。无可信对应原片时用单片模式，并以孔内/关闭前景的验层或覆盖通道补证。一个视觉样本的验收不能代替换物验证。

```powershell
python scripts/ae-edge/seam_qa.py render.mp4 --reference reference.mp4 --out qa-paired
python scripts/ae-edge/seam_qa.py render.mp4 --out qa-new-object --cuts 52,107
python scripts/ae-edge/review_strips.py qa-paired --previous previous.mp4
python scripts/ae-edge/review_strips.py qa-paired --recheck revised.mp4 --previous previous.mp4 --out original-regions-reviewed
python scripts/ae-edge/review_strips.py qa-new-object
python scripts/ae-edge/test_seam_qa.py --out qa-regression
```

复看所有达到阈值的区域。用 review_strips 在原始像素下对照参考、修前及修后相邻三帧。缩小播放和全片平均值容易掩盖只出现一帧的拼块。若一条栏杆、树线或硬轮廓在相邻姿态间断成小岛，沿整段运动补选局部实拍角度，按同一平面连续跟踪。把补片限在可靠区域、保留前景遮挡。用 --recheck 复验上一版的所有可疑位置，再单独看关键帧之间的画面。如果补片在关键帧位置干净、隔帧仍漏出旧底，优先使用同机位连续拍摄的短局部素材，跟随可见轮廓，检查启用与退出。若异常恰好出现在方向模糊关键帧上，检查实拍补片是否已经带有快门曝光；用同一局部遮罩限制顶层模糊的影响。完成原生重渲染后再次扫描整片，同时看镜头切口、叠化与穿孔全过程。

时间相关参数按本片测量。脚本依赖 NumPy、OpenCV、Pillow，优先使用当前 Python 环境。已有独立安装时可设置 WATCH_AND_DO_OPENCV_PATH 指向合适的安装位置。hole_guard.interior_matte 使用源 alpha 和真实孔内种子生成承接遮罩；种子不在孔内、孔连到原图边框时会报告错误。将通过的全片程序检查、在原分辨率看过的画面、已知偏差与真人反馈分别记录。
