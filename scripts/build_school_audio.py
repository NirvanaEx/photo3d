"""Prepare recorded foley for the expanded school. No synthesized footsteps.

Sources are cached in data/audio_sources/school. See game/assets/audio/school/CREDITS.md.
FFmpeg decodes/EQs; numpy balances levels, fades and creates a seamless ambience.
"""
from pathlib import Path
import json
import subprocess
import wave
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'data/audio_sources/school'
OUT=ROOT/'game/assets/audio/school'
FF='C:/ffmpeg/bin/ffmpeg.exe'
SR=44100
REPORT=[]


def decode(path,filters='anull',channels=1):
    p=subprocess.run([FF,'-v','error','-i',str(path),'-af',filters,'-f','f32le','-ac',str(channels),'-ar',str(SR),'-'],capture_output=True,check=True)
    return np.frombuffer(p.stdout,dtype=np.float32).copy().reshape(-1,channels)


def encode(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    data=np.nan_to_num(data)
    peak=float(np.max(abs(data)))
    if peak>.88:data*=.88/peak
    subprocess.run([FF,'-v','error','-y','-f','f32le','-ac',str(data.shape[1]),'-ar',str(SR),'-i','-','-c:a','libvorbis','-q:a','5',str(path)],input=data.astype(np.float32).tobytes(),check=True)
    REPORT.append({'file':str(path.relative_to(OUT)),'duration':round(len(data)/SR,3),'peak':round(float(np.max(abs(data))),4),'rms':round(float(np.sqrt(np.mean(data**2))),4)})


def normalize(data,rms=.09):
    data-=np.mean(data,axis=0)
    active=np.max(abs(data),axis=1)>.003
    if np.any(active):
        value=float(np.sqrt(np.mean(data[active]**2)));data*=min(rms/max(value,.001),8.0)
    fade=min(int(SR*.012),len(data)//4)
    data[:fade]*=np.linspace(0,1,fade)[:,None];data[-fade:]*=np.linspace(1,0,fade)[:,None]
    return data


def steps():
    for surface,kenney_name in [('wood','wood'),('tile','concrete'),('grass','grass'),('gravel',None)]:
        for gait in ('walk','run'):
            # Separate recorded variants for walking and running, with restrained EQ.
            if gait=='run' and kenney_name:
                sources=sorted((SRC/'kenney/Audio').glob('footstep_'+kenney_name+'_*.ogg'))
            else:sources=sorted((ROOT/f'game/assets/audio/steps/{surface}').glob('*.ogg'))[:8]
            if not sources:raise RuntimeError(f'Missing recorded steps for {surface}/{gait}')
            for index,source in enumerate(sources):
                low=5800 if gait=='run' else 4400
                data=decode(source,f'highpass=f=65,lowpass=f={low}')
                active=np.flatnonzero(np.max(abs(data),axis=1)>.005)
                if len(active):data=data[max(0,active[0]-220):min(len(data),active[-1]+int(SR*.035))]
                # Preserve the original single contact; never layer a second impact.
                data=normalize(data,.105 if gait=='run' else .075)
                encode(OUT/f'steps/{surface}/{gait}/{index:02}.ogg',data)


def ambience():
    birds=normalize(decode(SRC/'birds.ogg','highpass=f=150,lowpass=f=11000',2),.08)
    n=min(int(SR*1.2),len(birds)//8)
    fade=np.linspace(0,1,n)[:,None]
    loop=birds[n:].copy();loop[-n:]=birds[-n:]*(1-fade)+birds[:n]*fade
    encode(OUT/'garden.ogg',loop)
    room=normalize(decode(ROOT/'game/assets/audio/room_tone.wav','highpass=f=55,lowpass=f=900',2),.027)
    encode(OUT/'room.ogg',room)


def door_sounds():
    for name,number in [('door_open',1),('door_close',6),('door_latch',3)]:
        data=normalize(decode(SRC/f'door/door-{number:02}.flac','highpass=f=65,lowpass=f=7000'),.13)
        encode(OUT/(name+'.ogg'),data)


def demo():
    # 18-second listening sample: wood walk/run, tile, grass, then a door.
    clips=[]
    for surface,gait,count,gap in [('wood','walk',5,.47),('wood','run',7,.28),('tile','walk',5,.47),('grass','run',7,.28)]:
        pool=sorted((OUT/f'steps/{surface}/{gait}').glob('*.ogg'))
        segment=np.zeros((int(SR*(count*gap+.45)),1),np.float32)
        for i in range(count):
            a=decode(pool[i%len(pool)])*.7;start=int(i*gap*SR);end=min(start+len(a),len(segment));segment[start:end]+=a[:end-start]
        clips.extend([segment,np.zeros((int(SR*.55),1),np.float32)])
    clips.extend([decode(OUT/'door_open.ogg'),np.zeros((int(SR*.65),1),np.float32),decode(OUT/'door_close.ogg')])
    data=np.concatenate(clips)
    path=ROOT/'data/output/loc_classroom_v2/school_audio_demo.wav'
    with wave.open(str(path),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(SR);w.writeframes((np.clip(data,-.95,.95)*32767).astype('<i2').tobytes())


if __name__=='__main__':
    steps();ambience();door_sounds();demo()
    (OUT/'audio_manifest.json').write_text(json.dumps(REPORT,indent=2),encoding='utf-8')
    print('SCHOOL_AUDIO_DONE',len(REPORT),'files; peak',max(x['peak'] for x in REPORT))
