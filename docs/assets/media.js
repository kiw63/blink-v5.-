import {newVideoCheckpointId,stageVideoChunk,recoverVideoChunks,cleanVideoChunks} from './smart-backup.js';
/* BLINK local media engine. Pixel processing and color grading are NOT AI. */
export function videoMime() {
  if (!window.MediaRecorder) return '';
  return ['video/mp4;codecs=h264,aac','video/webm;codecs=vp9,opus','video/webm;codecs=vp8,opus','video/webm']
    .find(t => MediaRecorder.isTypeSupported(t)) || '';
}
export function downloadBlob(blob, filename) {
  if (!blob || !blob.size) throw new Error('Tidak ada berkas untuk diunduh');
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');a.href=url;a.download=filename;a.rel='noopener';
  document.body.append(a);a.click();a.remove();setTimeout(() => URL.revokeObjectURL(url), 60000);
}
export function readableBytes(n) {return n>1024*1024?`${(n/1048576).toFixed(1)} MB`:`${Math.round(n/1024)} KB`;}
export function canvasBlob(canvas, mime='image/jpeg', quality=.95) {
  return new Promise((resolve,reject)=>canvas.toBlob(b=>b&&b.size?resolve(b):reject(new Error('Gagal membuat file gambar')),mime,quality));
}
export function cropSize(w,h,aspect='source') {
  if (!w||!h) throw new Error('Resolusi kamera belum tersedia');
  const ratio = aspect==='source'?w/h:(()=>{const [a,b]=aspect.split(':').map(Number);return a/b;})();
  let cw=w,ch=h;if(w/h>ratio)cw=Math.round(h*ratio);else ch=Math.round(w/ratio);
  return {sx:Math.round((w-cw)/2),sy:Math.round((h-ch)/2),sw:cw,sh:ch};
}
export async function captureStill(video, aspect='source') {
  if (!video.videoWidth||!video.videoHeight)throw new Error('Kamera belum siap. Pastikan preview terlihat.');
  const {sx,sy,sw,sh}=cropSize(video.videoWidth,video.videoHeight,aspect);
  const canvas=document.createElement('canvas');canvas.width=sw;canvas.height=sh;
  canvas.getContext('2d',{alpha:false}).drawImage(video,sx,sy,sw,sh,0,0,sw,sh);
  const blob=await canvasBlob(canvas,'image/jpeg',.97);
  return {blob,width:sw,height:sh};
}
export async function decodeImage(blob) {
  if(!blob||!blob.type.startsWith('image/'))throw new Error('Gunakan file foto JPEG, PNG, atau WebP');
  if(blob.size>32*1048576)throw new Error('Ukuran foto maksimal 32 MB untuk pemrosesan lokal');
  if(window.createImageBitmap)return await createImageBitmap(blob,{imageOrientation:'from-image'});
  const uri=URL.createObjectURL(blob);try {return await new Promise((ok,fail)=>{const im=new Image();im.onload=()=>ok(im);im.onerror=()=>fail(new Error('Gambar tidak terbaca'));im.src=uri;});}finally{URL.revokeObjectURL(uri);}
}
const PHOTO_PARAMS={
  clean:{gain:1.025,contrast:1.055,sat:1.04,gamma:1,sharp:.23,denoise:.33},
  sharp:{gain:1.018,contrast:1.075,sat:1.03,gamma:1,sharp:.60,denoise:.08},
  portrait:{gain:1.025,contrast:1.025,sat:1.00,gamma:1.01,sharp:.15,denoise:.25},
  night:{gain:1.21,contrast:1.08,sat:1.06,gamma:.89,sharp:.20,denoise:.60},
  vivid:{gain:1.035,contrast:1.1,sat:1.22,gamma:.99,sharp:.35},
  cinema:{gain:.98,contrast:1.14,sat:.90,gamma:1.00,sharp:.34}
};
export async function localEnhance(blob,mode='clean',resolution='original',mime='image/jpeg') {
  if (resolution === '2160') {
    const {enhanceOnDevicePhoto} = await import('./ondevice-ai.js');
    return enhanceOnDevicePhoto(blob, mode, mime);
  }
  const params=PHOTO_PARAMS[mode];if(!params)throw new Error('Preset tidak tersedia');
  const source=await decodeImage(blob);
  const sw=source.width,sh=source.height;
  if(sw*sh>50000000){source.close?.();throw new Error('Foto terlalu besar untuk memori browser');}
  // Preserve actual source detail instead of automatically downsampling all photos to 1900px.
  // Weak mobile devices still use a bounded working canvas to avoid out-of-memory crashes.
  const maxWork=(navigator.deviceMemory&&navigator.deviceMemory<=2)?2300:3500;const workScale=Math.min(1,maxWork/Math.max(sw,sh));
  const work=document.createElement('canvas');work.width=Math.max(1,Math.round(sw*workScale));work.height=Math.max(1,Math.round(sh*workScale));
  const ctx=work.getContext('2d',{willReadFrequently:true,alpha:false});ctx.imageSmoothingQuality='high';ctx.drawImage(source,0,0,work.width,work.height);
  source.close?.();
  const {data}=ctx.getImageData(0,0,work.width,work.height);
  const w=work.width,h=work.height;
  const base=new Uint8ClampedArray(data.length);
  for(let i=0;i<data.length;i+=4){
    let r=data[i]/255,g=data[i+1]/255,b=data[i+2]/255;
    // gamma, exposure, brightness and saturation are genuinely applied to pixels.
    r=Math.pow(Math.min(1,r*params.gain),params.gamma);g=Math.pow(Math.min(1,g*params.gain),params.gamma);b=Math.pow(Math.min(1,b*params.gain),params.gamma);
    const lum=.2126*r+.7152*g+.0722*b;
    r=(lum+(r-lum)*params.sat-.5)*params.contrast+.5;
    g=(lum+(g-lum)*params.sat-.5)*params.contrast+.5;
    b=(lum+(b-lum)*params.sat-.5)*params.contrast+.5;
    if(mode==='cinema'){r*=1.015;b*=1.055;}
    base[i]=Math.max(0,Math.min(255,r*255));base[i+1]=Math.max(0,Math.min(255,g*255));base[i+2]=Math.max(0,Math.min(255,b*255));base[i+3]=255;
  }
  // Luminance-aware cross sharpening; no false claim of AI detail reconstruction.
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){
    const p=(y*w+x)*4;
    for(let c=0;c<3;c++){
      if(!params.sharp||!x||!y||x===w-1||y===h-1){data[p+c]=base[p+c];continue;}
      const val=base[p+c];
      const neighbor=(base[p-4+c]+base[p+4+c]+base[p-w*4+c]+base[p+w*4+c])*.25;
      // Edge-aware denoise uses four-neighbour color differences; preserve strong edges.
      // Pixel output is actual local processing, not neural super-resolution.
      const contrast=Math.abs(val-neighbor);
      const smooth=contrast<24 ? (params.denoise||0)*(1-contrast/24) : 0;
      const clean=val*(1-smooth)+neighbor*smooth;
      const delta=contrast>=6?(clean-neighbor)*params.sharp:0;
      data[p+c]=Math.max(0,Math.min(255,clean+delta));
    }
    data[p+3]=255;
  }
  ctx.putImageData(new ImageData(data,w,h),0,0);
  let outW=sw,outH=sh;
  if(resolution==='2160'){
    const capLong=3840,capShort=2160;
    const landscape=sw>=sh;
    const maxW=landscape?capLong:capShort,maxH=landscape?capShort:capLong;
    const factor=Math.min(maxW/sw,maxH/sh);
    outW=Math.max(1,Math.round(sw*factor));outH=Math.max(1,Math.round(sh*factor));
  }
  if(outW*outH>16000000)throw new Error('Output terlalu besar untuk pemrosesan perangkat ini');
  const output=document.createElement('canvas');output.width=outW;output.height=outH;
  const out=output.getContext('2d',{alpha:false});out.imageSmoothingEnabled=true;out.imageSmoothingQuality='high';out.drawImage(work,0,0,outW,outH);
  const result=await canvasBlob(output,mime,.95);
  return {blob:result,width:outW,height:outH,sourceWidth:sw,sourceHeight:sh,
    label:resolution==='2160'?'4K canvas / interpolasi, bukan AI':'Pixel finishing lokal (bukan AI)'};
}
/**
 * Non-AI VIDEO-ONLY color grade. Original BLINK presets inspired by familiar
 * cinematic color moods (not copied LUTs or assets from external apps).
 * One, several, all, or zero effects. Bounded blending protects highlight detail.
 * This function must never be imported into Photo Lab or Live Photo.
 */
export const VIDEO_FILTERS=Object.freeze({
  cinematic: Object.freeze({brightness:0.98,contrast:1.18,saturate:0.91,sepia:0.08,hue:-4}),
  sunset: Object.freeze({brightness:1.04,contrast:1.11,saturate:1.22,sepia:0.20,hue:-7}),
  clearblue: Object.freeze({brightness:1.035,contrast:1.12,saturate:1.16,sepia:0,hue:7}),
  sicily: Object.freeze({brightness:1.07,contrast:1.12,saturate:1.12,sepia:0.16,hue:-4}),
  dramatic: Object.freeze({brightness:0.96,contrast:1.25,saturate:0.78,sepia:0.07,hue:-4})
});
export function resolveVideoFilter(selection=[],intensity=75) {
  // Legacy single-preset calls keep working, but new UI always supplies an array.
  const legacy={natural:[],clear:['clearblue'],film:['dramatic'],gold:['sunset'],night:['cinematic']};
  const raw=typeof selection==='string'?(legacy[selection]??[selection]):selection;
  if(!Array.isArray(raw))throw new Error('Pilihan filter video tidak valid');
  const chosen=[...new Set(raw)];
  if(chosen.some(p=>!Object.hasOwn(VIDEO_FILTERS,p)))throw new Error('Filter video tidak tersedia');
  if(!Number.isFinite(Number(intensity)))throw new Error('Intensitas filter video tidak valid');
  const amount=Math.max(0,Math.min(1,Number(intensity)/100));
  if(!chosen.length||!amount)return 'none';
  // Normalize combined strength, so "all filters" doesn't burn highlights.
  const per=amount/Math.sqrt(chosen.length);
  let exposure=0,contrast=0,sat=0,sepia=0,hue=0;
  for(const id of chosen){const f=VIDEO_FILTERS[id];
    exposure+=Math.log(f.brightness)*per;
    contrast+=Math.log(f.contrast)*per;
    sat+=Math.log(f.saturate)*per;
    sepia+=f.sepia*per;hue+=f.hue*per;
  }
  const bound=(v,min,max)=>Math.min(max,Math.max(min,v));
  return `brightness(${bound(Math.exp(exposure),0.85,1.20).toFixed(4)}) `+
    `contrast(${bound(Math.exp(contrast),0.85,1.40).toFixed(4)}) `+
    `saturate(${bound(Math.exp(sat),0.72,1.50).toFixed(4)}) `+
    `sepia(${bound(sepia,0,0.35).toFixed(4)}) `+
    `hue-rotate(${bound(hue,-20,20).toFixed(3)}deg)`;
}
export function renderFrame(ctx,video,width,height,selected=[],intensity=75){
  if(!video.videoWidth||!video.videoHeight)return false;
  const css=resolveVideoFilter(selected,intensity);
  ctx.save();
  try {
    ctx.clearRect(0,0,width,height);ctx.filter=css;
    const scale=Math.max(width/video.videoWidth,height/video.videoHeight);
    const dw=video.videoWidth*scale,dh=video.videoHeight*scale;
    ctx.drawImage(video,(width-dw)/2,(height-dh)/2,dw,dh);
    return true;
  } finally {ctx.restore();}
}
export function outputVideoSize(width,height,option='source'){
  const ratio=width/height;
  const ceiling=option==='2160'?{w:3840,h:2160}:{w:1920,h:1080};
  const bounds=width>=height?ceiling:{w:ceiling.h,h:ceiling.w};
  const scale=option==='2160'?Math.min(bounds.w/width,bounds.h/height):Math.min(1,bounds.w/width,bounds.h/height);
  const w=Math.max(2,Math.round(width*scale/2)*2),h=Math.max(2,Math.round(height*scale/2)*2);
  return {width:w,height:h,upscaled:scale>1};
}
export function createRecorder(stream){
  const mime=videoMime();if(!mime)throw new Error('Browser tidak mendukung rekaman MediaRecorder. Coba Chrome atau Edge versi terbaru.');
  const session=newVideoCheckpointId();
  const fallback=[];let count=0,staged=0,staging=Promise.resolve(),backupWorking=true;
  let resolveDone,rejectDone;
  const completion=new Promise((ok,fail)=>{resolveDone=ok;rejectDone=fail;});
  const recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:Math.min(16000000,Math.max(2500000,stream.getVideoTracks()[0]?.getSettings?.().width*4200||6000000))});
  recorder.ondataavailable=e=>{
    if(!e.data?.size)return;
    const index=count++,blob=e.data;
    staging=staging.then(async()=>{
      if(backupWorking){
        try{await stageVideoChunk(session,index,blob);staged++;return;}
        catch(err){backupWorking=false;console.warn('BLINK video backup: RAM fallback',err.message);}
      }
      fallback.push({sequence:index,blob});
    });
  };
  recorder.onerror=e=>rejectDone(new Error(e.error?.message||'Gagal merekam video'));
  recorder.onstop=async()=>{
    try {
      await staging;
      const saved=staged?await recoverVideoChunks(session,staged):[];
      const entries=saved.concat(fallback).sort((a,b)=>a.sequence-b.sequence);
      if(entries.length!==count)throw new Error('Bagian rekaman hilang dari backup lokal');
      const b=new Blob(entries.map(c=>c.blob),{type:recorder.mimeType||mime});
      if(!b.size)throw new Error('Browser tidak menghasilkan video');
      resolveDone(b);
    }catch(e){rejectDone(e);}
    finally {await cleanVideoChunks(session,count);}
  };
  recorder.start(300);
  return {recorder,done:completion,mime};
}
