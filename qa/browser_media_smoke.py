"""Chromium tests on about:blank because container blocks local HTTP navigation.
Tests actual browser pixel processing, dimensions and MediaRecorder encoding.
Not a substitute for physical Android/iPhone testing or trained-AI quality testing.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
import shutil, os

ROOT=Path(__file__).resolve().parents[1]
MEDIA=(ROOT/'docs/assets/media.js').read_text()
INTRO=(ROOT/'docs/assets/intro.js').read_text()
ULTRA=(ROOT/'docs/assets/ultra4k.js').read_text()
ONDEVICE=(ROOT/'docs/assets/ondevice-ai.js').read_text()
BACKUP=(ROOT/'docs/assets/smart-backup.js').read_text()
MODEL=(ROOT/'docs/assets/tiny-restore-v1.json').read_text()

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=(shutil.which('chromium') or shutil.which('chromium-browser') or None),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream'])
    page=browser.new_page(viewport={'width':1280,'height':850})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('about:blank')
    page.set_content('<html><body><div id="app"></div></body></html>')
    result=page.evaluate('''async ({code,ultraCode,onDeviceCode,backupCode,model})=>{
       const backup=URL.createObjectURL(new Blob([backupCode],{type:'text/javascript'}));
       const modelUrl='data:application/json;base64,'+btoa(model);
       const ai=URL.createObjectURL(new Blob([onDeviceCode.replace("'./smart-backup.js'",`'${backup}'`).replace("new URL('./tiny-restore-v1.json',import.meta.url)",JSON.stringify(modelUrl))],{type:'text/javascript'}));
       const ultra=URL.createObjectURL(new Blob([ultraCode],{type:'text/javascript'}));
       const u=URL.createObjectURL(new Blob([code.replaceAll("'./ultra4k.js'",`'${ultra}'`).replaceAll("'./smart-backup.js'",`'${backup}'`).replaceAll("'./ondevice-ai.js'",`'${ai}'`)],{type:'text/javascript'}));
       const mod=await import(u);
       const reference=document.createElement('canvas');reference.width=480;reference.height=270;
       const ctx=reference.getContext('2d');
       const gradient=ctx.createLinearGradient(0,0,480,270);
       gradient.addColorStop(0,'#15143a');gradient.addColorStop(.5,'#a954b8');gradient.addColorStop(1,'#6ce9f0');
       ctx.fillStyle=gradient;ctx.fillRect(0,0,480,270);
       for(let i=0;i<150;i++){
         ctx.strokeStyle=(i%2)?'#fff8':'#0008';ctx.beginPath();ctx.moveTo(i*3,10);ctx.lineTo(i*3,260);ctx.stroke();
       }
       const original=await mod.canvasBlob(reference,'image/png');
       const enhanced=await mod.localEnhance(original,'sharp','2160','image/png');
       const before=new Uint8Array(await original.arrayBuffer());
       const after=new Uint8Array(await enhanced.blob.arrayBuffer());
       const decoded=await createImageBitmap(enhanced.blob);
       const outputCanvas=document.createElement('canvas');outputCanvas.width=decoded.width;outputCanvas.height=decoded.height;
       const dest=outputCanvas.getContext('2d');dest.drawImage(decoded,0,0);
       const recCanvas=document.createElement('canvas');recCanvas.width=160;recCanvas.height=90;
       const rctx=recCanvas.getContext('2d');rctx.fillStyle='purple';rctx.fillRect(0,0,160,90);
       let mediaTest={supported:!!recCanvas.captureStream && !!mod.videoMime()};
       if(mediaTest.supported){
         const stream=recCanvas.captureStream(30);
         const recording=mod.createRecorder(stream);
         let f=0;const timer=setInterval(()=>{rctx.fillStyle=f++%2?'purple':'cyan';rctx.fillRect(0,0,160,90);rctx.font='24px sans-serif';rctx.fillText('BLINK',12,48);},33);
         await new Promise(r=>setTimeout(r,1800));clearInterval(timer);
         recording.recorder.stop();
         const video=await recording.done;
         mediaTest={supported:true,bytes:video.size,mime:video.type};
         stream.getTracks().forEach(t=>t.stop());
       }
       return {
          originalBytes:before.length,processedBytes:after.length,
          width:enhanced.width,height:enhanced.height,
          decodedWidth:decoded.width,decodedHeight:decoded.height,
          isNotOriginal:before.length!==after.length,
          mediaRecorder:mediaTest, label:enhanced.label
       };
    }''',{'code':MEDIA,'ultraCode':ULTRA,'onDeviceCode':ONDEVICE,'backupCode':BACKUP,'model':MODEL})
    print('BROWSER_MEDIA',json.dumps(result,ensure_ascii=False))
    assert result['width']==3840 and result['height']==2160
    assert result['decodedWidth']==3840 and result['decodedHeight']==2160
    assert result['isNotOriginal']
    assert result['mediaRecorder']['supported'] and result['mediaRecorder']['bytes']>1500
    print('BROWSER_ERRORS',errors)
    assert not errors
    browser.close()
