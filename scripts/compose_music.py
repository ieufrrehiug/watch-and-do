"""A reproducible, original 84-BPM arrangement. Standard-library MIDI + local FluidSynth."""
from pathlib import Path
import argparse, json, math, shutil, struct, subprocess, tempfile

TPQ=480

def vlq(value):
    output=[value & 127]
    while value>>7:
        value >>= 7
        output.insert(0, (value&127)|128)
    return bytes(output)

def make_midi(target, bpm=84, duration=34.5):
    beat=60/bpm
    events=[]
    def add(t, data): events.append((max(0,round(t/beat*TPQ)),data))
    def note(ch,pitch,t,length,vel):
        if t<0 or t>=duration-.45: return
        add(t,bytes([0x90|ch,pitch,vel]))
        add(min(t+length,duration-.28),bytes([0x80|ch,pitch,0]))
    tempo=round(60000000/bpm)
    add(0,b'\xff\x51\x03'+tempo.to_bytes(3,'big'))
    add(0,b'\xff\x58\x04\x04\x02\x18\x08')
    for ch,program,volume,pan in [(0,0,88,54),(1,45,74,77),(2,48,53,61),(3,32,83,64),(4,11,69,45)]:
        add(0,bytes([0xc0|ch,program]))
        for ctrl,val in [(7,volume),(10,pan),(91,35)]:add(0,bytes([0xb0|ch,ctrl,val]))
    # Opening, harmonic cells, quiet interlude and closing cadence.
    chords=[(50,57,65),(46,53,62),(53,60,69),(48,55,64),(43,50,58),(45,52,61),(50,57,65),(50,57,65),(46,53,62),(53,60,69),(53,60,69)]
    for n in [50,57,65]: note(2,n,0,2.8,47)
    for k in range(4):
        note(3,38,.142857+k*beat,.38,62 if k%2==0 else 45)
        note(4,[69,72,77,76][k],.142857+k*beat,1.2,48)
    bars = max(len(chords), math.ceil((duration-3)/(4*beat)))
    for bar in range(bars):
        section = bar % (len(chords)-1) if bar < bars-1 else len(chords)-1
        chord = chords[section]
        start=3+bar*4*beat
        if start>=duration: break
        quiet=section==6
        for pitch in chord: note(2,pitch,start,4*beat-.1,28 if quiet else 48)
        if quiet:
            note(0,81,start,2.1,38)
            continue
        for k in range(4):
            t=start+k*beat
            note(3,chord[0]-12,t,.38,66 if k in [0,2] else 44)
            if section<10:
                note(9,36,t,.09,35 if k%2 else 44)
                note(1,chord[k%3]+12,t+.5*beat,.32,46+(k%2)*8)
            if k in [0,2]:note(0,chord[(k//2+bar)%3]+24,t,.95,54)
        if section==9:
            for k in range(8): note(4,chord[k%3]+24,start+k*.5*beat,.42,41)
        if section==10:
            for k,pitch in enumerate([65,69,72,77]):note(0,pitch,start+k*.11,2.4,54-k*3)
    for ch in range(10): add(duration,bytes([0xb0|ch,123,0]))
    events.sort(key=lambda item:(item[0],item[1][0]&0xf0 !=0x80))
    out=bytearray(); last=0
    for tick,data in events:
        out.extend(vlq(tick-last));out.extend(data);last=tick
    out.extend(b'\x00\xff\x2f\x00')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(b'MThd'+struct.pack('>IHHH',6,0,1,TPQ)+b'MTrk'+struct.pack('>I',len(out))+out)
    return {'bpm':bpm,'duration':duration,'beatOriginSeconds':3,'events':len(events),'originalArrangement':True,'audition':'not performed by this script'}

def render(midi, wav, project, duration, synth=None, soundfont=None):
    synth = synth or shutil.which("fluidsynth") or next((project/"tools/fluidsynth").rglob("fluidsynth.exe"), None)
    if not synth:
        raise ValueError("Supply --fluidsynth or install FluidSynth on PATH.")
    sf = soundfont or project/"assets/soundfont/GeneralUser-GS.sf2"
    if not sf.is_file():
        raise FileNotFoundError(f"Supply a licensed soundfont with --soundfont: {sf}")
    with tempfile.TemporaryDirectory(dir=wav.parent) as temp:
        raw = Path(temp)/"render.wav"
        final = Path(temp)/"final.wav"
        subprocess.run([str(synth), "-ni", "-r", "48000", "-g", "0.7", "-F", str(raw), str(sf), str(midi)], check=True)
        fade = min(.95, duration/4)
        filters = f"afade=t=in:d=0.12,afade=t=out:st={duration-fade}:d={fade},loudnorm=I=-16:TP=-1.5:LRA=9"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(raw), "-af", filters,
                        "-t", str(duration), "-ar", "48000", "-ac", "2", str(final)], check=True)
        final.replace(wav)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--midi-only", action="store_true")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--bpm", type=float, default=84)
    parser.add_argument("--duration", type=float, default=34.5)
    parser.add_argument("--soundfont", type=Path)
    parser.add_argument("--fluidsynth", help="Path or command name of a local FluidSynth executable")
    args = parser.parse_args()
    if not math.isfinite(args.bpm) or not 4 <= args.bpm <= 960 or not math.isfinite(args.duration) or args.duration <= 0:
        parser.error("Choose BPM in [4, 960] and a finite, positive duration.")
    midi = args.project/"assets/audio/score.mid"
    info = make_midi(midi, args.bpm, args.duration)
    if not args.midi_only:
        render(midi, midi.with_suffix(".wav"), args.project, args.duration, args.fluidsynth, args.soundfont)
    (midi.parent/"music.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info))
