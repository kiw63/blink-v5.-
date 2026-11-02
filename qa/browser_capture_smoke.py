"""Test actual BLINK capture controls with a synthetic MediaStream in Chromium.
Does NOT replace permission/hardware tests on iOS and Android.
"""
import base64, io, re, json
from pathlib import Path
from playwright.sync_api import sync_playwright
import shutil, os
root=Path(__file__).resolve().parents[1]/'docs'
html=(root/'index.html').read_text()
html=re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>','',html)
html=re.sub(r'<script[^>]*>.*?</script>','',html,flags=re.S)
html=re.sub(r'<link[^>]*rel="stylesheet"[^>]*>','',html)
logo='data:image/png;base64,'+base64.b64encode((root/'assets/logo.png').read_bytes()).decode()
html=html.replace('./assets/logo.png',logo)
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=(shutil.which('chromium') or shutil.which('chromium-browser') or None),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
 page=b.new_page(viewport={'width':1040,'height':880})
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('about:blank');page.set_content(html)
 page.add_style_tag(content=(root/'assets/style.css').read_text());page.add_style_tag(content=(root/'assets/intro.css').read_text())
 sources={name:(root/f'assets/{name}.js').read_text() for name in ('ultra4k','smart-backup','ondevice-ai','media','studio-api','intro','app')}
 sources['model']=(root/'assets/tiny-restore-v1.json').read_text()
 sources['app']=(sources['app']
    .replace("localStorage.getItem('blink_api_origin')","''")
    .replace("localStorage.setItem('blink_api_origin',base);",'')
    .replace('window.history.replaceState(', '(()=>{} )(')
    # test-only: the in-memory about:blank page is not a secure origin.
    .replace('if(!window.isSecureContext)throw new Error', 'if(false)throw new Error'))
 info=page.evaluate('''async sources=>{
  const camera=document.createElement('canvas');camera.width=640;camera.height=360;
  const ctx=camera.getContext('2d');let counter=0;
  window.__fakeCameraTimer=setInterval(()=>{
    ctx.fillStyle=counter++%2?'#162450':'#6644c3';ctx.fillRect(0,0,640,360);
    ctx.fillStyle='#fff';ctx.font='50px sans-serif';ctx.fillText('BLINK TEST VIDEO',75,190);
  },32);
  const stream=camera.captureStream(30);window.__fakeStream=stream;
  Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:async()=>stream}});
  window.BLINK_PUBLIC_CONFIG={apiBase:''};
  const blobUrl=s=>URL.createObjectURL(new Blob([s],{type:'text/javascript'}));
  const modules={};modules.ultra4k=blobUrl(sources.ultra4k);
  modules['smart-backup']=blobUrl(sources['smart-backup']);
  const model='data:application/json;base64,'+btoa(sources.model);
  sources['ondevice-ai']=sources['ondevice-ai'].replace("'./smart-backup.js'",`'${modules['smart-backup']}'`).replace("new URL('./tiny-restore-v1.json',import.meta.url)",JSON.stringify(model));
  modules['ondevice-ai']=blobUrl(sources['ondevice-ai']);
  sources.media=sources.media.replaceAll("'./ultra4k.js'",`'${modules.ultra4k}'`).replaceAll("'./smart-backup.js'",`'${modules['smart-backup']}'`).replaceAll("'./ondevice-ai.js'",`'${modules['ondevice-ai']}'`);
  for(const n of ['media','studio-api','intro'])modules[n]=blobUrl(sources[n]);
  let app=sources.app;for(const n in modules)app=app.replace(`'./${n}.js'`,`'${modules[n]}'`);
  await import(blobUrl(app));
  return {track:stream.getVideoTracks()[0].readyState};
 }''',sources)
 page.locator('#intro-enter').click();page.wait_for_timeout(1000)
 page.locator('#camera-start').click()
 page.wait_for_function('document.querySelector("#camera-snap").disabled===false',timeout=6000)
 page.locator('#camera-snap').click()
 page.wait_for_function('!document.querySelector("#camera-result").hidden',timeout=6000)
 still=page.locator('#camera-result-meta').inner_text()
 assert '640' in still and '360' in still
 page.locator('[data-tab="live"]').click()
 page.locator('#live-capture').click()
 page.wait_for_function('!document.querySelector("#live-result").hidden',timeout=12000)
 live=page.locator('#live-meta').inner_text()
 assert '640' in live and 'Klip' in live
 page.locator('[data-tab="video"]').click()
 page.locator('#video-record').click()
 page.wait_for_function('document.querySelector("#video-stop").disabled===false',timeout=6000)
 page.wait_for_timeout(1500)
 page.locator('#video-stop').click()
 page.wait_for_function('document.querySelector("#video-result").hidden===false',timeout=10000)
 video_record=page.locator('#video-meta').inner_text()
 detail=page.evaluate('''async()=>{
  const still=document.querySelector('#live-still');const video=document.querySelector('#live-motion');
  const response=await fetch(video.src);const blob=await response.blob();
  const a=await fetch(still.src);const image=await a.blob();
  const recorded=document.querySelector('#video-result-preview');const recordedBlob=await (await fetch(recorded.src)).blob();
  clearInterval(window.__fakeCameraTimer);window.__fakeStream.getTracks().forEach(t=>t.stop());
  return {photoBytes:image.size,videoBytes:blob.size,videoMime:blob.type,videoReady:video.readyState,cinematicBytes:recordedBlob.size,cinematicMime:recordedBlob.type};
 }''')
 print('BROWSER_CAPTURE',json.dumps({'camera':still,'live':live,'recorded':video_record,**detail,'jsErrors':errors},ensure_ascii=False))
 assert detail['photoBytes']>2000 and detail['videoBytes']>1000 and detail['cinematicBytes']>1000
 assert not errors,errors
 b.close()
