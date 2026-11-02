"""Test backup app logic against a deterministic IndexedDB mock in browser.
The platform's REAL IndexedDB still requires testing on a secure Android origin.
"""
import asyncio,base64,shutil
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
async def main():
  code=(ROOT/'docs/assets/smart-backup.js').read_text()
  uri='data:text/javascript;base64,'+base64.b64encode(code.encode()).decode()
  async with async_playwright() as p:
    b=await p.chromium.launch(executable_path=shutil.which('chromium') or None,headless=True,args=['--no-sandbox'])
    page=await b.new_page();await page.set_content('<html>BLINK IndexedDB mock</html>')
    result=await page.evaluate('''async (uri)=>{
      const maps=new Map();
      function mockStore(name){
        if(!maps.has(name)) maps.set(name,new Map());const records=maps.get(name);
        return {put:row=>req(()=>{records.set(row.key,row);return row.key;}),
          get:key=>req(()=>records.get(key)),delete:key=>req(()=>records.delete(key))};
      }
      function req(f){const r={};queueMicrotask(()=>{try{r.result=f();r.onsuccess?.();}catch(e){r.error=e;r.onerror?.();}});return r;}
      const dbs=new Map();
      Object.defineProperty(window,'indexedDB',{configurable:true,value:{open(name,version){
        const o={};queueMicrotask(()=>{
          let db=dbs.get(name),created=false;
          if(!db){created=true;db={objectStoreNames:{contains:key=>maps.has(name+':'+key)},
            createObjectStore:key=>mockStore(name+':'+key),
            transaction(key){return {objectStore:()=>mockStore(name+':'+key)};}};dbs.set(name,db);}
          o.result=db;if(created)o.onupgradeneeded?.();o.onsuccess?.();
        });return o;
      }}});
      const mod=await import(uri);
      const blob=new Blob(['photo-result'],{type:'image/jpeg'});
      if(!await mod.saveBackup('photo-k',{blob,width:123,height:54}))throw Error('save failed');
      const loaded=await mod.loadBackup('photo-k');
      if(!loaded||loaded.width!==123||await loaded.blob.text()!=='photo-result')throw Error('photo restore failed');
      const session=mod.newVideoCheckpointId();
      await mod.stageVideoChunk(session,0,new Blob(['AB']));
      await mod.stageVideoChunk(session,1,new Blob(['CD']));
      const chunks=await mod.recoverVideoChunks(session,2);
      if(chunks.length!==2||await chunks[0].blob.text()!=='AB'||await chunks[1].blob.text()!=='CD')throw Error('video recovery failed');
      await mod.cleanVideoChunks(session,2);await mod.removeBackup('photo-k');
      if((await mod.loadBackup('photo-k'))!==null)throw Error('photo delete failed');
      if((await mod.recoverVideoChunks(session,2)).length!==0)throw Error('video cleanup failed');
      return {photoRecovered:true,videoChunksRecovered:2,cleaned:true,backing:'mock IndexedDB'};
    }''',uri)
    print('PASS',result)
    await b.close()
if __name__=='__main__':asyncio.run(main())
