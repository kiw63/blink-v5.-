/* BLINK local Smart Backup. Stores processed files on the user's device; no uploads.
 * This is persistence/recovery, NOT extra GPU power or a cloud backup service.
 */
const DATABASE = 'blink-ondevice-media-v1';
const STORE = 'outputs';
const LIMIT_MS = 7 * 24 * 60 * 60 * 1000;
let pending;
export function backupAvailable(){return typeof indexedDB !== 'undefined';}
function openDB(){
  if (!backupAvailable()) return Promise.resolve(null);
  if(!pending) pending=new Promise((resolve,reject)=>{
    const req=indexedDB.open(DATABASE,1);
    req.onupgradeneeded=()=>{const db=req.result;if(!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE,{keyPath:'key'});};
    req.onsuccess=()=>resolve(req.result);
    req.onerror=()=>reject(req.error || new Error('Gagal membuka backup lokal'));
    req.onblocked=()=>reject(new Error('Database lokal sedang dipakai oleh tab lain'));
  }).catch(e=>{pending=null;throw e;});
  return pending;
}
async function query(key,method,value){
  const db=await openDB(); if(!db)return null;
  return new Promise((resolve,reject)=>{
    let request;
    const transaction=db.transaction(STORE,method==='get'?'readonly':'readwrite');
    const store=transaction.objectStore(STORE);
    request=method==='get'?store.get(key):method==='put'?store.put(value):store.delete(key);
    request.onsuccess=()=>resolve(request.result);
    request.onerror=()=>reject(request.error||new Error('Operasi backup gagal'));
    transaction.onabort=()=>reject(transaction.error || new Error('Backup dibatalkan'));
  });
}
// Hash all source bytes to avoid recovering a result for the wrong photo.
export async function sourceKey(blob,mode,target){
  if(!crypto?.subtle) return null;
  const digest=await crypto.subtle.digest('SHA-256',await blob.arrayBuffer());
  const hash=Array.from(new Uint8Array(digest),c=>c.toString(16).padStart(2,'0')).join('');
  return `v1:${mode}:${target}:${hash}`;
}
export async function loadBackup(key){
  if(!key)return null;
  try{
    const value=await query(key,'get');
    if(!value)return null;
    if(Date.now()-value.savedAt>LIMIT_MS){await query(key,'delete');return null;}
    return value.blob instanceof Blob && value.blob.size?value:null;
  }catch(e){console.warn('BLINK backup unavailable:',e.message);return null;}
}
export async function saveBackup(key,result){
  if(!key||!result?.blob?.size)return false;
  try {await query(key,'put',{key,savedAt:Date.now(),...result});return true;}
  catch(e){console.warn('BLINK storage quota or permission:',e.message);return false;}
}
export async function removeBackup(key){if(!key)return;try{await query(key,'delete');}catch{}}

/* Video chunks are staged in IndexedDB to reduce recorder-held RAM.
 * This is crash-resistant storage of intermediate chunks only; an interrupted
 * recording is not guaranteed playable without its final WebM/MP4 metadata.
 */
const VIDEO_STORE='video-chunks';
// This separate database avoids upgrading the verified image-cache database.
const VIDEO_DB='blink-video-checkpoint-v1';
let videoDBPromise;
function openVideoDB(){
  if(!backupAvailable())return Promise.resolve(null);
  if(!videoDBPromise)videoDBPromise=new Promise((resolve,reject)=>{
    const req=indexedDB.open(VIDEO_DB,1);
    req.onupgradeneeded=()=>{if(!req.result.objectStoreNames.contains(VIDEO_STORE))req.result.createObjectStore(VIDEO_STORE,{keyPath:'key'});};
    req.onsuccess=()=>resolve(req.result);
    req.onerror=()=>reject(req.error||new Error('Video checkpoint database unavailable'));
  }).catch(e=>{videoDBPromise=null;throw e;});
  return videoDBPromise;
}
export function newVideoCheckpointId(){
  const r=new Uint8Array(16);crypto.getRandomValues(r);
  return 'video-'+Array.from(r,c=>c.toString(16).padStart(2,'0')).join('');
}
async function videoRequest(method,key,value){
  const db=await openVideoDB();if(!db)throw new Error('Video backup unavailable');
  return new Promise((resolve,reject)=>{
    const tx=db.transaction(VIDEO_STORE,method==='get'?'readonly':'readwrite');
    const store=tx.objectStore(VIDEO_STORE);
    const req=method==='put'?store.put(value):method==='get'?store.get(key):store.delete(key);
    req.onsuccess=()=>resolve(req.result);
    req.onerror=()=>reject(req.error||new Error('Video checkpoint failed'));
    tx.onabort=()=>reject(tx.error||new Error('Video checkpoint aborted'));
  });
}
export async function stageVideoChunk(session,sequence,blob){
  if(!session||!Number.isInteger(sequence)||sequence<0||!blob?.size)throw new Error('Invalid video chunk');
  await videoRequest('put','',{key:`${session}:${sequence}`,session,sequence,blob});
}
export async function recoverVideoChunks(session,count){
  const parts=[];
  for(let i=0;i<count;i++){
    const row=await videoRequest('get',`${session}:${i}`);
    if(row?.blob?.size)parts.push({sequence:i,blob:row.blob});
  }
  return parts;
}
export async function cleanVideoChunks(session,count){
  try {for(let i=0;i<count;i++)await videoRequest('delete',`${session}:${i}`);}
  catch(e){console.warn('BLINK video backup cleanup:',e.message);}
}
