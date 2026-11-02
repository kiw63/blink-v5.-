"""4K WebM bytes generated from REAL local CNN processed frames; synthetic test media."""
import asyncio,base64,json,subprocess,shutil
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
def js_data(s):return 'data:text/javascript;base64,'+base64.b64encode(s.encode()).decode()
async def run():
  backup=(ROOT/'docs/assets/smart-backup.js').read_text()
  model=(ROOT/'docs/assets/tiny-restore-v1.json').read_text()
  src=(ROOT/'docs/assets/ondevice-ai.js').read_text().replace("'./smart-backup.js'",repr(js_data(backup)))
  src=src.replace("new URL('./tiny-restore-v1.json',import.meta.url)",repr('data:application/json;base64,'+base64.b64encode(model.encode()).decode()))
  async with async_playwright() as p:
    browser=await p.chromium.launch(executable_path=shutil.which('chromium') or None,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
    page=await browser.new_page();await page.set_content('<html>BLINK video AI test</html>')
    encoded=await page.evaluate('''async (src)=>{
      const {loadLocalModel,makeOnDeviceVideoProcessor}=await import(src);
      const model=await loadLocalModel();
      const source=document.createElement('canvas');source.width=80;source.height=45;
      const c=source.getContext('2d');Object.defineProperty(source,'videoWidth',{value:80});Object.defineProperty(source,'videoHeight',{value:45});
      const target=document.createElement('canvas');target.width=3840;target.height=2160;
      const proc=makeOnDeviceVideoProcessor(model,{maxLong:80});const dest=target.getContext('2d');
      if(!target.captureStream)throw Error('captureStream absent');
      const stream=target.captureStream(0);const types=['video/webm;codecs=vp8','video/webm'];
      const type=types.find(t=>MediaRecorder.isTypeSupported(t));if(!type)throw Error('No WebM recorder');
      const rec=new MediaRecorder(stream,{mimeType:type,videoBitsPerSecond:1200000});const chunks=[];
      rec.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
      const done=new Promise((res,rej)=>{rec.onstop=res;rec.onerror=e=>rej(e.error||Error('recorder failed'));});
      rec.start(300);
      for(let i=0;i<4;i++){
        c.fillStyle=i%2?'#ee0080':'#26aaff';c.fillRect(0,0,80,45);
        c.fillStyle='#111';c.fillRect(i*12,10,20,20);
        proc.render(source,dest,3840,2160);
        stream.getVideoTracks()[0].requestFrame();
        await new Promise(ok=>setTimeout(ok,600));
      }
      await new Promise(ok=>setTimeout(ok,1500));
      rec.stop();await done;stream.getTracks().forEach(t=>t.stop());
      const b=new Blob(chunks,{type});if(!b.size)throw Error('No video bytes');
      const bytes=new Uint8Array(await b.arrayBuffer());
      let binary='';for(let i=0;i<bytes.length;i++)binary+=String.fromCharCode(bytes[i]);
      return {frames:proc.stats().framesInferred,type,content:btoa(binary)};
    }''',js_data(src))
    assert encoded['frames']==4
    file=ROOT/'qa/blink-cnn-4k-video-smoke.webm';file.write_bytes(base64.b64decode(encoded['content']))
    video=json.loads(subprocess.check_output(['ffprobe','-v','quiet','-print_format','json','-show_streams',str(file)]))
    v=next(v for v in video['streams'] if v['codec_type']=='video');assert (v['width'],v['height'])==(3840,2160),v
    print('PASS local CNN video recorded',len(file.read_bytes()),'bytes',v['width'],v['height'],'frames processed',encoded['frames'])
    await browser.close()
if __name__=='__main__':asyncio.run(run())
