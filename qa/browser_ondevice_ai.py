"""Offline Chromium functional checks; 'about:blank' harness cannot test persistent backup.
Model and inference are the actual shipped source, embedded as data ESM for browser policy.
"""
import asyncio, json, base64, shutil
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]

def data_url(src):return 'data:text/javascript;base64,'+base64.b64encode(src.encode()).decode()

async def run():
    backup=(ROOT/'docs/assets/smart-backup.js').read_text()
    model=(ROOT/'docs/assets/tiny-restore-v1.json').read_text()
    ai=(ROOT/'docs/assets/ondevice-ai.js').read_text()
    ai=ai.replace("'./smart-backup.js'",repr(data_url(backup)))
    ai=ai.replace("new URL('./tiny-restore-v1.json',import.meta.url)",repr('data:application/json;base64,'+base64.b64encode(model.encode()).decode()))
    src=data_url(ai)
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=shutil.which('chromium') or None,headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream'])
        page=await browser.new_page()
        await page.set_content('<!doctype html><html><body>BLINK local AI</body></html>')
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        result=await page.evaluate('''async ({url})=> {
            const ai=await import(url);
            const model=await ai.loadLocalModel();
            if(model.conv1.length!==4)throw Error('CNN weights missing');
            const source=document.createElement('canvas');source.width=144;source.height=80;
            const c=source.getContext('2d');c.fillStyle='#ddd';c.fillRect(0,0,144,80);
            c.fillStyle='#111';c.fillRect(0,0,72,80);
            const png=await new Promise(ok=>source.toBlob(ok,'image/png'));
            const a=await ai.enhanceOnDevicePhoto(png,'sharp','image/jpeg',{backup:false});
            if(!a.neuralInference||a.width!==3840||a.height!==2133||!a.blob.size)throw Error('CNN photo invalid');
            const bmp=await createImageBitmap(a.blob);
            const probe=document.createElement('canvas');probe.width=2;probe.height=1;
            const pc=probe.getContext('2d');pc.drawImage(bmp,10,10,1,1,0,0,1,1);pc.drawImage(bmp,2500,1000,1,1,1,0,1,1);
            const pixels=Array.from(pc.getImageData(0,0,2,1).data);
            if(!(pixels[0]<130&&pixels[4]>130))throw Error('CNN lost image contrast');
            bmp.close();
            Object.defineProperty(source,'videoWidth',{value:144});
            Object.defineProperty(source,'videoHeight',{value:80});
            const target=document.createElement('canvas');target.width=3840;target.height=2160;
            const proc=ai.makeOnDeviceVideoProcessor(model,{maxLong:120});
            const ctx=target.getContext('2d');proc.render(source,ctx,3840,2160);
            c.fillStyle='#ff9c00';c.fillRect(72,0,72,80);
            proc.render(source,ctx,3840,2160);
            const stats=proc.stats();proc.dispose();
            if(stats.framesInferred!==2)throw Error('Neural video frame inference not used');
            return {model:ai.modelSource(),photo:[a.width,a.height],bytes:a.blob.size,
                pixels,neuralVideoFrames:stats.framesInferred,videoCanvas:[target.width,target.height]};
        }''',{'url':src})
        assert not errors,errors
        print(json.dumps(result,indent=2))
        await browser.close()
if __name__=='__main__':asyncio.run(run())
