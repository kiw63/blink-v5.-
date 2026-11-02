"""DOM smoke of the actual static site using in-memory module URLs.
The environment blocks HTTP navigation, so this uses about:blank.
This is NOT real hardware or production-host testing.
"""
import base64, io, json, re
from pathlib import Path
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
import shutil, os
ROOT=Path(__file__).resolve().parents[1]/'docs'
html=(ROOT/'index.html').read_text()
html=re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>','',html)
html=re.sub(r'<script[^>]*>.*?</script>','',html,flags=re.S)
html=re.sub(r'<link[^>]*rel="stylesheet"[^>]*>','',html)
logo='data:image/png;base64,'+base64.b64encode((ROOT/'assets/logo.png').read_bytes()).decode()
html=html.replace('./assets/logo.png',logo)
# Photo test input is actually decoded and processed by the application's own logic.
buf=io.BytesIO();img=Image.new('RGB',(640,360),'#1d2d72');d=ImageDraw.Draw(img)
for i in range(0,640,9): d.line((i,0,i,360),fill=(220,140,200),width=2)
img.save(buf,format='PNG')

with sync_playwright() as p:
 b=p.chromium.launch(executable_path=(shutil.which('chromium') or shutil.which('chromium-browser') or None),headless=True,args=['--no-sandbox','--disable-dev-shm-usage','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream'])
 results=[]
 for width,height in ((1280,800),(390,844)):
  page=b.new_page(viewport={'width':width,'height':height},device_scale_factor=1)
  errs=[];page.on('pageerror',lambda e:errs.append(str(e)))
  page.goto('about:blank')
  page.set_content(html)
  page.add_style_tag(content=(ROOT/'assets/style.css').read_text())
  page.add_style_tag(content=(ROOT/'assets/intro.css').read_text())
  sources={name:(ROOT/f'assets/{name}.js').read_text() for name in ('ultra4k','smart-backup','ondevice-ai','media','studio-api','intro','app')}
  sources['model']=(ROOT/'assets/tiny-restore-v1.json').read_text()
  sources['app']=sources['app'].replace("localStorage.getItem('blink_api_origin')","''").replace("localStorage.setItem('blink_api_origin',base);",'').replace('window.history.replaceState(', '(()=>{} )(')
  ret=page.evaluate('''async sources => {
   const blobUrl=s=>URL.createObjectURL(new Blob([s],{type:'text/javascript'}));
   const modules={};
   modules.ultra4k=blobUrl(sources.ultra4k);
   modules['smart-backup']=blobUrl(sources['smart-backup']);
   const model='data:application/json;base64,'+btoa(sources.model);
   sources['ondevice-ai']=sources['ondevice-ai'].replace("'./smart-backup.js'",`'${modules['smart-backup']}'`).replace("new URL('./tiny-restore-v1.json',import.meta.url)",JSON.stringify(model));
   modules['ondevice-ai']=blobUrl(sources['ondevice-ai']);
   sources.media=sources.media.replaceAll("'./ultra4k.js'",`'${modules.ultra4k}'`).replaceAll("'./smart-backup.js'",`'${modules['smart-backup']}'`).replaceAll("'./ondevice-ai.js'",`'${modules['ondevice-ai']}'`);
   for(const name of ['media','studio-api','intro'])modules[name]=blobUrl(sources[name]);
   let app=sources.app;
   for(const name of Object.keys(modules))app=app.replace(`'./${name}.js'`,`'${modules[name]}'`);
   window.BLINK_PUBLIC_CONFIG={apiBase:''};
   await import(blobUrl(app));
   return {secure:window.isSecureContext, introVisible:!document.querySelector('#blink-intro').hidden};
  }''',sources)
  assert ret['introVisible']
  assert page.locator('#intro-enter').is_visible()
  assert page.locator('.intro-logo').is_visible()
  assert page.locator('.intro-welcome').inner_text().split()==['Selamat','Datang']
  page.wait_for_timeout(4600)
  page.screenshot(path=str(ROOT.parent/f'qa/BLINK-entrance-{width}.png'))
  page.locator('#intro-enter').click()
  page.wait_for_timeout(1000)
  assert page.locator('#blink-intro').is_hidden()
  page.locator('[data-tab="photo"]').click()
  page.locator('#photo-input').set_input_files({'name':'test-source.png','mimeType':'image/png','buffer':buf.getvalue()})
  page.locator('#photo-process').click()
  page.wait_for_function("document.querySelector('#photo-result').hidden === false",timeout=25000)
  assert page.locator('#photo-result').is_visible()
  out=page.locator('#photo-result').inner_text()
  assert '640' in out or 'PHOTO' in out.upper(),out[:350]
  page.locator('[data-tab="premium"]').click()
  assert page.locator('#panel-premium').is_visible()
  assert page.locator('a[href="https://t.me/Marvel_sh"]').count()>0
  page.screenshot(path=str(ROOT.parent/f'qa/BLINK-studio-{width}.png'))
  result={'viewport':f'{width}x{height}','intro':True,'photo_pipeline':True,'premium_panel':True,'errors':errs}
  results.append(result)
  page.close()
 print('BROWSER_SITE',json.dumps(results,ensure_ascii=False))
 assert all(not x['errors'] for x in results)
 b.close()
