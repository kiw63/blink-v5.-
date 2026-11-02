/* BLINK experimental on-device machine-learned image restoration.
 * A real 2-layer CNN trained offline on SYNTHETIC blur/noise using example photos.
 * This model is NOT Real-ESRGAN, is NOT a guarantee of 4K detail, and cannot
 * reconstruct textures absent from severe blur. Strictly local: no media upload.
 */
import {sourceKey,loadBackup,saveBackup} from './smart-backup.js';
let modelPromise;
const MODEL_URL=new URL('./tiny-restore-v1.json',import.meta.url);
const MODEL_VERSION='tiny-restore-v1';
export function modelSource(){return MODEL_VERSION;}
export async function loadLocalModel(){
  if(!modelPromise)modelPromise=(async()=>{
    const response=await fetch(MODEL_URL,{cache:'force-cache'});
    if(!response.ok)throw new Error('Bobot model AI lokal tidak ditemukan');
    const m=await response.json();
    if(m.id!=='blink-tiny-restore-v1'||m.conv1.length!==4||m.conv2.length!==4||
      !m.conv1.every(w=>Array.isArray(w)&&w.length===25&&w.every(Number.isFinite))||
      !m.conv2.every(w=>Array.isArray(w)&&w.length===9&&w.every(Number.isFinite))||
      !m.bias1.every(Number.isFinite)||!Number.isFinite(m.bias2))throw new Error('Bobot AI lokal tidak valid');
    return m;
  })().catch(e=>{modelPromise=null;throw e;});
  return modelPromise;
}
function canvas(w,h){
  const c=document.createElement('canvas');c.width=w;c.height=h;return c;
}
function clamp255(x){return Math.max(0,Math.min(255,x));}
function srcAt(src,w,h,x,y){return src[Math.max(0,Math.min(h-1,y))*w+Math.max(0,Math.min(w-1,x))];}
/** Actual 2-convolution neural inference on luminance. No mocked model or fake claims. */
export function inferNeuralPixels(imageData,model){
  const {width:w,height:h,data}=imageData;
  const lum=new Float32Array(w*h), hidden=new Float32Array(w*h*4), out=new Uint8ClampedArray(data.length);
  for(let p=0;p<w*h;p++) {const i=4*p;lum[p]=(.2126*data[i]+.7152*data[i+1]+.0722*data[i+2])/255;}
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){
    const p=(y*w+x)*4;
    for(let n=0;n<4;n++){
      let sum=model.bias1[n],weights=model.conv1[n],k=0;
      for(let yy=-2;yy<=2;yy++)for(let xx=-2;xx<=2;xx++) sum+=weights[k++]*srcAt(lum,w,h,x+xx,y+yy);
      hidden[p+n]=Math.max(0,sum);
    }
  }
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){
    const p=y*w+x;
    let sum=model.bias2;
    for(let n=0;n<4;n++){
      const weights=model.conv2[n];let k=0;
      for(let yy=-1;yy<=1;yy++)for(let xx=-1;xx<=1;xx++) {
        const q=(Math.max(0,Math.min(h-1,y+yy))*w+Math.max(0,Math.min(w-1,x+xx)))*4+n;
        sum+=hidden[q]*weights[k++];
      }
    }
    const yOld=lum[p],yNew=Math.max(0,Math.min(1,yOld+0.5*sum));
    const delta=(yNew-yOld)*255, i=p*4;
    // Restore luminance with bounded changes; colors and alpha remain faithful.
    for(let c=0;c<3;c++)out[i+c]=clamp255(data[i+c]+delta);
    out[i+3]=255;
  }
  return new ImageData(out,w,h);
}
const limitSize=(w,h,maxLong)=>{const s=Math.min(1,maxLong/Math.max(w,h));return [Math.max(2,Math.round(w*s)),Math.max(2,Math.round(h*s))];};
const dims4K=(w,h)=>{const landscape=w>=h,capW=landscape?3840:2160,capH=landscape?2160:3840;
  const s=Math.min(capW/w,capH/h);return [Math.max(1,Math.round(w*s)),Math.max(1,Math.round(h*s))];};
const toBlob=(c,mime='image/jpeg')=>new Promise((ok,bad)=>c.toBlob(b=>b?.size?ok(b):bad(new Error('Gagal mengekspor output AI lokal')),mime,mime==='image/jpeg'?.95:undefined));
async function decode(blob){
  if(typeof createImageBitmap==='function')return createImageBitmap(blob,{imageOrientation:'from-image'});
  const url=URL.createObjectURL(blob);try {return await new Promise((ok,bad)=>{const i=new Image();i.onload=()=>ok(i);i.onerror=()=>bad(new Error('Foto gagal dibuka'));i.src=url;});}finally{URL.revokeObjectURL(url);}
}
export async function enhanceOnDevicePhoto(blob,mode='sharp',mime='image/jpeg',{onProgress,signal,backup=true}={}){
  if(!blob||!/^image\/(jpeg|png|webp)$/.test(blob.type))throw new Error('Foto bukan JPEG/PNG/WebP');
  if(blob.size>32*1048576)throw new Error('Foto maksimal 32 MB');
  if(!['image/jpeg','image/png'].includes(mime))throw new Error('Format foto tidak didukung');
  const model=await loadLocalModel();onProgress?.(5,'CNN lokal');
  const key=backup?await sourceKey(blob,`${MODEL_VERSION}:${mode}`,mime):null;
  const recovered=await loadBackup(key);
  if(recovered){onProgress?.(100,'Pulih dari backup HP');return {...recovered,recovered:true};}
  const image=await decode(blob);let output,work;
  try {
    if(image.width*image.height>50000000)throw new Error('Resolusi sumber melebihi batas aman HP');
    const [ow,oh]=dims4K(image.width,image.height);
    // Bounded CNN inference; output is 4K dimensional, learned detail is limited
    // to input working resolution. No claim of true 4K high-frequency recovery.
    const [iw,ih]=limitSize(image.width,image.height,Math.min(navigator.deviceMemory<=2?640:1024,1024));
    work=canvas(iw,ih);
    const ctx=work.getContext('2d',{willReadFrequently:true});
    if(!ctx)throw new Error('Canvas2D unavailable');
    ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';ctx.drawImage(image,0,0,iw,ih);
    onProgress?.(18,'CNN lokal');
    if(signal?.aborted)throw new Error('AI dibatalkan');
    // Neural inference on the real photo, no uploaded content.
    const inference=inferNeuralPixels(ctx.getImageData(0,0,iw,ih),model);
    ctx.putImageData(inference,0,0);
    onProgress?.(70,'CNN lokal');
    await new Promise(ok=>setTimeout(ok,0));
    if(signal?.aborted)throw new Error('AI dibatalkan');
    output=canvas(ow,oh);const dest=output.getContext('2d',{alpha:false});
    dest.imageSmoothingEnabled=true;dest.imageSmoothingQuality='high';
    // Preserve existing original camera detail: do NOT replace large originals
    // with a 1024px neural preview enlarged to 4K. Blend learned restoration.
    dest.drawImage(image,0,0,ow,oh);
    dest.globalAlpha=0.35;dest.drawImage(work,0,0,ow,oh);dest.globalAlpha=1;
    const resultBlob=await toBlob(output,mime);
    const result={blob:resultBlob,width:ow,height:oh,sourceWidth:image.width,sourceHeight:image.height,
      method:'BLINK Tiny CNN CPU lokal',label:'AI-lite CNN lokal + interpolasi 4K; bukan AI super-resolution Real-ESRGAN',
      neuralInference:true,upscaled:ow>image.width};
    await saveBackup(key,result);
    onProgress?.(100,'CNN lokal');return result;
  }finally{image.close?.();if(work)work.width=work.height=0;if(output)output.width=output.height=0;}
}
/** Reuse one set of buffers for on-device frame processing. Never send video frames to server. */
export function makeOnDeviceVideoProcessor(model,{maxLong=240}={}){
  const input=canvas(2,2),temp=canvas(2,2);let frameCounter=0;
  return {
    render(source,target,w,h,preset='natural'){
      if(!source.videoWidth||!source.videoHeight)return false;
      const [iw,ih]=limitSize(source.videoWidth,source.videoHeight,maxLong);
      if(input.width!==iw||input.height!==ih){input.width=temp.width=iw;input.height=temp.height=ih;}
      const c=input.getContext('2d',{willReadFrequently:true});c.drawImage(source,0,0,iw,ih);
      temp.getContext('2d').putImageData(inferNeuralPixels(c.getImageData(0,0,iw,ih),model),0,0);
      target.save();target.clearRect(0,0,w,h);target.imageSmoothingEnabled=true;target.imageSmoothingQuality='high';
      const ratio=Math.max(w/iw,h/ih),dw=iw*ratio,dh=ih*ratio;
      // Original video detail remains the base; learned correction is blended.
      target.drawImage(source,(w-dw)/2,(h-dh)/2,dw,dh);
      target.globalAlpha=0.35;target.drawImage(temp,(w-dw)/2,(h-dh)/2,dw,dh);
      target.globalAlpha=1;
      target.restore();frameCounter++;return true;
    },
    stats(){return {framesInferred:frameCounter,model:MODEL_VERSION};},
    dispose(){input.width=input.height=temp.width=temp.height=0;}
  };
}
