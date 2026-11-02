"""BLINK Video Studio only: real Chromium color grading, UI, recording and 4K encode.
No AI models used in the Video Studio pipeline. Synthetic source, not a device QA.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright
import base64, json, re, shutil, subprocess, tempfile, os

ROOT=Path(__file__).resolve().parents[1]; STATIC=ROOT/'docs'; ASSETS=STATIC/'assets'
HTML=(STATIC/'index.html').read_text()
HTML=re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>','',HTML)
HTML=re.sub(r'<script[^>]*>.*?</script>','',HTML,flags=re.S)
HTML=re.sub(r'<link[^>]*rel="stylesheet"[^>]*>','',HTML)
HTML=HTML.replace('./assets/logo.png','data:image/png;base64,'+base64.b64encode((ASSETS/'logo.png').read_bytes()).decode())
SOURCE={n:(ASSETS/f'{n}.js').read_text() for n in ['ultra4k','smart-backup','ondevice-ai','media','studio-api','intro','app']}
SOURCE['model']=(ASSETS/'tiny-restore-v1.json').read_text()
SOURCE['app']=SOURCE['app'].replace("localStorage.getItem('blink_api_origin')","''").replace("localStorage.setItem('blink_api_origin',base);",'').replace('window.history.replaceState(', '(()=>{} )(').replace('if(!window.isSecureContext)throw new Error','if(false)throw new Error')
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=shutil.which('chromium') or None,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
    page=browser.new_page(viewport={'width':1120,'height':900})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('about:blank');page.set_content(HTML)
    page.add_style_tag(content=(ASSETS/'style.css').read_text());page.add_style_tag(content=(ASSETS/'intro.css').read_text())
    results=page.evaluate('''async sources=>{
      const seed=document.createElement('canvas');seed.width=960;seed.height=540;
      Object.defineProperty(seed,'videoWidth',{value:960});Object.defineProperty(seed,'videoHeight',{value:540});
      const ink=seed.getContext('2d');let f=0;
      window.__videoTimer=setInterval(()=>{
        ink.fillStyle='#7f9bb6';ink.fillRect(0,0,960,540);
        ink.fillStyle='#a4bbcc';ink.fillRect(0,0,960,150);
        ink.fillStyle='#417f60';ink.fillRect(0,290,960,250);
        ink.fillStyle='#929297';ink.beginPath();ink.arc(480+15*Math.sin(f++/4),270,95,0,Math.PI*2);ink.fill();
        ink.fillStyle='#e4dfd4';ink.fillRect(20+(f*7%800),390,95,50);
      },40);
      window.__fakeStream=seed.captureStream(25);
      Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:async()=>window.__fakeStream}});
      window.BLINK_PUBLIC_CONFIG={apiBase:''};
      const blobURL=s=>URL.createObjectURL(new Blob([s],{type:'text/javascript'}));
      const mods={};mods.ultra4k=blobURL(sources.ultra4k);mods['smart-backup']=blobURL(sources['smart-backup']);
      const model='data:application/json;base64,'+btoa(sources.model);
      sources['ondevice-ai']=sources['ondevice-ai'].replace("'./smart-backup.js'",`'${mods['smart-backup']}'`).replace("new URL('./tiny-restore-v1.json',import.meta.url)",JSON.stringify(model));
      mods['ondevice-ai']=blobURL(sources['ondevice-ai']);
      sources.media=sources.media.replaceAll("'./smart-backup.js'",`'${mods['smart-backup']}'`).replaceAll("'./ultra4k.js'",`'${mods.ultra4k}'`).replaceAll("'./ondevice-ai.js'",`'${mods['ondevice-ai']}'`);
      for(const n of ['media','studio-api','intro'])mods[n]=blobURL(sources[n]);
      let app=sources.app;for(const n in mods)app=app.replace(`'./${n}.js'`,`'${mods[n]}'`);
      const media=await import(mods.media);await import(blobURL(app));
      window.__blinkMedia=media;
      const source={videoWidth:960,videoHeight:540};
      const output=document.createElement('canvas');output.width=960;output.height=540;const ctx=output.getContext('2d');
      // The exact same render path used during the actual recording.
      const sample=selected=>{media.renderFrame(ctx,seed,960,540,selected,80);let img=ctx.getImageData(50,50,1,1).data;return [...img].slice(0,3);};
      await new Promise(ok=>setTimeout(ok,200));
      const original=sample([]),single=sample(['cinematic']),combo=sample(['cinematic','sunset']),all=sample(Object.keys(media.VIDEO_FILTERS));
      const empty=media.resolveVideoFilter([],80);
      const filter=media.resolveVideoFilter(Object.keys(media.VIDEO_FILTERS),100);
      const bounds=/brightness\\(([0-9.]+)\\) contrast\\(([0-9.]+)\\) saturate\\(([0-9.]+)\\) sepia\\(([0-9.]+)\\)/.exec(filter);
      return {original,single,combo,all,empty,filter,bounds:bounds?.slice(1),size4k:media.outputVideoSize(960,540,'2160'),sizeHD:media.outputVideoSize(960,540,'source')};
    }''',SOURCE)
    assert results['empty']=='none',results
    assert results['original']!=results['single'],results
    assert results['single']!=results['combo'] and results['combo']!=results['all'],results
    assert results['size4k']['width']==3840 and results['size4k']['height']==2160,results
    assert results['bounds'] and len(results['bounds'])==4,results
    assert float(results['bounds'][0])<=1.20 and float(results['bounds'][1])<=1.40 and float(results['bounds'][2])<=1.50 and float(results['bounds'][3])<=.35,results
    page.locator('#intro-enter').click()
    page.locator('[data-tab="video"]').click()
    assert page.locator('#panel-video').is_visible()
    if os.environ.get('BLINK_QA_SCREENSHOT'):
        page.locator('#panel-video').screenshot(path=os.environ['BLINK_QA_SCREENSHOT'])
    assert page.locator('#video-filter-choices input').count()==5
    assert page.locator('#panel-photo #video-filter-choices').count()==0
    assert page.locator('#panel-live #video-filter-choices').count()==0
    assert page.locator('#video-filter-choices input:checked').count()==1
    page.locator('#video-filter-all').click()
    assert page.locator('#video-filter-choices input:checked').count()==5
    page.locator('#video-filter-none').click()
    assert page.locator('#video-filter-choices input:checked').count()==0
    page.locator('[data-video-filter="sunset"]').check()
    page.locator('[data-video-filter="clearblue"]').check()
    assert page.locator('#video-filter-choices input:checked').count()==2
    page.locator('#video-filter-strength').fill('85')
    assert page.locator('#video-filter-strength-value').inner_text()=='85%'
    page.locator('#video-filter-all').click()
    page.locator('#video-resolution').select_option('2160')
    page.locator('#video-record').click()
    page.wait_for_function('document.querySelector("#video-stop").disabled===false',timeout=20000)
    assert page.locator('[data-video-filter="cinematic"]').is_disabled()
    page.wait_for_timeout(2100)
    page.locator('#video-stop').click()
    page.wait_for_function('document.querySelector("#video-result").hidden===false',timeout=30000)
    meta=page.locator('#video-meta').inner_text()
    assert '3840 × 2160' in meta and '(tanpa AI)' in meta,meta
    encoded=page.evaluate('''async()=>{
      const el=document.getElementById('video-result-preview');const blob=await (await fetch(el.src)).blob();
      const bytes=new Uint8Array(await blob.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i++)binary+=String.fromCharCode(bytes[i]);
      clearInterval(window.__videoTimer);window.__fakeStream.getTracks().forEach(t=>t.stop());
      return {type:blob.type,size:blob.size,base64:btoa(binary)};
    }''')
    assert encoded['size']>2500,encoded
    with tempfile.TemporaryDirectory() as t:
        outfile=Path(t)/'blink-video-filter-4k.webm';outfile.write_bytes(base64.b64decode(encoded['base64']))
        probed=json.loads(subprocess.check_output(['ffprobe','-v','quiet','-print_format','json','-show_streams',str(outfile)]))
        track=next(v for v in probed['streams'] if v['codec_type']=='video')
        assert track['width']==3840 and track['height']==2160,track
    # Upload real WebM clip, preview preset, export its actual filtered pixels.
    with tempfile.TemporaryDirectory() as t:
        source_file=Path(t)/'source.webm'
        subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=480x270:rate=24',
                        '-t','2.5','-c:v','libvpx','-b:v','350k',str(source_file)],check=True)
        page.locator('#video-resolution').select_option('source')
        page.locator('#video-filter-none').click()
        page.locator('[data-video-filter="sunset"]').check()
        page.locator('[data-video-filter="clearblue"]').check()
        page.locator('#video-input').set_input_files(str(source_file))
        page.wait_for_function('document.querySelector("#video-export-file").disabled===false',timeout=15000)
        page.evaluate('document.querySelector("#video-result").hidden=true')
        page.locator('#video-export-file').click()
        page.wait_for_function('document.querySelector("#video-result").hidden===false && document.querySelector("#video-meta").textContent.includes("sunset + clearblue")',timeout=20000)
        upload_meta=page.locator('#video-meta').inner_text()
        assert '480 × 270' in upload_meta and '(tanpa AI)' in upload_meta,upload_meta
        upload_bytes=page.evaluate('''async()=>{let b=await(await fetch(document.querySelector('#video-result-preview').src)).blob();return {size:b.size,type:b.type};}''')
        assert upload_bytes['size']>2500,upload_bytes
        print('UPLOADED_VIDEO_FILTER_QA_PASS',upload_meta,upload_bytes)
    assert not errors,errors
    assert 'enqueueAutoAI(\'video\'' not in SOURCE['app']
    assert 'loadLocalModel' not in SOURCE['app']
    print('VIDEO_FILTER_QA_PASS',json.dumps({k:v for k,v in results.items() if k!='filter'},ensure_ascii=False),'recordedBytes',encoded['size'],'meta',meta)
    print('Video filters remain scoped to Video Studio. Video Studio uses no CNN/AI imports or uploads.')
    browser.close()
