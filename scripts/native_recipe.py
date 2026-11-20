"""Observed, version-scoped Jianying actions with per-action evidence."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
import inspect
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

from experience import read, write, digest, prepare, run_recipe, assert_state, parse_numeric, deactivate_recipe, ROOT, DATA


class Ocr:
    def __init__(self):
        self.proc = subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-File',
                                      str(Path(__file__).with_name('ocr_server.ps1'))],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     encoding='utf8', text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        self.queue = queue.Queue()
        def consume():
            for line in self.proc.stdout: self.queue.put(line)
        threading.Thread(target=consume, daemon=True).start()
    def texts(self, paths, languages=None):
        self.proc.stdin.write(json.dumps({'paths':[str(p.resolve()) for p in paths], 'languages':languages},ensure_ascii=False)+'\n')
        self.proc.stdin.flush()
        result = json.loads(self.queue.get(timeout=20))
        if 'error' in result: raise RuntimeError(result['error'])
        return result['texts']
    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try: self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired: self.proc.terminate()


class NativeAdapter:
    real_device = True
    def __init__(self, config):
        if os.name != "nt":
            raise RuntimeError("Actual Jianying desktop replay requires Windows; use --dry-run for a portable preflight.")
        from PIL import ImageGrab
        if "window" not in inspect.signature(ImageGrab.grab).parameters:
            raise RuntimeError("Window-only capture requires Pillow with ImageGrab.grab(window=...).")
        import native_windows as native_ui
        import uiautomation
        self.n, self.ui = native_ui, uiautomation
        self.config = config
        self.n.U.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p]
        self.n.U.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
        self.n.U.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        self.ocr = Ocr()
        self.hwnd = None
        self.last = None
    def close(self): self.ocr.close()
    def window(self):
        title = self.config.get('window_title','剪映专业版')
        rows = self.n.windows()
        main = [w for w in rows if w['title'] == title]
        if len(main) != 1: raise RuntimeError('Expected one exact window: '+title)
        self.hwnd = main[0]['hwnd']
        return main[0], rows
    def activate(self):
        w,_ = self.window(); h=w['hwnd']
        if w['version'] != self.config['version']: raise RuntimeError('Version changed')
        if not self.n.U.IsWindowEnabled(h): raise RuntimeError('Modal disables requested window')
        self.n.U.ShowWindowAsync(h,9); self.n.U.SetForegroundWindow(h)
        if self.n.U.GetForegroundWindow()!=h:
            current=ctypes.windll.kernel32.GetCurrentThreadId()
            foreground=self.n.U.GetWindowThreadProcessId(self.n.U.GetForegroundWindow(),None)
            attached=False
            try:
                if foreground!=current: attached=bool(self.n.U.AttachThreadInput(current,foreground,True))
                self.n.U.BringWindowToTop(h);self.n.U.SetForegroundWindow(h)
            finally:
                if attached:self.n.U.AttachThreadInput(current,foreground,False)
        deadline=time.monotonic()+5; previous=None; stable=0
        while time.monotonic()<deadline:
            box=self.n.rect(h)
            stable=stable+1 if box==previous else 0; previous=box
            if stable>=3 and self.n.U.GetForegroundWindow()==h: return
            time.sleep(.15)
        raise RuntimeError('Window did not stabilize after activation')
    def inspect_windows(self, w, rows):
        out=[]
        for other in rows:
            if other['pid']!=w['pid'] or other['hwnd']==w['hwnd']:continue
            h=other['hwnd'];c=self.ui.ControlFromHandle(h);box=self.n.rect(h)
            item=dict(title=other['title'],aid=c.AutomationId,cls=c.ClassName,rect=list(box))
            if c.AutomationId in ('MainWindow.surface_main','editPanelLoader.editWin'):
                continue
            if (re.fullmatch(r'LVToolTipWindow_QMLTYPE_\d+',c.ClassName)
                    and self.n.U.GetWindowLongW(h,-20)&0x20 and box[2]-box[0]<=160 and box[3]-box[1]<=80):
                continue  # observed transparent, noninteractive tooltip family, never a dialog
            allowed=False
            for rule in self.config.get('allowed_windows',[]):
                if rule.get('title')==other['title'] and re.fullmatch(rule['class_pattern'],c.ClassName):
                    if rule.get('size')==[box[2]-box[0],box[3]-box[1]]: allowed=True
            if not allowed:out.append(item)
        return out
    def foreground_allowed(self,w,rows):
        foreground=self.n.U.GetForegroundWindow()
        if foreground==w['hwnd']:return True
        for other in rows:
            if other['hwnd']!=foreground or other['pid']!=w['pid']:continue
            c=self.ui.ControlFromHandle(foreground);box=self.n.rect(foreground)
            for rule in self.config.get('allowed_windows',[]):
                if (rule.get('title')==other['title'] and re.fullmatch(rule['class_pattern'],c.ClassName)
                        and rule.get('size')==[box[2]-box[0],box[3]-box[1]]):return True
        return False
    def snapshot(self, dest):
        from PIL import ImageGrab,ImageOps
        dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.with_suffix('.png').exists():dest=dest.with_name(dest.name+'-'+uuid.uuid4().hex[:8])
        w,rows=self.window();h=w['hwnd'];box=self.n.rect(h)
        state=dict(version=w['version'],dpi=self.n.U.GetDpiForWindow(h),layout=[box[2]-box[0],box[3]-box[1]],
                   foreground=self.foreground_allowed(w,rows),window_title=w['title'],
                   automation_id=self.ui.ControlFromHandle(h).AutomationId)
        unknown=self.inspect_windows(w,rows);state['unknown_dialog']=bool(unknown);state['unknown_windows']=unknown
        state['external_focus']=not any(row['hwnd']==self.n.U.GetForegroundWindow() and row['pid']==w['pid'] for row in rows)
        for name,file in self.config.get('files',{}).items():
            file=Path(file);state[name+'_exists']=file.is_file()
            state[name+'_nonempty']=file.is_file() and file.stat().st_size>0
        if not state['foreground'] or state['unknown_dialog']:
            self.last=state;return state  # never save another app's covered pixels
        picture=ImageGrab.grab(window=h)
        if picture.size != tuple(state['layout']):
            raise RuntimeError('Native capture and observed window dimensions differ')
        path=dest.with_suffix('.png');picture.save(path)
        state.update(image=str(path),image_sha256=digest(path))
        probes=dict(self.config.get('probes',{}))
        if state['automation_id']=='MainWindow':
            probes={'project':{'rect':[round(picture.width*.30),0,round(picture.width*.70),40]},**probes}
        elif state['automation_id']=='HomeWindow':state['project']='HOME'
        paths=[];names=[];languages=[]
        for name,probe in probes.items():
            if probe.get('when_layout') and state['layout']!=probe['when_layout']:
                state[name]=None
                continue
            if 'point' in probe:
                pixel=picture.convert('RGB').getpixel(tuple(probe['point']))
                state[name]=all(abs(a-b)<=probe.get('tolerance',20) for a,b in zip(pixel,probe['color']))
                continue
            area=probe['rect']
            if area[0]<0 or area[1]<0 or area[2]>picture.width or area[3]>picture.height:raise ValueError('Probe outside window')
            crop=picture.crop(tuple(area)).convert('RGB')
            if 'template' in probe:
                from PIL import Image,ImageChops,ImageStat
                with Image.open(probe['template']) as template:
                    template=template.convert('RGB')
                    state[name]=crop.size==template.size and max(ImageStat.Stat(ImageChops.difference(crop,template)).mean)<=probe.get('max_mean_error',5)
                continue
            crop=ImageOps.invert(crop) if probe.get('invert',True) else crop
            crop=ImageOps.autocontrast(crop.convert('L')).convert('RGB')
            crop=crop.resize((crop.width*3,crop.height*3))
            crop_path=dest.with_name(dest.name+'-'+name).with_suffix('.png');crop.save(crop_path)
            paths.append(crop_path);names.append(name);languages.append(probe.get('language','en-US'))
        if paths:
            for name,words in zip(names,self.ocr.texts(paths,languages)):
                value=words.strip()
                probe=probes[name]
                if probe.get('type')=='number':
                    state[name+'_ocr']=value
                    value=parse_numeric(value)
                    state[name+'_visible']=value is not None
                if probe.get('compact'):value=''.join(value.split())
                state[name]=value
        self.last=state
        return state
    def input_guard(self):
        w,rows=self.window()
        if w['version']!=self.config['version']:raise RuntimeError('Version changed')
        if not self.foreground_allowed(w,rows):raise RuntimeError('Focus changed')
        if self.inspect_windows(w,rows):raise RuntimeError('Unknown popup')
        box=self.n.rect(w['hwnd'])
        if self.last and self.last['layout']!=[box[2]-box[0],box[3]-box[1]]:raise RuntimeError('Layout changed after observation')
        if self.last and self.last['dpi'] != self.n.U.GetDpiForWindow(w['hwnd']):
            raise RuntimeError('DPI changed after observation')
        return box
    def execute(self, action):
        box=self.input_guard();op=action['op'];u=self.n.U
        if op=='observe':return
        if op in ('click','right_click','drag'):
            x,y=action['point']
            if not 0<=x<box[2]-box[0] or not 0<=y<box[3]-box[1]:raise ValueError('Target outside app')
            px,py=box[0]+x,box[1]+y
            def uncovered(ax, ay):
                owner = u.GetAncestor(u.WindowFromPoint(wintypes.POINT(ax,ay)), 2)
                window, rows = self.window()
                return (self.foreground_allowed(window, rows) and
                        (owner == window['hwnd'] or owner == u.GetForegroundWindow() and
                         any(r['hwnd'] == owner and r['pid'] == window['pid'] for r in rows)))
            if not uncovered(px, py):raise RuntimeError('Click target is covered')
            if op=='click': self.ui.Click(px,py,waitTime=.1)
            elif op=='right_click':self.ui.RightClick(px,py,waitTime=.15)
            else:
                dx,dy=action['to']
                if not 0<=dx<box[2]-box[0] or not 0<=dy<box[3]-box[1]:raise ValueError('Drag end outside app')
                if not uncovered(box[0]+dx, box[1]+dy):raise RuntimeError('Drag end is covered')
                self.ui.DragDrop(px,py,box[0]+dx,box[1]+dy,moveSpeed=1,waitTime=.2)
        elif op=='keys':self.ui.SendKeys(action['keys'],waitTime=.2,charMode=not action.get('physical',False),interval=.08 if action.get('physical') else .01)
        elif op=='set_text':
            self.ui.SetClipboardText(str(action['value']))
            self.input_guard();self.ui.SendKeys('{Ctrl}a',waitTime=.05)
            self.input_guard();self.ui.SendKeys('{Ctrl}v',waitTime=.1)
            if action.get('commit'):self.input_guard();self.ui.SendKeys(action['commit'],waitTime=.1)
        else:raise ValueError('Unsupported observed action: '+op)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recipe',required=True);p.add_argument('--params',required=True)
    p.add_argument('--out');p.add_argument('--dry-run',action='store_true', help='Check the recipe and inputs without opening a window or sending input');p.add_argument('--activate',action='store_true')
    p.add_argument('--data',default=str(DATA),help='Same learning store used for retrieval and promotion')
    args=p.parse_args();recipe=read(args.recipe);params=read(args.params);recipe_dir=Path(args.recipe).resolve().parent;resolved,_=prepare(recipe,params,recipe_dir)
    if args.dry_run:
        print(json.dumps({'status':'preflight-only','recipe':resolved},ensure_ascii=False,indent=2));return
    if not args.out:raise ValueError('--out is required for actual actions')
    adapter=NativeAdapter(resolved['native'])
    try:
        if args.activate:adapter.activate()
        result=run_recipe(recipe,params,adapter,args.out,recipe_dir)
        if result['status']!='complete':
            try:result['learning']=deactivate_recipe(recipe,result['recovery']['error'],Path(args.data))
            except Exception as error:result['learning']={'status':'rollback-error','error':str(error)}
            write(Path(args.out)/'result.json',result)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if result['status']!='complete':sys.exit(2)
    finally:adapter.close()


if __name__=='__main__':main()
