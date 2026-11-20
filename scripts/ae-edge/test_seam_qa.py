"""Lossless synthetic positives and controls. Output stays under the caller's chosen directory."""
import argparse,csv,json
from pathlib import Path
import numpy as np
from seam_qa import cv,parse,run

W,H=224,160
COUNT=27
def scene(f):
    y,x=np.indices((H,W))
    noise=2.6*np.sin((x+.6*f)*.2)*np.cos(y*.09)
    base=np.stack([98+x*.13+noise,119+y*.11+noise,108+(x+y)*.07+noise],axis=2).astype('uint8')
    if f>=17:base=cv.flip(base,1)
    # Real narrow texture, real paired outlines, a real aperture and an intentional corner strip
    # are present in the clean reference. All must be excluded by the paired detector.
    cv.line(base,(8,146),(122,145),(164,168,160),1)
    shift=round(3*np.sin(f*.35))
    cv.rectangle(base,(65+shift,28),(121+shift,129),(218,210,196),-1)
    cv.ellipse(base,(91+shift,57),(16,20),12,0,360,(32,68,39),-1)
    cv.line(base,(20,10),(52,22),(172,175,167),2)
    cv.line(base,(20,15),(52,27),(170,173,168),2)
    if f==18:base[:]=245
    return base,shift

def make(out):
    paths={k:out/(k+'.avi') for k in ['reference','render','coverage']}
    writers={k:cv.VideoWriter(str(p),cv.VideoWriter_fourcc(*'FFV1'),30.,(W,H)) for k,p in paths.items()}
    if not all(w.isOpened() for w in writers.values()):raise RuntimeError('FFV1 writer unavailable')
    for f in range(COUNT):
        b,shift=scene(f);render=b.copy();alpha=np.full_like(b,255)
        if f==4:cv.line(render,(26,104),(56,40),(6,14,15),1)
        if f==6:cv.polylines(render,[np.int32([[76,45],[77,62],[83,74],[98,78],[106,69]])],False,(239,248,241),2)
        if f in (7,8):cv.line(render,(127+shift,34),(127+shift,123),(200,193,181),2)
        if f==9:render[:1]=0;alpha[:1]=0
        if f==10:render[:,-4:]=36;alpha[:,-4:]=0
        if f==11:render[-3:]=10;alpha[-3:]=0
        if f==12:render[:,:2]=208;alpha[:,:2]=0
        if f==13:cv.line(render,(136,42),(201,94),(200,206,214),2)
        if f==14:cv.polylines(render,[np.int32([[109,35],[107,53],[109,73],[105,111]])],False,(79,109,76),7)
        if f==15:cv.line(render,(12,8),(12,63),(1,1,1),2)
        if f==18:render[:]=32
        if f==20:alpha[64:74,148:156]=0
        for k,im in [('reference',b),('render',render),('coverage',alpha)]:writers[k].write(im)
    for w in writers.values():w.release()
    return paths

def run_tests(out):
    out.mkdir(parents=True,exist_ok=True);p=make(out)
    common=['--images','3','--cuts','17','--flashes','18','--ignore-roi','15:0,0,0.12,0.5','--aperture-roi','6:0.30,0.22,0.53,0.55']
    args=lambda video,dest,*extra:parse([str(video),'--out',str(out/dest),*common,*map(str,extra)])
    paired=run(args(p['render'],'paired','--reference',p['reference'],'--coverage',p['coverage']))
    clean=run(args(p['reference'],'clean','--reference',p['reference']))
    single=run(args(p['render'],'single'))
    natural=run(args(p['reference'],'single-texture'))
    # A clean flat clip has no candidate structure; moving textured footage can legitimately have some.
    neutral=out/'flat.avi'
    writer=cv.VideoWriter(str(neutral),cv.VideoWriter_fourcc(*'FFV1'),30.,(W,H))
    assert writer.isOpened()
    for f in range(8):writer.write(np.full((H,W,3),125+f,np.uint8))
    writer.release()
    flat=run(args(neutral,'single-flat'))
    assert flat['frames']==8 and flat['frames_with_any_candidate']==0,flat
    previous=(out/'clean/summary.json').read_bytes()
    try:run(args(p['render'],'clean','--reference',neutral))
    except ValueError as e:assert 'length' in str(e)
    else:raise AssertionError('Unequal decoded frame counts accepted')
    assert previous==(out/'clean/summary.json').read_bytes()
    rows=lambda d:[json.loads(l) for l in (out/d/'candidates.jsonl').read_text('utf8').splitlines()]
    pr=rows('paired');sr=rows('single')
    cases=[]
    def check(name,f,predicate,column='paired'):
        r=(pr if column=='paired' else sr)[f]
        if not predicate(r):raise AssertionError(f"{column} / {name}: "+json.dumps(r))
        cases.append([column,name,f])
    for s in [paired,clean,single]:assert s['frames']==COUNT
    assert clean['frames_with_any_candidate']==0,clean
    for d in ['paired','clean','single']:
        with (out/d/'frames.csv').open(encoding='utf-8-sig') as handle:assert list(range(COUNT))==[int(v['frame']) for v in csv.DictReader(handle)]
    def has(kind,x=None,y=None,slack=4):
        def match(row):
            for q in row['hits']:
                if q['kind']!=kind:continue
                a,b,c,d=q['box']
                if x is None or a-slack<=x<c+slack and b-slack<=y<d+slack:return True
            return False
        return match
    check('clean pair / no new edge',1,lambda r:not r['hits'])
    check('new one-pixel slanted line',4,has('thin_line',41,72))
    check('curved crack through marked aperture',6,has('aperture',84,70))
    check('duplicate beside retained object edge',7,has('double_edge',130,70))
    for f,side in zip(range(9,13),('top','right','bottom','left')):
        for mode in ('paired','single'):check(side+' strip',f,lambda r,s=side:any(q['kind']=='border' and q['side']==s for q in r['hits']),mode)
        check(side+' coverage hole',f,has('coverage_gap'))
    check('unmasked diagonal',13,has('thin_line',170,67))
    check('wider crack inside smooth reference material',14,lambda r:any(h['evidence'].get('shape')=='smooth_interior_crack' and h['box'][1]<48 and h['box'][3]>96 for h in r['hits']))
    check('intentional mask',15,lambda r:not r['hits'])
    check('declared edit',17,lambda r:r['declared_cut'] and not r['hits'])
    check('intentional flash',18,lambda r:r['intentional_flash'] and not r['hits'])
    check('interior hole in explicit coverage matte',20,has('coverage_gap',152,69))
    check('single diagonal geometry',4,has('thin_line',41,72),'single')
    check('single changed parallel edge',7,has('double_edge',130,70),'single')
    check('single curve within aperture',6,has('aperture',84,70),'single')
    assert single['verdict']=='manual_review'
    report=dict(decoded_frames_each=COUNT,paired_clean_candidates=clean['candidate_regions'],clean_flat_single_frames=8,clean_flat_single_candidates=flat['candidate_regions'],natural_single_frames_with_candidates=natural['frames_with_any_candidate'],natural_single_total_frames=natural['frames'],unequal_length_rejected=True,previous_report_preserved_on_failure=True,passed_cases=cases,checks_passed=len(cases))
    (out/'regression.json').write_text(json.dumps(report,indent=2),'utf-8');print(report)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);run_tests(parser.parse_args().out)
