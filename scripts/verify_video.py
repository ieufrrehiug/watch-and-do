"""Inspect the encoded media, fully decode it, and measure audio. Never claims audition."""
from pathlib import Path
from fractions import Fraction
import argparse, json, math, re, subprocess

def probe_errors(probe,width,height,fps,duration,audio):
    errors=[]
    videos=[s for s in probe.get('streams',[]) if s.get('codec_type')=='video']
    sounds=[s for s in probe.get('streams',[]) if s.get('codec_type')=='audio']
    if not videos:errors.append('missing video')
    else:
        v=videos[0]
        if (v.get('width'),v.get('height'))!=(width,height):errors.append('wrong dimensions')
        try:actual=float(Fraction(v.get('r_frame_rate','0')))
        except (ValueError,ZeroDivisionError):actual=0
        if abs(actual-fps)>.001:errors.append('wrong frame rate')
        try:average=float(Fraction(v.get('avg_frame_rate',v.get('r_frame_rate','0'))))
        except (ValueError,ZeroDivisionError):average=0
        if abs(average-fps)>.001:errors.append('wrong average frame rate')
        try:video_duration=float(v.get('duration',0))
        except (ValueError,TypeError):video_duration=0
        if abs(video_duration-duration)>1/fps+.001:errors.append('wrong video stream duration')
        count=v.get('nb_read_frames',v.get('nb_frames'))
        if count is not None:
            try:
                if abs(int(count)-round(duration*fps))>1:errors.append('wrong video frame count')
            except (ValueError,TypeError):errors.append('invalid video frame count')
        if v.get('codec_name')!='h264' or v.get('pix_fmt')!='yuv420p':errors.append('not H264/yuv420p')
    try:actual_duration=float(probe.get('format',{}).get('duration',0))
    except (ValueError,TypeError):actual_duration=0
    if abs(actual_duration-duration)>1/fps+.001:errors.append('wrong duration')
    if audio:
        if not sounds:errors.append('missing audio')
        else:
            a=sounds[0]
            if a.get('channels')!=2 or a.get('codec_name')!='aac':errors.append('audio is not stereo AAC')
            try:start=float(a.get('start_time',0)); length=float(a.get('duration',0))
            except (ValueError,TypeError):start=0;length=0
            tolerance=max(1/fps,.05)  # AAC priming/frame padding
            if abs(start)>tolerance or abs(start+length-duration)>tolerance:errors.append('audio does not cover the film')
    return errors

def run(args):
    return subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace')

def verify(path,width,height,fps,duration,audio):
    probe_result=run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)])
    if probe_result.returncode:raise RuntimeError(probe_result.stderr)
    probe=json.loads(probe_result.stdout)
    errors=probe_errors(probe,width,height,fps,duration,audio)
    decoded=run(['ffmpeg','-hide_banner','-v','error','-xerror','-i',str(path),'-map','0:v','-map','0:a?','-f','null','-'])
    if decoded.returncode:errors.append('full decode failed')
    result={'ok':False,'file':str(path.resolve()),'probe':probe,'fullDecode':decoded.returncode==0,'errors':errors,'audition':'NOT PERFORMED — measurements do not prove listening quality','visualReview':'NOT PERFORMED by this script'}
    if audio and any(s.get('codec_type')=='audio' for s in probe['streams']):
        measured=run(['ffmpeg','-hide_banner','-i',str(path),'-vn','-af','loudnorm=I=-16:TP=-1.5:LRA=9:print_format=json','-f','null','-'])
        blocks=re.findall(r'\{[^{}]*"input_i"[^{}]*\}',measured.stderr)
        if measured.returncode or not blocks:errors.append('audio measurement failed')
        else:
            loud=json.loads(blocks[-1]);result['audioMeasurements']=loud
            integrated=float(loud['input_i']);peak=float(loud['input_tp'])
            if not math.isfinite(integrated) or integrated<-55:errors.append('audio silent or nearly silent')
            if peak>0:errors.append('audio true peak exceeds 0 dBTP')
    result['ok']=not errors
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('file',type=Path)
    for name,kind,default in [('width',int,1080),('height',int,1920),('fps',float,30),('duration',float,34.5)]:p.add_argument('--'+name,type=kind,default=default)
    p.add_argument('--audio',action='store_true');p.add_argument('--report',type=Path);a=p.parse_args()
    if not all(math.isfinite(n) and n > 0 for n in (a.fps, a.duration, a.width, a.height)):
        p.error('dimensions, fps and duration must be finite and positive')
    report=verify(a.file,a.width,a.height,a.fps,a.duration,a.audio)
    if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='probe'},ensure_ascii=True,indent=2))
    raise SystemExit(0 if report['ok'] else 1)
