/* BLINK Ultra 4K — genuine local, NON-AI image processing.
 * Safe to serve on GitHub Pages: no network calls, no dependencies, no uploads.
 * Tile-based WebGL2 shader with a bounded Canvas2D/CPU fallback.
 * Does NOT reconstruct irrecoverable details or promise AI-quality restoration.
 */

const SETTINGS = Object.freeze({
  clean: { sharp: 0.42, denoise: 0.32, contrast: 1.035, brightness: 1.018, sat: 1.02 },
  sharp: { sharp: 0.78, denoise: 0.20, contrast: 1.047, brightness: 1.012, sat: 1.02 },
  portrait: { sharp: 0.23, denoise: 0.40, contrast: 1.018, brightness: 1.018, sat: 0.99 },
  night: { sharp: 0.35, denoise: 0.66, contrast: 1.045, brightness: 1.14, sat: 1.03 },
  vivid: { sharp: 0.44, denoise: 0.29, contrast: 1.07, brightness: 1.025, sat: 1.13 },
  cinema: { sharp: 0.43, denoise: 0.24, contrast: 1.075, brightness: 0.99, sat: 0.92 },
});
const WIDTH_MAX = 3840;
const HEIGHT_MAX = 2160;
const PIXEL_CEILING = 3840 * 2160;

export function ultra4kDimensions(width, height) {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1)
    throw new TypeError('Invalid source dimensions');
  const landscape = width >= height;
  const capW = landscape ? WIDTH_MAX : HEIGHT_MAX;
  const capH = landscape ? HEIGHT_MAX : WIDTH_MAX;
  const ratio = Math.min(capW / width, capH / height);
  const w = Math.max(1, Math.round(width * ratio));
  const h = Math.max(1, Math.round(height * ratio));
  if (w * h > PIXEL_CEILING + 3840) throw new RangeError('4K output would exceed safe size');
  return { width: w, height: h, isUpscale: ratio > 1, multiplier: ratio };
}

const VERTEX = `#version 300 es
in vec2 aPosition;
void main(){ gl_Position=vec4(aPosition,0.,1.); }
`;
const FRAGMENT = `#version 300 es
precision highp float;
uniform sampler2D uTexture;
uniform vec2 uSourceSize;
uniform vec2 uOutputSize;
uniform vec2 uTileOffset;
uniform vec2 uTileSize;
uniform vec4 uOptions;
uniform float uSaturation;
out vec4 outColor;
vec3 sampleAt(vec2 uv){return texture(uTexture,clamp(uv,vec2(0.),vec2(1.))).rgb;}
void main(){
  vec2 uv=vec2((uTileOffset.x + gl_FragCoord.x - .5) / uOutputSize.x,
               (uTileOffset.y + uTileSize.y - gl_FragCoord.y + .5) / uOutputSize.y);
  // ImageBitmap source is uploaded with UNPACK_FLIP_Y_WEBGL=false; UV=0
  // corresponds to the first (top) source row.
  vec2 dx=1.0/uSourceSize;
  vec3 center=sampleAt(uv);
  vec3 left=sampleAt(uv-vec2(dx.x,0.));
  vec3 right=sampleAt(uv+vec2(dx.x,0.));
  vec3 up=sampleAt(uv+vec2(0.,dx.y));
  vec3 down=sampleAt(uv-vec2(0.,dx.y));
  vec3 avg=(center*4.+left+right+up+down)/8.;
  float gradient=length(center-avg);
  float flat=1.-smoothstep(.018,.11,gradient);
  // Denoise smooth regions conservatively; do not smudge boundaries.
  vec3 denoised=mix(center,avg,flat*uOptions.y);
  vec3 sharpened=denoised+(denoised-avg)*uOptions.x*smoothstep(.012,.065,gradient);
  // Constrain overshoot to keep natural leaf/skin texture and avoid halos.
  sharpened=clamp(sharpened,min(center,avg)-.07,max(center,avg)+.07);
  vec3 color=clamp((sharpened-.5)*uOptions.z+.5,0.,1.)*uOptions.w;
  float l=dot(color,vec3(.2126,.7152,.0722));
  color=clamp(mix(vec3(l),color,uSaturation),0.,1.);
  outColor=vec4(color,1.);
}`;

function compileShader(gl, kind, src) {
  const shader = gl.createShader(kind);
  gl.shaderSource(shader, src);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const msg = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`GPU shader unavailable: ${msg}`);
  }
  return shader;
}

function gpuProcessor(source, options, tileSize) {
  const tile = document.createElement('canvas');
  tile.width = tile.height = tileSize;
  const gl = tile.getContext('webgl2', { alpha: false, depth: false, antialias: false,
    preserveDrawingBuffer: true, powerPreference: 'high-performance' });
  if (!gl) throw new Error('WebGL2 tidak tersedia');
  if (Math.max(source.width, source.height) > gl.getParameter(gl.MAX_TEXTURE_SIZE))
    throw new Error('Ukuran foto melebihi batas GPU perangkat');
  const program = gl.createProgram();
  const vert = compileShader(gl, gl.VERTEX_SHADER, VERTEX);
  const frag = compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT);
  gl.attachShader(program, vert); gl.attachShader(program, frag); gl.linkProgram(program);
  gl.deleteShader(vert); gl.deleteShader(frag);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS))
    throw new Error(`GPU shader linking failed: ${gl.getProgramInfoLog(program)}`);
  gl.useProgram(program);
  const vertices = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vertices);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,1,1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(program, 'aPosition');
  gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const texture = gl.createTexture();
  gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,source);
  gl.uniform1i(gl.getUniformLocation(program,'uTexture'), 0);
  gl.uniform2f(gl.getUniformLocation(program,'uSourceSize'),source.width,source.height);
  gl.uniform4f(gl.getUniformLocation(program,'uOptions'),options.sharp, options.denoise, options.contrast, options.brightness);
  gl.uniform1f(gl.getUniformLocation(program,'uSaturation'),options.sat);
  const uOutputSize=gl.getUniformLocation(program,'uOutputSize');
  const uTileOffset=gl.getUniformLocation(program,'uTileOffset');
  const uTileSize=gl.getUniformLocation(program,'uTileSize');
  let disposed = false;
  return {
    method: 'WebGL2',
    render(x,y,w,h,target,outputWidth,outputHeight) {
      if (disposed || gl.isContextLost()) throw new Error('Konteks GPU terputus. Ulangi pemrosesan.');
      tile.width=w;tile.height=h;gl.viewport(0,0,w,h);
      gl.uniform2f(uOutputSize,outputWidth,outputHeight);
      gl.uniform2f(uTileOffset,x,y);
      gl.uniform2f(uTileSize,w,h);
      gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
      const err=gl.getError();
      if (err !== gl.NO_ERROR) throw new Error(`GPU rendering error ${err}`);
      target.drawImage(tile, x, y);
    },
    dispose() {
      if(disposed) return; disposed=true;
      gl.deleteTexture(texture);gl.deleteBuffer(vertices);gl.deleteProgram(program);
      tile.width=tile.height=0;
    }
  };
}

// Verify shader orientation and color correctness before trusting an actual GPU.
// When a mobile driver is unsupported or misbehaves we must use the CPU engine.
let cachedGPUVerified;
function gpuSelfTest() {
  if (cachedGPUVerified !== undefined) return cachedGPUVerified;
  let engine;
  try {
    const test = document.createElement('canvas');
    test.width = test.height = 32;
    const context=test.getContext('2d',{alpha:false});
    for (const [color,x,y] of [['#ff0000',0,0],['#00ff00',16,0],['#0000ff',0,16],['#ffff00',16,16]]) {
      context.fillStyle=color;context.fillRect(x,y,16,16);
    }
    engine=gpuProcessor(test,SETTINGS.clean,64);
    const target=document.createElement('canvas');target.width=target.height=64;
    const output=target.getContext('2d',{willReadFrequently:true});
    engine.render(0,0,64,64,output,64,64);
    const pixel=(x,y)=>Array.from(output.getImageData(x,y,1,1).data);
    const red=pixel(16,16), green=pixel(48,16), blue=pixel(16,48), yellow=pixel(48,48);
    cachedGPUVerified=(red[0]>160&&red[1]<100&&red[2]<100&&
      green[1]>160&&green[0]<100&&green[2]<100&&
      blue[2]>160&&blue[0]<100&&blue[1]<100&&
      yellow[0]>160&&yellow[1]>160&&yellow[2]<100);
    return cachedGPUVerified;
  } catch(e) {
    console.info('BLINK Ultra 4K: GPU self-check unavailable:',e.message);
    return (cachedGPUVerified=false);
  } finally {engine?.dispose();}
}

function cpuProcessor(source, options, tileSize) {
  const tile=document.createElement('canvas');
  const ctx=tile.getContext('2d',{alpha:false,willReadFrequently:true});
  if (!ctx) throw new Error('Canvas2D tidak tersedia');
  const halo=2;
  return {
    method:'Canvas2D CPU',
    render(x,y,w,h,target,outputWidth,outputHeight) {
      const pw=w+halo*2,ph=h+halo*2;
      tile.width=pw;tile.height=ph;
      ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';
      ctx.drawImage(source,-x+halo,-y+halo,outputWidth,outputHeight);
      const frame=ctx.getImageData(0,0,pw,ph);
      const data=frame.data;
      const processed=new ImageData(w,h);
      const dest=processed.data;
      for(let yy=0;yy<h;yy++)for(let xx=0;xx<w;xx++){
        const i=((yy+halo)*pw+(xx+halo))*4;
        const o=(yy*w+xx)*4;
        for(let c=0;c<3;c++){
          const center=data[i+c];
          const avg=(4*center+data[i-4+c]+data[i+4+c]+data[i-pw*4+c]+data[i+pw*4+c])/8;
          const grad=Math.abs(center-avg)/255;
          const flat=Math.max(0,Math.min(1,(.11-grad)/.092));
          const blend=options.denoise*flat;
          const clean=center*(1-blend)+avg*blend;
          const edge=Math.max(0,Math.min(1,(grad-.012)/.053));
          const sharp=clean+(clean-avg)*options.sharp*edge;
          const safe=Math.max(Math.min(center,avg)-18,Math.min(Math.max(center,avg)+18,sharp));
          dest[o+c]=Math.max(0,Math.min(255,((safe/255-.5)*options.contrast+.5)*options.brightness*255));
        }
        const gray=(.2126*dest[o]+.7152*dest[o+1]+.0722*dest[o+2]);
        for(let c=0;c<3;c++)dest[o+c]=Math.max(0,Math.min(255,gray+(dest[o+c]-gray)*options.sat));
        dest[o+3]=255;
      }
      // Copy only the processed core; tile margins prevent boundary seams.
      const core=document.createElement('canvas');core.width=w;core.height=h;
      core.getContext('2d',{alpha:false}).putImageData(processed,0,0);
      target.drawImage(core,x,y);
      core.width=core.height=0;
    },
    dispose(){tile.width=tile.height=0;}
  };
}

function exportCanvas(canvas,mime) {
  return new Promise((resolve,reject)=>{
    canvas.toBlob(blob => blob?.size ? resolve(blob) : reject(new Error('Gagal mengekspor foto 4K')),
      mime, mime==='image/jpeg' ? .96 : undefined);
  });
}

/**
 * Process the real source locally without uploading it anywhere.
 * onProgress is optional; it receives integer percent and processing method.
 * Respects AbortSignal between tiles, and never silently claims AI restoration.
 */
export async function enhanceUltra4K(blob, mode='sharp', mime='image/jpeg', { onProgress, signal, preferCPU=false }={}) {
  if (!blob || !String(blob.type).startsWith('image/')) throw new Error('Masukkan berkas foto yang valid');
  if (blob.size > 32*1024*1024) throw new Error('Ukuran foto maksimal 32 MB');
  const options = SETTINGS[mode];
  if (!options) throw new Error('Preset foto tidak tersedia');
  if (!['image/jpeg','image/png'].includes(mime)) throw new Error('Format ekspor harus JPEG atau PNG');
  let source;
  if (typeof createImageBitmap === 'function') {
    try {source = await createImageBitmap(blob, { imageOrientation:'from-image' });}
    catch {source=await createImageBitmap(blob);}
  }
  else {
    const url=URL.createObjectURL(blob);
    try {source=await new Promise((resolve,reject)=>{const i=new Image();i.onload=()=>resolve(i);i.onerror=()=>reject(new Error('Foto tidak bisa dibuka'));i.src=url;});}
    finally {URL.revokeObjectURL(url);}
  }
  let output,engine;
  try {
    if (source.width*source.height > 50000000) throw new Error('Resolusi sumber melebihi batas aman HP');
    const size=ultra4kDimensions(source.width,source.height);
    output=document.createElement('canvas');output.width=size.width;output.height=size.height;
    const target=output.getContext('2d',{alpha:false});
    if (!target) throw new Error('Perangkat tidak sanggup membuka canvas 4K');
    const tileSize=384; // Tile memory is <2 MB, unlike a full intermediate 4K image.
    if (!preferCPU && gpuSelfTest()) {try{engine=gpuProcessor(source,options,tileSize);}catch(e){console.info('BLINK Ultra 4K: fallback ke CPU:',e.message);}}
    if(!engine)engine=cpuProcessor(source,options,tileSize);
    const total=Math.ceil(size.width/tileSize)*Math.ceil(size.height/tileSize);
    let completed=0;
    for(let y=0;y<size.height;y+=tileSize){
      for(let x=0;x<size.width;x+=tileSize){
        if(signal?.aborted)throw new Error('Pemrosesan Ultra 4K dibatalkan');
        const w=Math.min(tileSize,size.width-x),h=Math.min(tileSize,size.height-y);
        engine.render(x,y,w,h,target,size.width,size.height);
        onProgress?.(Math.floor((++completed/total)*95),engine.method);
      }
      // Let mobile browsers render UI/touch events between tile rows.
      await new Promise(resolve=>setTimeout(resolve,0));
    }
    const result=await exportCanvas(output,mime);
    onProgress?.(100,engine.method);
    return {blob:result,width:size.width,height:size.height,
      sourceWidth:source.width,sourceHeight:source.height,
      method:engine.method,upscaled:size.isUpscale,
      label:'Ultra 4K lokal (non-AI): koreksi warna, denoise adaptif, ketajaman, interpolasi'};
  } finally {
    engine?.dispose();source?.close?.();
    if(output)output.width=output.height=0;
  }
}
