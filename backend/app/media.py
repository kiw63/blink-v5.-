import json, os, subprocess, tempfile
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException, UploadFile
from .config import settings

ALLOWED_IMAGE={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp'}
ALLOWED_VIDEO={'video/mp4':'.mp4','video/quicktime':'.mov','video/webm':'.webm','video/x-matroska':'.mkv'}
PHOTO_MODES={'auto','hd','sharp','4k','portrait','night','cinema'}
VIDEO_MODES={'auto','1080p','2k','4k'}
CINEMA_MODES={'natural','ultra-clear','film-contrast','golden-hour','night-cinema'}

def ffprobe(path, validate_upload=True):
    try:
        cmd=['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height,r_frame_rate','-of','json',str(path)]
        result=subprocess.run(cmd,timeout=20,capture_output=True,text=True,check=True)
        data=json.loads(result.stdout)
        stream=next((s for s in data.get('streams',[]) if s.get('codec_type')=='video'),None)
        if not stream: raise ValueError('No video stream')
        duration=float(data.get('format',{}).get('duration') or 0)
        if duration<=0 or (validate_upload and duration>settings.max_video_seconds): raise ValueError('Durasi video melebihi batas atau tidak diketahui')
        w=int(stream['width']); h=int(stream['height'])
        if w<=0 or h<=0: raise ValueError('Dimensi video tidak valid')
        if validate_upload and w*h>1920*1080: raise ValueError('Unggahan video maksimal 1080p untuk pembatasan biaya')
        rate=stream.get('r_frame_rate','0/1'); n,d=map(int,rate.split('/'))
        fps=n/d if d else 0
        if fps<=0 or fps>120.1: raise ValueError('Frame rate video tidak valid (maksimal 120 FPS input)')
        return {'width':w,'height':h,'fps':fps,'duration':duration}
    except (subprocess.CalledProcessError,ValueError,KeyError,IndexError,TimeoutError,FileNotFoundError,TypeError) as exc:
        raise HTTPException(422,f'Video tidak valid: {exc}')

async def receive_upload(upload:UploadFile,kind):
    images=kind=='image'
    accepted=ALLOWED_IMAGE if images else ALLOWED_VIDEO
    if upload.content_type not in accepted: raise HTTPException(415,'Format file tidak didukung')
    limit=(settings.max_photo_mb if images else settings.max_video_mb)*1024*1024
    temp=tempfile.NamedTemporaryFile(delete=False,suffix=accepted[upload.content_type])
    size=0
    try:
        with temp:
            while True:
                chunk=await upload.read(1024*1024)
                if not chunk: break
                size+=len(chunk)
                if size>limit: raise HTTPException(413,'Ukuran file melebihi batas')
                temp.write(chunk)
        if size==0: raise HTTPException(422,'File kosong')
        if images:
            try:
                with Image.open(temp.name) as im:
                    im.verify()
                with Image.open(temp.name) as im:
                    w,h=im.size
                    if w<=0 or h<=0: raise HTTPException(422,'Dimensi gambar tidak valid')
                    if w*h>32_000_000: raise HTTPException(413,'Gambar terlalu besar')
                    if im.format not in ('PNG','JPEG','WEBP'): raise HTTPException(415,'Format gambar salah')
                    # Reencode strips EXIF/metadata; no disguised payload retained
                    safe=ImageOps.exif_transpose(im).convert('RGB')
                    clean=temp.name+'.png'; safe.save(clean,format='PNG')
                os.unlink(temp.name)
                return clean,'.png',{'width':w,'height':h}
            except (UnidentifiedImageError, OSError, ValueError): raise HTTPException(422,'Gambar tidak valid')
        return temp.name,accepted[upload.content_type],ffprobe(temp.name)
    except Exception:
        if os.path.exists(temp.name): os.unlink(temp.name)
        raise
