import {initMotion,showRegistrationWelcome} from './motion.js';
import {videoMime,downloadBlob,readableBytes,captureStill,decodeImage,localEnhance,
  renderFrame,outputVideoSize,createRecorder} from './media.js';
import {StudioAPI} from './studio-api.js';
import {initIntro} from './intro.js';
initIntro();
initMotion();
const $=id=>document.getElementById(id);
const api=new StudioAPI();
const state={camera:null,cameraAudio:false,cameraPhoto:null,photoFile:null,photoObjectURL:null,photoOutput:null,livePhoto:null,
  cinema:null,videoFile:null,videoFileURL:null,videoOutput:null,videoOutputURL:null,recording:false,
  aiFile:null,aiJob:null,aiCapability:null,aiPolling:false,tab:'camera'};
let toastTimer;
function notify(message,error=false){const t=$('toast');t.textContent=message;t.className=`toast show${error?' error':''}`;clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.classList.remove('show'),6500);}
function fail(error){console.error(error);notify(error instanceof Error?error.message:String(error),true);}
function ensureSecure(){if(!window.isSecureContext)throw new Error('Kamera memerlukan HTTPS atau http://localhost. GitHub Pages menyediakan HTTPS.');if(!navigator.mediaDevices?.getUserMedia)throw new Error('Browser tidak menyediakan API kamera');}
function switchTab(name){if(!['camera','live','photo','video','ai','premium'].includes(name))return;
  state.tab=name;document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));
  document.querySelectorAll('[data-panel]').forEach(p=>p.classList.toggle('active',p.dataset.panel===name));
  const names={camera:'LIVE CAMERA',live:'LIVE PHOTO',photo:'PHOTO LAB',video:'VIDEO STUDIO',ai:'AI GPU STUDIO',premium:'BLINK PREMIUM'};
  $('breadcrumb-current').textContent=names[name];window.history.replaceState(null,'',location.pathname+location.search+'#'+name);
  if(name==='ai')renderAIReady();
  if(name==='premium'&&api.token)refreshOrders().catch(fail);
}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
$('jump-ai').onclick=()=>switchTab('ai');$('open-settings').onclick=()=>{switchTab('ai');$('api-url').focus();};
if(location.hash&&['camera','live','photo','video','ai','premium'].includes(location.hash.slice(1)))switchTab(location.hash.slice(1));

// CAMERA
async function startCamera(audio=false,force=false){
  ensureSecure();
  if(state.recording)throw new Error('Hentikan rekaman sebelum mengganti kamera');
  if(!force&&state.camera && state.cameraAudio===audio && state.camera.active)return state.camera;
  stopCamera();
  const height=+$('camera-quality').value;
  const videoConstraints={facingMode:{ideal:$('camera-facing').value},width:{ideal:height===2160?3840:1920},height:{ideal:height},frameRate:{ideal:30,max:30}};
  let stream;
  try{stream=await navigator.mediaDevices.getUserMedia({video:videoConstraints,audio});}
  catch(e){
    if(['NotAllowedError','SecurityError','NotFoundError'].includes(e.name))throw e;
    // Relax constraints only if the requested camera mode was not supported.
    stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:$('camera-facing').value}},audio});
  }
  state.camera=stream;state.cameraAudio=audio;
  const v=$('camera-video');v.srcObject=stream;await v.play();
  // Each visible studio has its own media element; hidden-tab videos may be throttled.
  $('live-video').srcObject=stream;$('video-camera-feed').srcObject=stream;
  $('live-video').play().catch(()=>{});$('video-camera-feed').play().catch(()=>{});
  $('live-video').hidden=false;$('live-placeholder').hidden=true;
  const track=stream.getVideoTracks()[0];const set=track.getSettings();
  $('camera-resolution').textContent=`${set.width||v.videoWidth} × ${set.height||v.videoHeight} · ${Math.round(set.frameRate||30)}FPS`;
  $('camera-state').textContent=`Aktif: ${track.label||'Kamera perangkat'}`;
  $('camera-placeholder').hidden=true;$('camera-start').textContent='↻ Mulai Ulang Kamera';
  $('camera-snap').disabled=false;$('camera-stop').disabled=false;
  track.onended=()=>{if(state.camera===stream&&!state.recording){stopCamera();notify('Kamera terputus atau izin dihentikan',true);}};
  return stream;
}
function stopCamera(){if(state.recording)return;
  if(state.camera)state.camera.getTracks().forEach(t=>t.stop());state.camera=null;state.cameraAudio=false;
  $('camera-video').srcObject=null;$('live-video').srcObject=null;$('video-camera-feed').srcObject=null;
  $('live-video').hidden=true;$('live-placeholder').hidden=false;$('camera-placeholder').hidden=false;$('camera-resolution').textContent='CAMERA OFFLINE';
  $('camera-state').textContent='Kamera belum dinyalakan';$('camera-snap').disabled=true;$('camera-stop').disabled=true;
}
$('camera-start').onclick=()=>startCamera(false).catch(fail);
$('camera-stop').onclick=stopCamera;
$('camera-facing').onchange=()=>{if(state.camera)startCamera(state.cameraAudio,true).catch(fail);};
$('camera-quality').onchange=()=>{if(state.camera)startCamera(state.cameraAudio,true).catch(fail);};
$('camera-grid-toggle').onchange=e=>$('camera-grid').hidden=!e.target.checked;
async function shutterTimer(seconds){const el=$('camera-countdown');if(!seconds)return;el.hidden=false;try{for(let i=seconds;i>0;i--){el.textContent=i;await new Promise(r=>setTimeout(r,1000));}}finally{el.hidden=true;}}
async function takeCameraPhoto(){
  const btn=$('camera-snap');btn.disabled=true;
  try{if(!state.camera)await startCamera(false);
    await shutterTimer(+$('camera-timer').value);
    const result=await captureStill($('camera-video'),$('camera-ratio').value);
    state.cameraPhoto=result;
    const file=new File([result.blob],`BLINK-camera-${Date.now()}.jpg`,{type:'image/jpeg'});
    setPhotoFile(file,true);
    $('camera-result-image').src=URL.createObjectURL(result.blob);
    $('camera-result-meta').textContent=`${result.width} × ${result.height} px · ${readableBytes(result.blob.size)} · resolusi capture nyata`;
    $('camera-result').hidden=false;notify('Foto asli berhasil ditangkap. BLINK mengecek proses Auto AI.');
    enqueueAutoAI('photo',file);
    // Automatically generate a cleaner, downloadable local fallback even when GPU is offline.
    // This is pixel finishing and may use spatial interpolation for 4K; it is never labeled AI.
    void (async()=>{
      try{
        const enhanced=await localEnhance(result.blob,'sharp','2160','image/jpeg');
        if(state.cameraPhoto?.blob!==result.blob)return; // another photo was captured
        state.cameraPhoto={blob:enhanced.blob,width:enhanced.width,height:enhanced.height};
        const previous=$('camera-result-image').src;
        $('camera-result-image').src=URL.createObjectURL(enhanced.blob);
        if(previous.startsWith('blob:'))URL.revokeObjectURL(previous);
        $('camera-result-meta').textContent=`${enhanced.width} × ${enhanced.height} px · ${readableBytes(enhanced.blob.size)} · CNN AI-lite lokal + upscale 4K`;
        notify('CNN restorasi lokal berjalan. AI-lite tidak menjamin detail asli foto sangat buram.');
      }catch(e){console.warn('Local enhancement unavailable:',e); /* original remains downloadable */}
    })();
  }catch(e){fail(e);}finally{btn.disabled=!state.camera;}
}
$('camera-snap').onclick=takeCameraPhoto;
$('camera-retake').onclick=()=>$('camera-result').hidden=true;
$('camera-download').onclick=()=>{if(state.cameraPhoto)downloadBlob(state.cameraPhoto.blob,`BLINK-camera-${Date.now()}.jpg`);};
$('camera-to-photo').onclick=()=>switchTab('photo');

// LIVE PHOTO
$('live-enable').onclick=()=>startCamera($('live-audio').checked).then(()=>notify('Kamera siap. Tekan Rekam Live Photo.')).catch(fail);
$('live-capture').onclick=async()=>{
  const btn=$('live-capture');btn.disabled=true;
  try{
    const stream=await startCamera($('live-audio').checked);
    const mime=videoMime();if(!mime)throw new Error('Browser tidak mendukung perekaman Live Photo.');
    const liveSource=$('live-video');await liveSource.play();
    const still=await captureStill(liveSource,$('camera-ratio').value);
    const {recorder,done}=createRecorder(stream);
    $('live-status').textContent='● Sedang merekam gerak 3 detik setelah shutter';
    await new Promise(r=>setTimeout(r,3100));
    if(recorder.state==='recording')recorder.stop();
    const motion=await done;
    const ext=recorder.mimeType.includes('mp4')?'mp4':'webm';
    state.livePhoto={still:still.blob,motion,ext};
    $('live-still').src=URL.createObjectURL(still.blob);
    $('live-motion').src=URL.createObjectURL(motion);
    $('live-meta').textContent=`Still ${still.width}×${still.height} px · Klip ${readableBytes(motion.size)} · video nyata setelah shutter`;
    $('live-result').hidden=false;$('live-status').textContent='✓ Live Photo siap diunduh';
    notify('Live Photo asli tersimpan. BLINK mengecek Auto AI foto dan klip gerak.');
    enqueueAutoAI('live_photo',new File([still.blob],`BLINK-live-${Date.now()}.jpg`,{type:'image/jpeg'}),new File([motion],`BLINK-live-motion.${ext}`,{type:motion.type}));
    void (async()=>{
      try{
        const enhanced=await localEnhance(still.blob,'sharp','2160','image/jpeg');
        if(state.livePhoto?.still!==still.blob)return;
        state.livePhoto.still=enhanced.blob;
        const previous=$('live-still').src;
        $('live-still').src=URL.createObjectURL(enhanced.blob);
        if(previous.startsWith('blob:'))URL.revokeObjectURL(previous);
        $('live-meta').textContent=`Still ${enhanced.width}×${enhanced.height} px (finishing lokal, bukan AI) · motion ${readableBytes(motion.size)} · pemrosesan AI klip tersedia via GPU`;
        notify('Still Live Photo otomatis dipoles. Klip asli tetap tersimpan; AI motion via GPU.');
      }catch(e){console.warn('Local Live Photo finishing unavailable:',e);}
    })();
  }catch(e){$('live-status').textContent='Live Photo gagal direkam';fail(e);}
  finally{btn.disabled=false;}
};
$('live-download-photo').onclick=()=>{if(state.livePhoto)downloadBlob(state.livePhoto.still,`BLINK-live-still-${Date.now()}.jpg`);};
$('live-download-motion').onclick=()=>{if(state.livePhoto)downloadBlob(state.livePhoto.motion,`BLINK-live-motion-${Date.now()}.${state.livePhoto.ext}`);};

// PHOTO LAB
function setPhotoFile(file,skipAuto=false){
  if(!file)return;if(!/^image\/(jpeg|png|webp)$/.test(file.type)){fail('Format foto harus JPG, PNG, atau WebP');return;}
  if(file.size>32*1048576){fail('Foto lokal maksimal 32 MB');return;}
  state.photoFile=file;if(state.photoObjectURL)URL.revokeObjectURL(state.photoObjectURL);
  state.photoObjectURL=URL.createObjectURL(file);
  $('photo-preview').src=state.photoObjectURL;$('photo-before').src=state.photoObjectURL;
  $('photo-empty').hidden=true;$('photo-view').hidden=false;$('photo-process').disabled=false;
  $('photo-result').hidden=true;$('photo-dimensions').textContent=`${readableBytes(file.size)}`;
  $('photo-status').textContent=`${file.name} · ${readableBytes(file.size)}`;
  if(!skipAuto)enqueueAutoAI('photo',file);
}
$('photo-input').onchange=e=>setPhotoFile(e.target.files[0]);
const drop=$('photo-drop');
drop.ondragover=e=>{e.preventDefault();drop.classList.add('dragging');};
drop.ondragleave=()=>drop.classList.remove('dragging');
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('dragging');setPhotoFile(e.dataTransfer?.files[0]);};
$('photo-compare-slider').oninput=e=>$('photo-compare-widget').style.setProperty('--compare',`${e.target.value}%`);
$('photo-process').onclick=async()=>{
  const btn=$('photo-process');btn.disabled=true;btn.textContent='◌ Memproses piksel asli…';
  try{
    if(!state.photoFile)throw new Error('Pilih foto dahulu');
    // yield one frame so the progress state paints before synchronous pixel loops.
    await new Promise(r=>requestAnimationFrame(()=>setTimeout(r,0)));
    const output=await localEnhance(state.photoFile,$('photo-mode').value,$('photo-output').value,$('photo-format').value);
    state.photoOutput=output;
    $('photo-after').src=URL.createObjectURL(output.blob);
    $('photo-meta').textContent=`${output.sourceWidth}×${output.sourceHeight} → ${output.width}×${output.height} · ${readableBytes(output.blob.size)} · ${output.label}`;
    $('photo-result').hidden=false;notify('Pemrosesan lokal selesai. Periksa hasil before/after.');
  }catch(e){fail(e);}finally{btn.disabled=false;btn.textContent='✦ Proses & Tingkatkan';}
};
$('photo-download').onclick=()=>{
  if(!state.photoOutput)return;
  const ext=state.photoOutput.blob.type==='image/png'?'png':'jpg';
  downloadBlob(state.photoOutput.blob,`BLINK-photo-lab-${Date.now()}.${ext}`);
};
$('photo-send-ai').onclick=()=>{
  if(!state.photoFile)return;setAIFile(state.photoFile,'photo');switchTab('ai');
};

// VIDEO STUDIO ONLY: original, adjustable non-AI color grading. Foto/Live Photo unchanged.
const canvas=$('cinema-canvas');const videoSource=$('video-source');let raf=0;
const VIDEO_CHECKS=[...document.querySelectorAll('#video-filter-choices input[data-video-filter]')];
function chosenVideoFilters(){return VIDEO_CHECKS.filter(c=>c.checked).map(c=>c.dataset.videoFilter);}
function videoStrength(){return Number($('video-filter-strength').value);}
function refreshVideoFilterPreview(){
  if(state.recording)return;
  $('video-filter-strength-value').textContent=`${videoStrength()}%`;
  if(state.videoFile&&videoSource.videoWidth&&videoSource.readyState>=2){
    renderFrame(canvas.getContext('2d'),videoSource,canvas.width,canvas.height,chosenVideoFilters(),videoStrength());
  }
}
function setVideoControlsLocked(value){
  for(const input of VIDEO_CHECKS)input.disabled=value;
  for(const id of ['video-filter-all','video-filter-none','video-filter-strength','video-resolution','video-input'])$(id).disabled=value;
}
for(const check of VIDEO_CHECKS)check.addEventListener('change',refreshVideoFilterPreview);
$('video-filter-strength').addEventListener('input',refreshVideoFilterPreview);
$('video-filter-all').onclick=()=>{if(state.recording)return;for(const c of VIDEO_CHECKS)c.checked=true;refreshVideoFilterPreview();};
$('video-filter-none').onclick=()=>{if(state.recording)return;for(const c of VIDEO_CHECKS)c.checked=false;refreshVideoFilterPreview();};
function beginDraw(video,selected,intensity,settings){
  const context=canvas.getContext('2d',{alpha:false});
  const size=outputVideoSize(video.videoWidth,video.videoHeight,settings);
  canvas.width=size.width;canvas.height=size.height;
  $('video-monitor-empty').hidden=true;
  let running=true,renderError=null;
  function draw(){if(!running)return;
    try{renderFrame(context,video,canvas.width,canvas.height,selected,intensity);}
    catch(e){renderError=e;running=false;console.error('BLINK video filter:',e);$('video-status').textContent='Filter video gagal: '+e.message;return;}
    raf=requestAnimationFrame(draw);
  }
  draw();return {stop:()=>{running=false;cancelAnimationFrame(raf);},size,assertHealthy:()=>{if(renderError)throw renderError;}};
}
function stopOldVideoURL(){if(state.videoFileURL){URL.revokeObjectURL(state.videoFileURL);state.videoFileURL=null;}}
$('video-input').onchange=async e=>{
  const file=e.target.files[0];if(!file)return;
  if(!file.type.startsWith('video/')){fail('Pilih file video');return;}
  if(file.size>160*1048576){fail('File lokal dibatasi 160MB');return;}
  if(state.recording){fail('Hentikan rekaman dahulu');return;}
  state.videoFile=file;stopOldVideoURL();state.videoFileURL=URL.createObjectURL(file);
  videoSource.src=state.videoFileURL;videoSource.load();
  try{await new Promise((resolve,reject)=>{videoSource.onloadedmetadata=resolve;videoSource.onerror=()=>reject(new Error('Video tidak dapat dibaca'));});
    if(!Number.isFinite(videoSource.duration)||videoSource.duration>65)throw new Error('Video lokal maksimal 65 detik untuk menghindari masalah memori.');
    $('video-status').textContent=`Dipilih: ${file.name} · ${Math.round(videoSource.duration)}s`;
    $('video-export-file').disabled=false;
    $('video-monitor-empty').hidden=true;
    canvas.width=videoSource.videoWidth;canvas.height=videoSource.videoHeight;
    videoSource.currentTime=Math.min(.1,Math.max(0,videoSource.duration-.1));
    videoSource.onseeked=refreshVideoFilterPreview;
    if(videoSource.readyState>=2)refreshVideoFilterPreview();
    // Explicitly NO Auto AI queue for Video Studio.
  }catch(err){$('video-export-file').disabled=true;fail(err);}
};
function finishVideo(blob,label='Color grading lokal'){
  const mime=blob.type||'video/webm';const ext=mime.includes('mp4')?'mp4':'webm';
  state.videoOutput={blob,ext};if(state.videoOutputURL)URL.revokeObjectURL(state.videoOutputURL);
  state.videoOutputURL=URL.createObjectURL(blob);$('video-result-preview').src=state.videoOutputURL;
  $('video-meta').textContent=`${canvas.width} × ${canvas.height} px · ${readableBytes(blob.size)} · ${label} (tanpa AI)`;
  $('video-result').hidden=false;notify('Video dengan filter warna selesai diekspor secara lokal.');
}
async function recordCameraVideo(){
  if(state.recording)throw new Error('Sedang merekam');
  const stream=await startCamera($('cinema-audio').checked);
  const video=$('video-camera-feed');await video.play();
  const selected=chosenVideoFilters(),intensity=videoStrength(),resolution=$('video-resolution').value;
  const draw=beginDraw(video,selected,intensity,resolution);
  const videoStream=canvas.captureStream?.(30);
  if(!videoStream){draw.stop();throw new Error('Browser tidak mendukung canvas.captureStream untuk ekspor filter.');}
  const combined=new MediaStream([...videoStream.getVideoTracks(),...stream.getAudioTracks()]);
  try{
    const rec=createRecorder(combined);
    state.cinema={...rec,draw,stream:videoStream,start:Date.now(),combined,selection:selected,resolution};state.recording=true;
    setVideoControlsLocked(true);
    $('video-record').disabled=true;$('video-stop').disabled=false;$('video-export-file').disabled=true;
    $('video-status').textContent='● Merekam video dengan color grading tanpa AI';
    const tick=()=>{if(!state.recording)return;const secs=Math.floor((Date.now()-state.cinema.start)/1000);$('video-clock').textContent=`${String(Math.floor(secs/60)).padStart(2,'0')}:${String(secs%60).padStart(2,'0')}`;if(secs>=60)stopVideoRecording();else setTimeout(tick,500);};tick();
  }catch(e){draw.stop();videoStream.getTracks().forEach(t=>t.stop());throw e;}
}
function stopVideoRecording(){
  if(!state.cinema)return;
  const active=state.cinema;state.cinema=null;state.recording=false;
  try{if(active.recorder.state==='recording')active.recorder.stop();}catch(e){fail(e);}
  active.draw.stop();
  active.done.then(blob=>{active.draw.assertHealthy();finishVideo(blob,`Rekaman filter ${active.selection.length?active.selection.join(' + '):'Natural'} · ${active.resolution==='2160'?'target 4K interpolasi':'Full HD'}`);}).catch(fail).finally(()=>{
    active.stream.getTracks().forEach(t=>t.stop());
    setVideoControlsLocked(false);
    $('video-record').disabled=false;$('video-stop').disabled=true;$('video-export-file').disabled=!state.videoFile;
    $('video-status').textContent='Rekaman kamera selesai';
  });
}
$('video-record').onclick=()=>recordCameraVideo().catch(fail);
$('video-stop').onclick=stopVideoRecording;
async function exportVideoFile(){
  if(!state.videoFile)throw new Error('Pilih video terlebih dahulu');
  if(state.recording)throw new Error('Sedang merekam');
  if(!canvas.captureStream)throw new Error('Browser tidak mendukung canvas capture. Gunakan Chrome/Edge terkini.');
  const button=$('video-export-file');button.disabled=true;$('video-record').disabled=true;
  let draw,stream,rec;
  try{
    videoSource.currentTime=0;videoSource.muted=true;
    await videoSource.play();
    const selected=chosenVideoFilters(),intensity=videoStrength(),resolution=$('video-resolution').value;
    draw=beginDraw(videoSource,selected,intensity,resolution);
    stream=canvas.captureStream(30);
    const captured=videoSource.captureStream?.()||videoSource.mozCaptureStream?.();
    const audio=captured?.getAudioTracks?.()||[];
    if(audio.length)stream=new MediaStream([...stream.getVideoTracks(),...audio]);
    rec=createRecorder(stream);
    state.recording=true;setVideoControlsLocked(true);
    $('video-status').textContent='● Mengekspor frame filter warna tanpa AI';
    const ended=new Promise((ok,reject)=>{videoSource.onended=ok;videoSource.onerror=()=>reject(new Error('Pemutaran video sumber gagal'));});
    await ended;
    if(rec.recorder.state==='recording')rec.recorder.stop();
    const result=await rec.done;
    draw.assertHealthy();
    finishVideo(result,`Filter ${selected.length?selected.join(' + '):'Natural'} · ${resolution==='2160'?'target 4K interpolasi':'Full HD'} · ${audio.length?'audio didukung':'audio tidak dijamin'}`);
    $('video-status').textContent='File video selesai diekspor';
  }catch(e){if(rec?.recorder.state==='recording')rec.recorder.stop();throw e;}
  finally{state.recording=false;draw?.stop();stream?.getTracks().forEach(t=>t.stop());videoSource.pause();
    setVideoControlsLocked(false);button.disabled=false;$('video-record').disabled=false;}
}
$('video-export-file').onclick=()=>exportVideoFile().catch(fail);
$('video-download').onclick=()=>{if(state.videoOutput)downloadBlob(state.videoOutput.blob,`BLINK-cinematic-${Date.now()}.${state.videoOutput.ext}`);};
$('video-filter-again').onclick=()=>{
  $('video-result').hidden=true;switchTab('video');
  document.getElementById('video-filter-choices').scrollIntoView({behavior:'smooth',block:'center'});
  refreshVideoFilterPreview();
};

// SERVER GPU (never a simulated AI result)
$('api-url').value=window.BLINK_PUBLIC_CONFIG?.apiBase||localStorage.getItem('blink_api_origin')||'';
function setAIFile(file,kind){
  state.aiFile=file;$('ai-kind').value=kind;$('ai-input').value='';
  $('ai-job-label').textContent=`File siap: ${file.name} · ${readableBytes(file.size)}`;
  $('ai-mode').disabled=kind==='video';$('ai-mode').value=kind==='video'?'auto':$('ai-mode').value;
  renderAIReady();
}
$('ai-input').onchange=e=>{
  const file=e.target.files[0];if(!file)return;
  const type=file.type.startsWith('image/')?'photo':file.type.startsWith('video/')?'video':null;
  if(!type){fail('Format media tidak didukung');return;}setAIFile(file,type);
};
$('ai-kind').onchange=()=>{state.aiFile=null;$('ai-input').value='';$('ai-mode').disabled=$('ai-kind').value==='video';renderAIReady();};
function renderAIReady(){
  const connected=Boolean(api.token);const service=Boolean(state.aiCapability?.services?.ai_gpu_verified);
  $('ai-process').disabled=!(connected&&service&&state.aiFile&&!state.aiPolling);
  $('balance-free').textContent=api.user?.free_tokens??'—';$('balance-premium').textContent=api.user?.premium_tokens??'—';
  $('service-capability').textContent=service?'GPU INFERENCE VERIFIED':'GPU NOT VERIFIED';
  if(!connected||!service)$('ai-job-info').textContent=!connected?'Hubungkan backend GPU dan masuk dengan akun pengguna.':'AI GPU belum lulus tes inferensi asli di server saat ini.';
  updateAutoState();
}
async function checkApi(){
  const base=api.setBase($('api-url').value);
  localStorage.setItem('blink_api_origin',base);
  $('api-status').className='api-status';$('api-status').textContent='Menghubungi backend…';
  try{
    const c=await api.capabilities();state.aiCapability=c;
    if(c.api_version<2)throw new Error('Backend terlalu lama untuk BLINK Studio');
    const available=c.services?.ai_gpu_verified;
    $('api-status').textContent=`API v${c.api_version} tersambung. AI: ${available?'GPU + model berhasil lulus inferensi asli':'GPU/model belum lulus tes inferensi'}. Batas video ${c.limits?.video_seconds||'?'} detik.`;
    $('api-status').classList.add(available?'ok':'bad');renderAIReady();
    notify('Backend berhasil dihubungkan.');drainAutoQueue();return c;
  }catch(e){state.aiCapability=null;$('api-status').classList.add('bad');$('api-status').textContent=`Koneksi gagal: ${e.message}`;renderAIReady();throw e;}
}
$('api-check').onclick=()=>checkApi().catch(fail);
$('api-login').onclick=async()=>{
  const btn=$('api-login');btn.disabled=true;
  try{
    if(!state.aiCapability)await checkApi();
    const result=await api.login($('api-email').value,$('api-password').value);
    $('api-password').value='';$('auth-fields').hidden=true;$('auth-success').hidden=false;
    $('auth-name').textContent=`${result.user.name} · sesi sementara 45 menit`;
    await refreshBalance();renderAIReady();notify('Login Studio AI berhasil.');
    updateAutoState();drainAutoQueue();
  }catch(e){fail(e);}finally{btn.disabled=false;}
};
$('show-register').onclick=()=>{const box=$('register-box');box.hidden=!box.hidden;};
$('register-submit').onclick=async()=>{
  try{
    if(!api.base)api.setBase($('api-url').value);
    const result=await api.request('/api/auth/register',{method:'POST',body:JSON.stringify({
      name:$('register-name').value,email:$('register-email').value,password:$('register-password').value
    })});
    $('register-password').value='';showRegistrationWelcome(result.verification_email_sent);notify(result.verification_email_sent?'Akun dibuat. Cek email untuk verifikasi sebelum login.':'Akun dibuat tetapi SMTP belum aktif; verifikasi email belum terkirim.');
  }catch(e){fail(e);}
};
$('request-reset').onclick=async()=>{
  const email=$('api-email').value;
  if(!email){notify('Masukkan email di kolom login untuk menerima reset password.',true);return;}
  try{
    if(!api.base)api.setBase($('api-url').value);
    const result=await api.request('/api/auth/request-reset',{method:'POST',body:JSON.stringify({email})});
    notify(result.message);
  }catch(e){fail(e);}
};
const query=new URLSearchParams(location.search);
if(query.has('verify')||query.has('reset')){
  switchTab('ai');
  if(query.has('verify')){
    const token=query.get('verify');
    $('api-status').textContent='Verifikasi email: hubungkan API yang digunakan saat pendaftaran.';
    const verifyButton=document.createElement('button');verifyButton.className='btn btn-outline';verifyButton.textContent='✓ Verifikasi Email';
    $('auth-fields').prepend(verifyButton);
    verifyButton.onclick=async()=>{
      try{if(!api.base)api.setBase($('api-url').value);
        await api.request('/api/auth/verify-email',{method:'POST',body:JSON.stringify({token})});
        notify('Email terverifikasi. Silakan login.');verifyButton.remove();
        history.replaceState(null,'',location.pathname+'#ai');
      }catch(e){fail(e);}
    };
  }else{$('reset-box').hidden=false;notify('Masukkan password baru di kotak reset password.');}
}
$('reset-submit').onclick=async()=>{
  const token=query.get('reset');if(!token){fail('Token reset tidak ditemukan');return;}
  try{if(!api.base)api.setBase($('api-url').value);
    await api.request('/api/auth/reset-password',{method:'POST',body:JSON.stringify({token,new_password:$('reset-new-password').value})});
    $('reset-new-password').value='';$('reset-box').hidden=true;notify('Password berhasil diubah. Silakan login.');
    history.replaceState(null,'',location.pathname+'#ai');
  }catch(e){fail(e);}
};
$('api-logout').onclick=async()=>{try{await api.logout();}catch(e){console.warn('Server logout error',e);}finally{observedOrders.clear();$('premium-qris').hidden=true;$('premium-qris-help').hidden=false;$('auth-fields').hidden=false;$('auth-success').hidden=true;renderAIReady();notify('Keluar Studio AI.');}};
async function refreshBalance(){try{const user=await api.me();api.user=user;renderAIReady();}catch(e){console.warn('Balance',e);}}
$('ai-process').onclick=async()=>{
  if(state.aiPolling)return;
  state.aiPolling=true;$('ai-download').hidden=true;
  try{
    if(!state.aiFile)throw new Error('Pilih file media dahulu');
    const kind=$('ai-kind').value;
    if(kind==='photo'&&!state.aiFile.type.startsWith('image/'))throw new Error('Mode foto membutuhkan image.');
    if(kind==='video'&&!state.aiFile.type.startsWith('video/'))throw new Error('Mode video membutuhkan video.');
    const max=state.aiCapability?.limits?.[kind==='photo'?'photo_mb':'video_mb'];
    if(max&&state.aiFile.size>max*1048576)throw new Error(`File maksimal ${max} MB untuk server AI`);
    $('ai-job-label').textContent='Mengunggah file ke server AI (jangan tutup halaman)…';$('ai-job-info').textContent='Biaya token hanya selesai saat pemrosesan berhasil';
    const job=await api.createJob(state.aiFile,kind,kind==='video'?'auto':$('ai-mode').value,$('ai-target').value);
    state.aiJob=job;$('ai-job-label').textContent=`Job ${job.id.slice(0,12)} · ${job.status}`;
    for(let count=0;count<240;count++){
      const current=await api.job(job.id);
      const progress=Math.max(0,Math.min(100,Number(current.progress)||0));
      $('ai-job-progress').style.width=`${progress}%`;
      $('ai-job-label').textContent=`Job ${job.id.slice(0,12)} · ${current.status} · ${progress}% (dari backend)`;
      if(current.status==='failed')throw new Error(current.error||'Server melaporkan kegagalan AI');
      if(current.status==='completed'){
        $('ai-job-info').textContent=`AI berhasil · ${current.output_width} × ${current.output_height} px · siap diunduh`;
        $('ai-download').hidden=false;await refreshBalance();notify('AI GPU selesai memproses hasil asli.');return;
      }
      await new Promise(r=>setTimeout(r,1800));
    }
    $('ai-job-info').textContent=`Job masih diproses: ${job.id}. Server tidak dibatalkan. Periksa kembali riwayat melalui aplikasi backend.`;
  }catch(e){$('ai-job-info').textContent=`Gagal: ${e.message}`;await refreshBalance();fail(e);}
  finally{state.aiPolling=false;renderAIReady();}
};
$('ai-download').onclick=async()=>{
  try{if(!state.aiJob)throw new Error('Belum ada job');
    const blob=await api.download(state.aiJob.id);
    downloadBlob(blob,`BLINK-AI-${state.aiJob.id.slice(0,8)}.${blob.type.startsWith('image/')?'png':'mp4'}`);
  }catch(e){fail(e);}
};
// SECURE STATIC PREMIUM: manual QRIS, real server orders and proofs.
let premiumOrder=null;
$('premium-order').onclick=async()=>{
  try{
    if(!api.token)throw new Error('Login di AI GPU Studio terlebih dahulu');
    const order=await api.request('/api/studio/payments/orders',{method:'POST'});
    premiumOrder=order;$('premium-qris').hidden=false;$('premium-qris-help').hidden=true;$('premium-order-info').textContent=`ORDER ${order.id} · Rp${order.amount.toLocaleString('id-ID')} · ${order.status}`;
    $('premium-send').disabled=order.status!=='created';
    await refreshOrders();notify('Order asli dibuat. Lakukan pembayaran ke QRIS NANZERA.');
  }catch(e){fail(e);}
};
async function refreshOrders(){
  if(!api.token){$('premium-qris').hidden=true;$('premium-qris-help').hidden=false;$('premium-history').textContent='Login ke AI Studio untuk melihat riwayat pembayaran.';return;}
  const orders=await api.request('/api/studio/payments/orders');
  $('premium-history').replaceChildren();
  if(!orders.length){$('premium-qris').hidden=true;$('premium-qris-help').hidden=false;$('premium-history').textContent='Belum ada riwayat pembayaran.';return;}
  for(const order of orders.slice(0,10)){
    const row=document.createElement('p');
    row.textContent=`${order.id.slice(0,8)} · Rp${Number(order.amount).toLocaleString('id-ID')} · ${order.status}${order.rejection_reason?` · ${order.rejection_reason}`:''}`;
    $('premium-history').append(row);
  }
  premiumOrder=orders.find(o=>['created','submitted'].includes(o.status))||null;
  $('premium-qris').hidden=!premiumOrder;
  $('premium-qris-help').hidden=Boolean(premiumOrder);
  $('premium-send').disabled=!premiumOrder||premiumOrder.status!=='created';
  if(premiumOrder)$('premium-order-info').textContent=`ORDER ${premiumOrder.id} · Rp${Number(premiumOrder.amount).toLocaleString('id-ID')} · ${premiumOrder.status}`;
  else if(orders.length)$('premium-order-info').textContent=`Pesanan terakhir ${orders[0].id.slice(0,8)} · ${orders[0].status}. Buat order baru untuk memperpanjang Premium.`;
  await refreshBalance();
}
$('premium-refresh').onclick=()=>refreshOrders().catch(fail);
// Near-real-time payment sync: poll authenticated order state every 4 seconds.
// The server database is authoritative; the browser never awards tokens.
const observedOrders=new Map();
let paymentPollBusy=false;
async function pollPaymentState(){
  if(paymentPollBusy||!api.token||document.visibilityState==='hidden')return;
  paymentPollBusy=true;
  try{
    const orders=await api.request('/api/studio/payments/orders');
    let changed=false;
    for(const order of orders){
      const previous=observedOrders.get(order.id);
      if(previous&&previous!==order.status){
        changed=true;
        if(order.status==='approved')notify('Pembayaran telah disetujui admin! 20 token Premium sekarang aktif.');
        else if(order.status==='rejected')notify('Pembayaran ditolak admin. Periksa riwayat pesanan.',true);
      }
      observedOrders.set(order.id,order.status);
    }
    if(changed||state.tab==='premium')await refreshOrders();
    else if(orders.length)await refreshBalance();
  }catch(e){
    if(/401|403|expired|kedaluwarsa/i.test(e.message||'')){
      // Do not keep stale credentials around after the server revokes the session.
      api.token='';api.user=null;renderAIReady();
      notify('Sesi AI telah berakhir. Silakan login kembali.',true);
    }else console.warn('Payment sync unavailable:',e.message);
  }finally{paymentPollBusy=false;}
}
setInterval(pollPaymentState,4000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollPaymentState();});

$('premium-send').onclick=async()=>{
  try{
    if(!premiumOrder||premiumOrder.status!=='created')throw new Error('Buat order baru dahulu');
    const proof=$('premium-proof').files[0];
    if(!proof||!/^image\/(jpeg|png|webp)$/.test(proof.type))throw new Error('Unggah foto bukti PNG/JPG/WebP');
    if(proof.size>16*1048576)throw new Error('Bukti maksimal 16MB');
    const body=new FormData();body.append('proof',proof,proof.name);
    const result=await api.request(`/api/studio/payments/orders/${encodeURIComponent(premiumOrder.id)}/proof`,{method:'POST',body});
    $('premium-order-info').textContent=result.message;$('premium-proof').value='';
    await refreshOrders();notify('Bukti masuk. Menunggu admin memverifikasi dana masuk.');
  }catch(e){fail(e);}
};
// AUTOMATIC HIGH-QUALITY PIPELINE: Only server-completed Real-ESRGAN jobs are AI.
const autoQueue=[];let autoBusy=false;let autoResult=null;
$('auto-ai-connect').onclick=()=>{switchTab('ai');$('api-url').focus();};
$('auto-ai-manage').onclick=()=>switchTab('ai');
$('auto-ai-enable').onchange=()=>{if(!$('auto-ai-enable').checked)autoQueue.length=0;updateAutoState();if($('auto-ai-enable').checked)drainAutoQueue();};
function updateAutoState(){
  const el=$('auto-ai-state');if(!el)return;
  if(!$('auto-ai-enable').checked){el.textContent='Auto AI dimatikan. Foto/video asli tetap dapat disimpan.';return;}
  if(!state.aiCapability?.services?.ai_gpu_verified){el.textContent='Menunggu GPU yang lulus tes inferensi Real-ESRGAN. Efek lokal bukan AI 4K.';return;}
  if(!api.token){el.textContent='Server tersedia. Login di AI Studio untuk mengaktifkan peningkatan otomatis (menggunakan token).';return;}
  el.textContent='Aktif · Foto, Live Photo dan video dikirim otomatis ke AI GPU setelah capture atau upload. Biaya 1/2/3 token.';
}
function enqueueAutoAI(kind,file,motion=null){
  if(!$('auto-ai-enable').checked||!file)return;
  if(!file.size||file.size>(kind==='video'?160:32)*1048576){notify('File terlalu besar untuk antrean Auto AI, sumber tetap dapat disimpan.',true);return;}
  // Do not silently upload private media before the user has connected and signed in.
  // A pending media file is only held in memory; an authenticated user may activate it later.
  autoQueue.push({kind,file,motion});
  if(autoQueue.length>3)autoQueue.shift();
  if(!api.token||!state.aiCapability?.services?.ai_gpu_verified){
    $('auto-ai-result').hidden=false;
    $('auto-ai-job-title').textContent='Hasil asli siap · AI belum terhubung';
    $('auto-ai-job-detail').textContent='Buka AI Studio, hubungkan server GPU dan login. Setelah itu peningkatan dimulai otomatis.';
    $('auto-ai-progress').style.width='0%';return;
  }
  drainAutoQueue();
}
async function drainAutoQueue(){
  if(autoBusy||!$('auto-ai-enable').checked||!api.token||!state.aiCapability?.services?.ai_gpu_verified)return;
  autoBusy=true;
  while(autoQueue.length&&$('auto-ai-enable').checked&&api.token){
    const task=autoQueue.shift();const panel=$('auto-ai-result');panel.hidden=false;
    $('auto-ai-download').hidden=true;$('auto-ai-download-motion').hidden=true;
    $('auto-ai-image').hidden=true;$('auto-ai-video').hidden=true;
    $('auto-ai-indicator').classList.remove('done');$('auto-ai-progress').style.width='0%';
    $('auto-ai-job-title').textContent=`Auto AI ${task.kind==='video'?'Video 4K':task.kind==='live_photo'?'Live Photo 4K':'Photo 4K'}`;
    $('auto-ai-job-detail').textContent='Memeriksa batas unggahan dan mengirim sumber asli ke server…';
    try{
      const max=state.aiCapability?.limits?.[task.kind==='video'?'video_mb':'photo_mb']||0;
      if(max&&task.file.size>max*1048576)throw new Error(`Batas unggahan server ${max} MB. Kurangi ukuran berkas.`);
      if(task.motion){
        const vmax=state.aiCapability?.limits?.video_mb||0;
        if(vmax&&task.motion.size>vmax*1048576)throw new Error(`Klip gerak melebihi ${vmax} MB`);
      }
      const mode=task.kind==='video'?'auto':'auto';
      const job=await api.createJob(task.file,task.kind,mode,'4k',task.motion);
      $('auto-ai-job-detail').textContent=`Job ${job.id.slice(0,8)} · server memproses media…`;
      let result=null;
      for(let i=0;i<300;i++){
        const current=await api.job(job.id);
        const progress=Math.max(0,Math.min(100,Number(current.progress)||0));
        $('auto-ai-progress').style.width=`${progress}%`;
        $('auto-ai-job-detail').textContent=`${current.status} · ${progress}% (progres nyata dari server)`;
        if(current.status==='failed')throw new Error(current.error||'Job AI gagal');
        if(current.status==='completed'){result=current;break;}
        await new Promise(resolve=>setTimeout(resolve,2000));
      }
      if(!result)throw new Error('Pemrosesan belum selesai. Job tetap berjalan di server; periksa riwayat Studio.');
      const blob=await api.download(job.id);
      if(!blob?.size)throw new Error('Output AI kosong');
      const ext=task.kind==='video'?'mp4':'png';
      if(autoResult?.url)URL.revokeObjectURL(autoResult.url);
      const url=URL.createObjectURL(blob);
      autoResult={blob,url,ext,job,kind:task.kind,motion:null};
      const preview=task.kind==='video'?'auto-ai-video':'auto-ai-image';
      $(preview).src=url;$(preview).hidden=false;
      $('auto-ai-job-title').textContent=`AI Selesai · ${result.output_width} × ${result.output_height} px`;
      $('auto-ai-job-detail').textContent='File benar-benar diproses server AI. Resolusi di atas adalah hasil terukur.';
      $('auto-ai-indicator').classList.add('done');$('auto-ai-download').hidden=false;
      if(task.kind==='live_photo'&&result.motion_download_url){
        const motion=await api.download(job.id,'motion');
        if(motion.size){autoResult.motion=motion;$('auto-ai-download-motion').hidden=false;}
      }
      await refreshBalance();notify('Hasil AI asli siap diunduh!');
    }catch(e){
      $('auto-ai-job-title').textContent='Peningkatan AI belum berhasil';
      $('auto-ai-job-detail').textContent=e.message||String(e);
      notify(`AI: ${e.message||e}`,true);await refreshBalance();
    }
  }
  autoBusy=false;updateAutoState();
}
$('auto-ai-download').onclick=()=>{if(autoResult?.blob)downloadBlob(autoResult.blob,`BLINK-AI-4K-${autoResult.job.id.slice(0,8)}.${autoResult.ext}`);};
$('auto-ai-download-motion').onclick=()=>{if(autoResult?.motion)downloadBlob(autoResult.motion,`BLINK-AI-Live-Motion-${autoResult.job.id.slice(0,8)}.mp4`);};
if($('api-url').value){checkApi().catch(()=>{});}else updateAutoState();

window.addEventListener('pagehide',()=>{
  stopCamera(); // browser tracks released on page exit; no private media persists
  if(state.photoObjectURL)URL.revokeObjectURL(state.photoObjectURL);
  if(state.videoFileURL)URL.revokeObjectURL(state.videoFileURL);
  if(state.videoOutputURL)URL.revokeObjectURL(state.videoOutputURL);
});
renderAIReady();
