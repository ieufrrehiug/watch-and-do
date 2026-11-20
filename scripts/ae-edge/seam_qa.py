"""Full-frame video seam QA. Coordinates in the JSONL are native source pixels."""
import argparse
import csv
import json
import math
import sys
import tempfile
from copy import copy
from collections import Counter
from pathlib import Path
import numpy as np

try:
    import cv2 as cv
except ImportError as error:
    import os
    fallback = os.environ.get('WATCH_AND_DO_OPENCV_PATH')
    if not fallback:
        raise ImportError("Install opencv-python-headless in the current Python environment.") from error
    sys.path.insert(0, fallback)
    import cv2 as cv

cv.setNumThreads(2)
KINDS=("thin_line","double_edge","aperture","border","coverage_gap")
SIDES=("top","right","bottom","left")
def tc(f,fps):
    ms=round(f*1000/fps)
    return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}.{ms%1000:03}"

def framespec(text):
    ranges=[]
    for item in text.split(","):
        if not item.strip():continue
        parts=list(map(int,item.split("-")))
        if len(parts)>2 or parts[0]<0 or parts[-1]<parts[0]: raise ValueError("Invalid inclusive frame range: "+item)
        ranges.append((parts[0],parts[-1]))
    return ranges

def roispec(text):
    try:
        frames,box=text.split(":")
        bounds=framespec(frames)
        if len(bounds)!=1:raise ValueError
        x,y,x1,y1=map(float,box.split(","))
        if not (0<=x<x1<=1 and 0<=y<y1<=1):raise ValueError
        return (*bounds[0],x,y,x1,y1)
    except ValueError as e:raise argparse.ArgumentTypeError("Use FIRST-LAST:x0,y0,x1,y1 with normalized corners") from e

def roi_mask(shape,f,items):
    h,w=shape
    m=np.zeros(shape,np.uint8)
    for lo,hi,x,y,x1,y1 in items:
        if lo<=f<=hi:m[int(y*h):math.ceil(y1*h),int(x*w):math.ceil(x1*w)]=1
    return m.astype(bool)

def gray(im):return cv.cvtColor(im,cv.COLOR_BGR2GRAY)
def edgemaps(luma):
    blur=cv.GaussianBlur(luma,(3,3),.65)
    dx=cv.Sobel(blur,cv.CV_32F,1,0,ksize=3);dy=cv.Sobel(blur,cv.CV_32F,0,1,ksize=3)
    return cv.Canny(blur,32,85,L2gradient=True), cv.phase(dx,dy,angleInDegrees=True)%180

def difference(first,second):
    d=cv.absdiff(first,second)
    return np.max(d,axis=2) if d.ndim==3 else d

def ridge(values,radius):
    # A thin stripe has lower-valued neighbours on both sides along its normal.
    k=cv.getStructuringElement(cv.MORPH_ELLIPSE,(radius*2+1,radius*2+1))
    return cv.morphologyEx(values,cv.MORPH_TOPHAT,k)

def aligned_previous(now,old):
    h,w=now.shape
    small=(max(24,round(w*.38)),max(24,round(h*.38)))
    a=cv.resize(now,small,interpolation=cv.INTER_AREA);b=cv.resize(old,small,interpolation=cv.INTER_AREA)
    flow=cv.calcOpticalFlowFarneback(a,b,None,.5,3,13,2,5,1.2,0)
    flow=cv.resize(flow,(w,h));flow[:,:,0]*=w/small[0];flow[:,:,1]*=h/small[1]
    yy,xx=np.indices((h,w),np.float32)
    pred=cv.remap(old,xx+flow[:,:,0],yy+flow[:,:,1],cv.INTER_LINEAR,borderMode=cv.BORDER_REPLICATE)
    return cv.absdiff(now,pred)

def runs(values,gap=2):
    active=cv.morphologyEx(np.uint8(values)[None],cv.MORPH_CLOSE,np.ones((1,gap+1),np.uint8))[0]>0
    z=np.diff(np.r_[False,active,False].astype(int))
    return zip(np.flatnonzero(z==1),np.flatnonzero(z==-1))

def box_overlap(a,b):
    xa,ya,xb,yb=a;xc,yc,xd,yd=b
    area=max(0,min(xb,xd)-max(xa,xc))*max(0,min(yb,yd)-max(ya,yc))
    return area/max(1,min((xb-xa)*(yb-ya),(xd-xc)*(yd-yc)))

def borders(im,ref,allowed,temporal):
    h,w=im.shape[:2];result=[]
    for side,a,r,m,t in zip(SIDES,[im,im[:,::-1].transpose(1,0,2),im[::-1],im.transpose(1,0,2)],
            [None]*4 if ref is None else [ref,ref[:,::-1].transpose(1,0,2),ref[::-1],ref.transpose(1,0,2)],
            [allowed,allowed[:,::-1].T,allowed[::-1],allowed.T],
            [None]*4 if temporal is None else [temporal,temporal[:,::-1].T,temporal[::-1],temporal.T]):
        candidates=[]
        depth=min(24,max(4,round(min(h,w)*.04)),a.shape[0]-2)
        minrun=max(14,round(a.shape[1]*.095))
        # Exact and anti-aliased internal border lines, including a one-pixel strip against the frame.
        for d in range(1,depth+1):
            outside=a[d-1];inside=a[min(d+1,a.shape[0]-1)]
            edge=cv.absdiff(outside,inside).max(axis=1)
            if edge.max()<17:continue
            mask=(edge>=19)&m[d-1]&m[d+1]
            if r is not None:
                refedge=cv.absdiff(r[d-1],r[d+1]).max(axis=1)
                mask&=(edge.astype(np.int16)-refedge.astype(np.int16)>12)&((cv.absdiff(outside,r[d-1]).max(axis=1)>13)|(cv.absdiff(inside,r[d+1]).max(axis=1)>13))
            for x,x1 in runs(mask):
                if x1-x<minrun:continue
                outpatch=a[:d,x:x1]
                spread=float(np.max(np.std(outpatch.reshape(-1,3).astype(np.float32),axis=0)))
                contrast=float(np.median(edge[x:x1]))
                temporal_delta=None if t is None else float(np.median(t[:d,x:x1]))
                if r is None and spread>16 and (temporal_delta is None or temporal_delta<14):continue
                if r is None and spread>32:continue
                strength=(x1-x)/minrun*min(2.1,contrast/48)*(.85 if r is None else 1.0)/(1+spread/86)
                box={'top':[x,0,x1,d+2],'bottom':[x,h-d-2,x1,h],
                     'left':[0,x,d+2,x1],'right':[w-d-2,x,w,x1]}[side]
                candidates.append(dict(kind="border",side=side,box=box,score=round(float(strength),3),
                    evidence={"inset_px":d,"span_px":int(x1-x),"step":round(contrast,1),"outer_spread":round(spread,1)}))
        kept=[]
        for c in sorted(candidates,key=lambda q:-q["score"]):
            if any(box_overlap(c["box"],a["box"])>.6 for a in kept):continue
            kept.append(c)
        result.extend(kept)
    return result

def doubles(edge,angle,ref_edge,ref_angle,paired):
    # A retained edge and a second parallel edge must both exist. Orientation is modulo pi.
    # Shift by the edge normal up to 11 analysis pixels, with a 3 px minimum separation.
    out=np.zeros_like(edge,bool)
    bins=np.round(angle/45).astype('uint8')%4
    for j,(ux,uy) in enumerate([(1,0),(1,1),(0,1),(-1,1)]):
        a=j*45.;ori=np.minimum(np.abs(angle-a),180-np.abs(angle-a))<30
        base=(edge>0)&ori
        if paired:
            rori=np.minimum(np.abs(ref_angle-a),180-np.abs(ref_angle-a))<30
            base&=cv.dilate(np.uint8((ref_edge>0)&rori),np.ones((3,3),'uint8'))>0
        near=np.zeros(edge.shape,np.uint8)
        line=np.zeros((23,23),np.uint8)
        for dist in range(3,12):
            s=round(dist/(math.sqrt(2) if ux and uy else 1))
            for sign in (-1,1):line[11+sign*s*uy,11+sign*s*ux]=1
        near=cv.dilate(np.uint8(base),line)
        out|=(bins==j)&(edge>0)&(near>0)
    return out

def regions(mask,weight,kind,minimum,paired,aperture,temporal):
    if not np.any(mask):return []
    # Closing connects mild compression breaks in curved cracks. Connected-component
    # support and measured width allow curved outlines as well as long straight lines.
    broader=kind=='smooth_interior_crack'
    kernel=5 if broader else 3
    dense=cv.morphologyEx(np.uint8(mask),cv.MORPH_CLOSE,np.ones((kernel,kernel),np.uint8))
    n,labels,stats,_=cv.connectedComponentsWithStats(dense,8)
    hits=[]
    for j in np.flatnonzero((stats[:,4]>=minimum*.65)&(np.maximum(stats[:,2],stats[:,3])>=minimum*.65)):
        if not j:continue
        x,y,w,h,area=map(int,stats[j])
        roi=np.s_[y:y+h,x:x+w];support=(labels[roi]==j)&mask[roi]
        py,px=np.where(support)
        if len(px)<minimum*.68:continue
        comp=np.uint8(labels[roi]==j)
        contours=cv.findContours(comp,cv.RETR_EXTERNAL,cv.CHAIN_APPROX_NONE)[0]
        perimeter=sum(cv.arcLength(c,True) for c in contours)
        width=2*area/max(1.,perimeter)
        span=np.hypot(w,h)
        if span<minimum or width>(13.5 if broader else 5.6 if kind=='thin_line' else 5.0):continue
        if area>max(70,span*(15 if broader else 10)):continue
        if broader:
            # Isolate elongated intrusions into previously smooth material. Broad differences
            # in shading, large blobs, and grass patches typically violate this ribbon geometry.
            if span<minimum*1.8 or span/max(1,width)<11:continue
            eigen=np.linalg.eigvalsh(np.cov(px,py))
            if eigen[1]<14*max(.25,eigen[0]):continue
        intensity=float(np.percentile(weight[roi][support],68))
        change=float(np.percentile(temporal[roi][support],70)) if temporal is not None else None
        scale=.07 if broader else .23
        score=(span/minimum)**.67*(min(2.8,intensity/26))*(1 if paired else .82)/(1+max(0,width-2)*scale)
        if broader:score*=1.65
        if not paired and change is not None:score*=min(1.4,.84+change/85)
        if not paired and change is not None and change<8:
            # Keep exceptionally prominent static geometry eligible, but give recurring
            # natural line textures much lower priority after their first observation.
            score*=.24
        if score<1.15:continue
        evidence={"span_px":round(float(span),1),"effective_width_px":round(width,1),"support_px":len(px),"contrast":round(intensity,1)}
        if change is not None:
            evidence['motion_compensated_change']=round(change,1)
            evidence['temporal_support']='changed' if change>=8 else 'spatial_only'
        elif not paired:evidence['temporal_support']='no_previous'
        ap=bool(np.mean(aperture[roi][support])>.35)
        family='thin_line' if broader else kind
        hits.append(dict(kind='aperture' if ap else family,box=[x,y,x+w,y+h],score=round(float(score),3),evidence={**evidence,"shape":kind} if ap or broader else evidence))
    return hits

def inspect(im,ref,previous,allowed,aperture,minimum):
    paired=ref is not None
    g=gray(im);ed,angle=edgemaps(g)
    temporal=aligned_previous(g,previous) if not paired and previous is not None else None
    h,w=g.shape;inside=allowed.copy();inside[:2]=inside[-2:]=False;inside[:,:2]=inside[:,-2:]=False
    if paired:
        rg=gray(ref);re,ra=edgemaps(rg)
        delta=difference(im,ref)
        band=ridge(delta,3)
        dilref=cv.dilate(re,np.ones((5,5),'uint8'))
        thin=(band>17)&(delta>19)&inside
        near_delta=cv.dilate(delta,np.ones((3,3),np.uint8))
        parallel=doubles(ed,angle,re,ra,True)&(dilref==0)&(near_delta>11)&inside
        # Edge-to-edge translation without a retained original boundary is excluded from the double class.
        wghost=np.maximum(band,near_delta)
    else:
        bright=ridge(g,3);dark=ridge(255-g,3);band=np.maximum(bright,dark)
        thin=(band>=34)&inside
        parallel=doubles(ed,angle,None,None,False)&inside
        # For generic footage stable paired contours are ubiquitous. Keep high-contrast spatial
        # ridges and flag newly changing parallel outlines; first frames have no temporal baseline.
        if temporal is None:parallel[:]=False
        else:parallel&=(cv.dilate(temporal,np.ones((3,3),'uint8'))>=20)
        wghost=np.maximum(band,temporal) if temporal is not None else band
    hits=borders(im,ref,allowed,temporal)
    linehits=regions(thin,band,'thin_line',minimum,paired,aperture,temporal)
    if paired:
        broader=ridge(delta,8)
        smooth=(dilref==0)&(delta>15)&(broader>12)&inside
        linehits.extend(regions(smooth,broader,'smooth_interior_crack',minimum,True,aperture,None))
    ghosts=regions(parallel,wghost,'double_edge',minimum,paired,aperture,temporal)
    for candidate in sorted(ghosts+linehits,key=lambda q:-q['score']):
        if any(o['kind']==candidate['kind'] and box_overlap(o['box'],candidate['box'])>.72 for o in hits):continue
        hits.append(candidate)
    return hits,g

def cover(mask,allowed):
    bad=(mask<250)&allowed
    if not np.any(bad):return []
    n,l,s,_=cv.connectedComponentsWithStats(np.uint8(bad),8);result=[]
    for j in range(1,n):
        x,y,w,h,area=map(int,s[j])
        if area<3:continue
        result.append(dict(kind="coverage_gap",box=[x,y,x+w,y+h],score=round(4+math.log1p(area)/2,3),evidence={"pixels_below_250":area,"min_coverage":int(mask[y:y+h,x:x+w][l[y:y+h,x:x+w]==j].min())}))
    return result

class Source:
    def __init__(self,path):
        self.path=str(Path(path).resolve());self.cap=cv.VideoCapture(self.path)
        if not self.cap.isOpened():raise ValueError("Cannot open "+self.path)
        self.size=tuple(int(self.cap.get(k)) for k in [cv.CAP_PROP_FRAME_WIDTH,cv.CAP_PROP_FRAME_HEIGHT]);self.fps=float(self.cap.get(cv.CAP_PROP_FPS));self.advertised=round(self.cap.get(cv.CAP_PROP_FRAME_COUNT))
        if min(self.size)<=0 or self.fps<=0:raise ValueError("Invalid video metadata for "+self.path)
    def read(self):
        ok,im=self.cap.read()
        return im if ok else None
    def close(self):self.cap.release()
def proof(out,sources,rows,fps,max_images,force):
    if max_images<=0 and not force:return []
    relevant=[r for r in rows if r['hits']]
    best=[]
    for s in sorted(relevant,key=lambda r:-r['max_score']):
        if all(abs(s['frame']-r['frame'])>max(2,round(fps*.15)) for r in best):best.append(s)
        if len(best)>=max_images:break
    best=best[:max_images]
    selected={r['frame']:r for r in best}
    selected.update({f:rows[f] for f in force if 0<=f<len(rows)})
    output=[]
    if not selected:return output
    from PIL import Image,ImageDraw
    renders=[Source(s.path) for s in sources]
    try:
        for f,row in selected.items():
            imgs=[]
            for cap in renders:
                cap.cap.set(cv.CAP_PROP_POS_FRAMES,f)
                im=cap.read()
                if im is None:raise ValueError(f'Cannot seek proof frame {f}')
                imgs.append(Image.fromarray(cv.cvtColor(im,cv.COLOR_BGR2RGB)))
            hit=row['hits'][0] if row['hits'] else None
            left=imgs[0].copy(); d=ImageDraw.Draw(left)
            for h in row['hits'][:5]:
                x,y,x1,y1=h['box'];d.rectangle((x,y,x1-1,y1-1),outline=(255,76,37),width=max(1,min(left.size)//210))
            left.thumbnail((200,260))
            wi,he=imgs[0].size
            x,y,x1,y1=hit['box'] if hit else [wi//4,he//4,3*wi//4,3*he//4]
            # Center an enlarged native detail on actual local evidence. A full-width
            # one-pixel border would otherwise collapse into a tiny dark stripe in the card.
            cx=(x+x1)//2;cy=(y+y1)//2
            if hit and hit['kind'] in ('thin_line','aperture','double_edge'):
                patch=np.array(imgs[0].crop((x,y,x1,y1)))
                if len(imgs)>1:
                    strength=difference(patch,np.array(imgs[1].crop((x,y,x1,y1))))
                else:
                    light=cv.cvtColor(patch,cv.COLOR_RGB2GRAY)
                    strength=np.maximum(ridge(light,3),ridge(255-light,3))
                yy,xx=np.where(strength>=max(5,np.percentile(strength,92)))
                if len(xx):
                    ix=np.argmin((xx-(cx-x))**2+(yy-(cy-y))**2)
                    cx=x+int(xx[ix]);cy=y+int(yy[ix])
            halfw=min(73,max(30,round((x1-x)*.6)+8));halfh=min(55,max(22,round((y1-y)*.6)+8))
            if hit and hit['kind']=='border':halfw,halfh=68,39
            x0=max(0,min(cx-halfw,wi-2*halfw));y0=max(0,min(cy-halfh,he-2*halfh))
            crop=(x0,y0,min(wi,x0+2*halfw),min(he,y0+2*halfh))
            detail=[]
            for im in imgs:
                region=im.crop(crop);zoom=min(260/region.width,230/region.height,3.)
                region=region.resize((max(1,round(region.width*zoom)),max(1,round(region.height*zoom))),Image.Resampling.NEAREST if zoom>1 else Image.Resampling.LANCZOS)
                detail.append(region)
            tile=Image.new('RGB',(210+270*len(imgs),298),'#17212b');d=ImageDraw.Draw(tile)
            tile.paste(left,(4,27));d.text((5,4),f"F{f}   {tc(f,fps)}   "+(hit['kind'] if hit else 'no candidate'),fill='white')
            for j,im in enumerate(detail):
                tile.paste(im,(215+j*270,49));d.text((215+j*270,29),'render crop' if j==0 else 'reference crop',fill='white')
            name=f"F{f:06}.jpg";tile.save(out/name,quality=91);output.append(name)
    finally:
        for cap in renders:cap.close()
    return output

def _run(args):
    video=Source(args.video);ref=Source(args.reference) if args.reference else None
    coverage=Source(args.coverage) if args.coverage else None
    sources=[s for s in (video,ref,coverage) if s is not None]
    for item in sources[1:]:
        if item.size!=video.size or abs(item.fps-video.fps)>.002:raise ValueError("Geometry or FPS differs: "+item.path)
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    w,h=video.size
    scale=min(1.,args.max_side/max(w,h)) if args.max_side else 1.
    size=(max(2,round(w*scale)),max(2,round(h*scale)))
    if min(size)<24:raise ValueError("Minimum supported analyzed side is 24 pixels")
    minimum=args.min_length if args.min_length else max(17,round(min(size)*.055))
    if minimum<5:raise ValueError("min-length must be >=5 analyzed pixels")
    counts=Counter();frames_by_kind=Counter();rows=[];prev=None;mini_old=None
    flags=set(f for a,b in framespec(args.cuts) for f in range(a,b+1))
    flashes=framespec(args.flashes)
    try:
        with (out/'candidates.jsonl').open('w',encoding='utf-8') as jf,(out/'frames.csv').open('w',encoding='utf-8-sig',newline='') as cf:
            writer=csv.writer(cf);writer.writerow(['frame','timecode','declared_cut','auto_cut','intentional_flash','count','max_score',*KINDS,*('border_'+s for s in SIDES)])
            f=0
            while True:
                ims=[s.read() for s in sources]
                if all(im is None for im in ims):break
                if any(im is None for im in ims):raise ValueError("Decoded sources have different lengths at frame "+str(f))
                img=ims[0]
                sm=cv.resize(img,size,interpolation=cv.INTER_AREA) if scale<1 else img
                r=ims[1] if ref else None
                if ref and scale<1:r=cv.resize(r,size,interpolation=cv.INTER_AREA)
                base=gray(sm);mini=cv.resize(base,(64,36),interpolation=cv.INTER_AREA)
                auto=bool(mini_old is not None and np.median(cv.absdiff(mini,mini_old))>args.cut_change)
                first=f in flags or auto
                intentional=any(a<=f<=b for a,b in flashes)
                allowed=~roi_mask(base.shape,f,args.ignore_roi)
                aperture=roi_mask(base.shape,f,args.aperture_roi)
                if intentional:hits=[]
                else:hits,_=inspect(sm,r,None if first else prev,allowed,aperture,minimum)
                for h0 in hits:
                    coord=h0['box']
                    h0['box']=[max(0,round(coord[0]*w/size[0])),max(0,round(coord[1]*h/size[1])),min(w,round(coord[2]*w/size[0])),min(h,round(coord[3]*h/size[1]))]
                if coverage:
                    # Always check the matte at its decoded native dimensions, including flash frames.
                    cm=gray(ims[-1]);hits+=cover(cm,~roi_mask(cm.shape,f,args.ignore_roi))
                hits.sort(key=lambda q:-q['score']);by=Counter(q['kind'] for q in hits);sd=Counter(q.get('side') for q in hits)
                counts.update(by);frames_by_kind.update(by.keys())
                row=dict(frame=f,timecode=tc(f,video.fps),declared_cut=f in flags,auto_cut=auto,intentional_flash=intentional,max_score=hits[0]['score'] if hits else 0.,hits=hits)
                jf.write(json.dumps(row,ensure_ascii=False,default=lambda o:o.item())+'\n')
                writer.writerow([f,row['timecode'],int(f in flags),int(auto),int(intentional),len(hits),row['max_score'],*(by[k] for k in KINDS),*(sd[s] for s in SIDES)])
                rows.append({**row,'hits':hits[:5]})
                prev=None if intentional else base;mini_old=mini;f+=1
                if f%100==0:print(f"Inspected {f} frames",flush=True)
    finally:
        for s in sources:s.close()
    if not rows:raise ValueError('Video has no decoded frames')
    if any(s.advertised>0 and s.advertised!=len(rows) for s in sources):raise ValueError("Decoded length differs from source metadata; inspect the partial report")
    forced={f for a,b in framespec(args.review_frames) for f in range(a,b+1)}
    picks=proof(out,[video]+([ref] if ref else []),rows,video.fps,args.images,forced)
    mode='paired_reference' if ref else 'single_video_candidates'
    summary=dict(mode=mode,video=video.path,reference=ref.path if ref else None,coverage=coverage.path if coverage else None,dimensions=list(video.size),fps=video.fps,frames=len(rows),analysis_dimensions=list(size),min_span_analyzed_px=minimum,declared_cuts=sorted(flags),intentional_flashes=flashes,ignore_roi=args.ignore_roi,aperture_roi=args.aperture_roi,candidate_regions=dict(counts),frames_with_candidates_by_kind=dict(frames_by_kind),frames_with_any_candidate=sum(bool(r['hits']) for r in rows),proof_images=picks,verdict='manual_review',coverage_definition='Opaque neutral matte: expected 250..255, flagged connected areas of >=3 native pixels' if coverage else None)
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),'utf-8')
    text=['# 成片接缝检查','',f"逐帧解码 {len(rows)} 帧，{w}×{h}，{video.fps:g} fps。分析分辨率 {size[0]}×{size[1]}，内区候选最小跨度 {minimum} 个分析像素。", '',f"成片 `{video.path}`"]
    if ref:text+=['',f"同画面参考 `{ref.path}`",'','对照模式按同一帧寻找新增窄残差、保留原边缘的平行轮廓和画框内侧台阶。机位和时序需对应，微小错位和压缩也会产生响应。']
    else:text+=['','单片模式检查窄亮暗线、连续帧运动补偿后的平行边缘及四边候选。建筑线、物体轮廓、稳定黑边和极细纹理可产生相同信号。动画是否正确须看相邻帧及图层。']
    text+=['',f"{summary['frames_with_any_candidate']} 帧含候选。候选类别可能重叠，分值用于排序。",'','| 类别 | 影响帧数 | 区域数 |','|---|---:|---:|']
    labels=dict(thin_line='窄线',double_edge='平行双边',aperture='指定穿孔区域',border='画框四边',coverage_gap='可选覆盖层实测缺口')
    for k in KINDS:text.append(f"| {labels[k]} | {frames_by_kind[k]} | {counts[k]} |")
    text+=['','[全帧 CSV](frames.csv) · [原图坐标与局部证据](candidates.jsonl) · [运行条件](summary.json)','','## 优先复看','']
    if picks:text.extend(f"- [第 {int(n[1:7])} 帧 · {tc(int(n[1:7]),video.fps)}]({n})" for n in picks)
    else:text.append('当前参数没有选出候选图。')
    text+=['','## 观测边界','','切镜重置跨帧比较，声明的有意闪光保留帧号并跳过画面结构比较。ROI 坐标按原帧归一化。未指定穿孔区时，裂缝仍以窄线或平行边缘扫描。','',
    '对齐偏差、景深、草叶、文字、新增的合法转场和编码振铃可形成候选。弱对比或短于设定跨度的接缝、紧贴已有边缘的亚像素重影、纹理密集区的弯曲断裂、与背景同色的空洞可能漏检。四边扫描深度为短边约 4%，上限 24 个分析像素。缩小分析分辨率可能丢失原生一像素线。','',
    '覆盖层可直接定位未达阈值的像素。其结论仅对应提供的覆盖层和约定的满幅区域。帧序号从 0 起，时间码按视频报出的帧率生成；变帧率视频需预先按同一固定时基导出。音轨和整体观感不在本项检查内。']
    (out/'report.md').write_text('\n'.join(text)+'\n','utf-8');return summary

def rank_frames(directory,summary,threshold):
    # Retain weak candidates in their original rows while giving long clips a shorter review queue.
    path=Path(directory);scores=[]
    with (path/'candidates.jsonl').open(encoding='utf-8') as jf:
        for line in jf:
            row=json.loads(line)
            scores.append(sum(hit['score']>=threshold for hit in row['hits']))
    with (path/'frames.csv').open(encoding='utf-8-sig',newline='') as cf:
        frames=list(csv.DictReader(cf))
    if len(frames)!=summary['frames'] or len(scores)!=len(frames):
        raise ValueError('Review index and decoded frame count differ')
    for row,count in zip(frames,scores):row['priority_count']=count
    with (path/'frames.csv').open('w',encoding='utf-8-sig',newline='') as cf:
        writer=csv.DictWriter(cf,fieldnames=list(frames[0]));writer.writeheader();writer.writerows(frames)
    number=sum(count>0 for count in scores)
    summary.update(review_score_threshold=threshold,priority_frames=number)
    (path/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),'utf-8')
    report=path/'report.md'
    note=f'**优先复看**按分值 ≥ {threshold:g} 筛出 {number} 帧，可在全帧 CSV 过滤 `priority_count > 0`。较弱的局部候选均保留。'
    lines=[l for l in report.read_text('utf-8').splitlines() if not l.startswith('**优先复看**')]
    idx=lines.index('| 类别 | 影响帧数 | 区域数 |')
    lines[idx:idx]=[note,'']
    report.write_text('\n'.join(lines)+'\n','utf-8')

def run(args):
    # Keep a previous completed inspection intact if the new media cannot be fully decoded.
    destination=Path(args.out).resolve()
    destination.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.seam-qa-',dir=destination) as working:
        current=copy(args);current.out=working
        summary=_run(current)
        rank_frames(working,summary,args.review_score)
        files=list(Path(working).iterdir())
        files.sort(key=lambda f:f.name in ('report.md','summary.json'))
        for file in files:file.replace(destination/file.name)
    return summary

def parse(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('video');p.add_argument('--reference');p.add_argument('--coverage',help='frame-matched neutral white=fully covered video')
    p.add_argument('--out',required=True);p.add_argument('--cuts',default='',help='zero-based shot starts, e.g. 183,387')
    p.add_argument('--flashes',default='',help='inclusive intentional flash ranges, e.g. 5-6,19')
    p.add_argument('--ignore-roi',type=roispec,action='append',default=[]);p.add_argument('--aperture-roi',type=roispec,action='append',default=[])
    p.add_argument('--review-frames',default='',help='additional proof frames, even if candidate count is zero')
    p.add_argument('--max-side',type=int,default=0,help='0 = full native resolution')
    p.add_argument('--min-length',type=int,default=0,help='minimum interior span in analysis pixels, default short side * 0.055, floor 17')
    p.add_argument('--cut-change',type=float,default=55,help='median 8-bit luma frame change that resets temporal evidence')
    p.add_argument('--images',type=int,default=8,help='worst timecodes to illustrate; spaced apart')
    p.add_argument('--review-score',type=float,default=6,help='ranked triage threshold; all raw candidates stay in the full report')
    a=p.parse_args(argv)
    if a.max_side<0 or a.images<0:p.error('Image count and max side must be nonnegative')
    return a
if __name__=='__main__':
    try:
        s=run(parse());print(f"Decoded {s['frames']} frames. {s['frames_with_any_candidate']} frames with review candidates.",flush=True)
    except (ValueError,RuntimeError,cv.error) as e:raise SystemExit(str(e))
