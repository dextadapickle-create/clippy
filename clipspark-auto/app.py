import os, re, json, uuid, shutil, subprocess, threading, math, zipfile
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

ROOT=Path(__file__).resolve().parent
WORK=ROOT/'jobs'; WORK.mkdir(exist_ok=True)
MAX_MB=int(os.getenv('MAX_UPLOAD_MB','1500'))
app=FastAPI(title='CLIPSPARK Auto')
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
jobs={}; lock=threading.Lock(); model=None; model_lock=threading.Lock()

def run(cmd):
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if p.returncode: raise RuntimeError((p.stderr or p.stdout)[-1500:])
    return p.stdout

def probe(path):
    return json.loads(run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)]))

def duration(path): return float(probe(path)['format']['duration'])
def update(jid,**kw):
    with lock: jobs[jid].update(kw)

def transcription(path):
    global model
    try:
        from faster_whisper import WhisperModel
        with model_lock:
            if model is None: model=WhisperModel(os.getenv('WHISPER_MODEL','base'),device='cpu',compute_type='int8')
            segments,_=model.transcribe(str(path),beam_size=3,word_timestamps=True,vad_filter=True)
            return [{'start':float(s.start),'end':float(s.end),'text':s.text.strip(),'words':[{'start':float(w.start),'end':float(w.end),'text':w.word.strip()} for w in (s.words or [])]} for s in segments]
    except Exception as e:
        raise RuntimeError('Transcription failed: '+str(e))

def highlights(segs,total,count=5):
    # Speech density, punchy keywords, question/exclamation hooks and novelty.
    # This is a heuristic ranking, not a trained viral-prediction model.
    windows=[]; length=min(42,max(12,total/5))
    step=max(6,length/3)
    for st in [i*step for i in range(int(max(0,total-length)/step)+1)]:
        en=min(total,st+length)
        hits=[s for s in segs if s['end']>st and s['start']<en]
        words=' '.join(s['text'] for s in hits)
        n=len(words.split()); excitement=len(re.findall(r'\b(no way|what|wait|crazy|insane|oh my|unbelievable|actually|bro|wow|look|never|how|why|clutch|win|lost|funny)\b',words,re.I))
        score= min(1,n/max(1,(en-st)*2.6))*45 + min(35,excitement*7)+ min(12,words.count('!')*4+words.count('?')*3)+ (8 if n>20 else 0)
        if hits:
            st=max(0,min(st,hits[0]['start'])); en=min(total,max(en,hits[-1]['end']))
        windows.append({'start':round(st,2),'end':round(en,2),'score':round(min(99,score)),'reason':'High speech energy and reaction cues' if excitement else 'Strong spoken segment','text':words[:180]})
    if not windows: windows=[{'start':0,'end':min(total,30),'score':40,'reason':'Opening segment','text':''}]
    windows.sort(key=lambda x:x['score'],reverse=True); chosen=[]
    for w in windows:
        if all(max(0,min(w['end'],v['end'])-max(w['start'],v['start']))<min(w['end']-w['start'],v['end']-v['start'])*.35 for v in chosen): chosen.append(w)
        if len(chosen)>=count:break
    return chosen

def ass_time(t):
    t=max(0,t); h=int(t//3600); m=int(t%3600//60); s=t%60
    return f'{h}:{m:02}:{s:05.2f}'
def ass_escape(s): return s.replace('\\','').replace('{','').replace('}','').replace('\n',' ')
def subtitle_file(path,segs,start,end):
    header='''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,Arial,78,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,5,2,2,80,80,340,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events=[]
    for seg in segs:
        words=[w for w in seg.get('words',[]) if w['end']>start and w['start']<end]
        if not words:
            if seg['end']>start and seg['start']<end:
                events.append((max(0,seg['start']-start),min(end-start,seg['end']-start),seg['text']))
            continue
        for i in range(0,len(words),4):
            chunk=words[i:i+4]; a=max(0,chunk[0]['start']-start); b=min(end-start,chunk[-1]['end']-start)
            events.append((a,max(a+.12,b),' '.join(w['text'] for w in chunk).upper()))
    with open(path,'w',encoding='utf-8') as f:
        f.write(header)
        for a,b,txt in events:
            f.write(f'Dialogue: 0,{ass_time(a)},{ass_time(b)},Pop,,0,0,0,,{{\\fad(70,70)\\fscx105\\fscy105}}{ass_escape(txt)}\n')

def process(jid,source,link,clip_count):
    folder=WORK/jid
    try:
        update(jid,status='processing',stage='Preparing video',progress=8)
        video=folder/'source.mp4'
        if link:
            if not re.match(r'^https?://(www\.)?(youtube\.com|youtu\.be)/',link,re.I): raise RuntimeError('Only YouTube URLs are accepted')
            run(['yt-dlp','--no-playlist','--max-filesize',f'{MAX_MB}M','-f','bv*+ba/b','--merge-output-format','mp4','-o',str(folder/'source.%(ext)s'),link])
            files=[p for p in folder.glob('source.*') if p.suffix.lower() in ('.mp4','.mkv','.webm','.mov')]
            if not files: raise RuntimeError('YouTube download failed or unavailable')
            video=files[0]
        elif source: video=source
        else: raise RuntimeError('No video supplied')
        total=duration(video)
        if total<3: raise RuntimeError('Video must be at least 3 seconds')
        update(jid,stage='Transcribing speech',progress=22)
        segs=transcription(video)
        update(jid,stage='Ranking moments',progress=48)
        picks=highlights(segs,total,clip_count)
        clips=[]
        for i,pick in enumerate(picks):
            update(jid,stage=f'Rendering short {i+1} of {len(picks)}',progress=52+int(43*i/len(picks)))
            ass=folder/f'caption_{i+1}.ass'; subtitle_file(ass,segs,pick['start'],pick['end'])
            out=folder/f'short_{i+1}.mp4'
            # Center-crop keeps a predictable vertical frame; true subject tracking needs a vision model.
            vf="scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,ass="+str(ass).replace('\\','/').replace(':','\\:').replace("'","\\'")
            run(['ffmpeg','-y','-ss',str(pick['start']),'-t',str(pick['end']-pick['start']),'-i',str(video),'-vf',vf,'-map','0:v:0','-map','0:a?','-c:v','libx264','-preset','veryfast','-crf','23','-c:a','aac','-b:a','160k','-movflags','+faststart',str(out)])
            clips.append({'filename':out.name,**pick})
        with zipfile.ZipFile(folder/'shorts.zip','w',compression=zipfile.ZIP_STORED) as z:
            for c in clips:z.write(folder/c['filename'],c['filename'])
        update(jid,status='done',stage='Complete',progress=100,clips=clips)
    except Exception as e: update(jid,status='error',stage=str(e),error=str(e))

@app.get('/')
def home():return FileResponse(ROOT/'static'/'index.html')
@app.post('/api/jobs')
async def create(file:UploadFile|None=File(None),url:str=Form(''),count:int=Form(4)):
    if not file and not url.strip():raise HTTPException(400,'Upload a video or paste a YouTube URL')
    if file and url.strip():raise HTTPException(400,'Choose a file or a URL, not both')
    jid=uuid.uuid4().hex; folder=WORK/jid;folder.mkdir()
    source=None
    if file:
        if Path(file.filename or '').suffix.lower() not in ('.mp4','.mov','.mkv','.webm','.avi'):raise HTTPException(400,'Unsupported video format')
        source=folder/'upload'+Path(file.filename).suffix.lower();size=0
        with open(source,'wb') as f:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>MAX_MB*1024*1024:
                    f.close();source.unlink(missing_ok=True);raise HTTPException(413,'Video too large')
                f.write(chunk)
    jobs[jid]={'id':jid,'status':'queued','stage':'Queued','progress':0,'clips':[]}
    threading.Thread(target=process,args=(jid,source,url.strip(),max(1,min(8,count))),daemon=True).start()
    return {'id':jid}
@app.get('/api/jobs/{jid}')
def status(jid:str):
    if jid not in jobs:raise HTTPException(404,'Job not found')
    return jobs[jid]
@app.get('/api/jobs/{jid}/download/{name}')
def download(jid:str,name:str):
    if jid not in jobs or jobs[jid]['status']!='done':raise HTTPException(404,'Job not ready')
    if name!='shorts.zip' and not re.fullmatch(r'short_\d+\.mp4',name):raise HTTPException(400,'Invalid filename')
    path=WORK/jid/name
    if not path.exists():raise HTTPException(404,'Not found')
    return FileResponse(path,filename=name)
