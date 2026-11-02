export class StudioAPI{
  constructor(){this.base='';this.token='';this.user=null;}
  setBase(value){
    const u=new URL(value.trim());
    if(u.username||u.password||u.search||u.hash||u.pathname!=='/'&&u.pathname!=='')throw new Error('Masukkan origin API saja tanpa path, query atau kredensial');
    if(u.protocol!=='https:'&&!(u.protocol==='http:'&&['localhost','127.0.0.1'].includes(u.hostname)))throw new Error('API publik wajib memakai HTTPS');
    this.base=u.origin;return this.base;
  }
  async request(path,options={}){
    if(!this.base)throw new Error('Masukkan alamat API dahulu');
    const headers=new Headers(options.headers||{});
    if(this.token)headers.set('Authorization',`Bearer ${this.token}`);
    if(options.body&&!(options.body instanceof FormData))headers.set('Content-Type','application/json');
    const res=await fetch(this.base+path,{...options,headers,mode:'cors',credentials:'omit',cache:'no-store',signal:options.signal||AbortSignal.timeout(30000)});
    if(!res.ok){const data=await res.json().catch(()=>({detail:`HTTP ${res.status}`}));throw new Error(typeof data.detail==='string'?data.detail:`HTTP ${res.status}`);}
    if(res.status===204)return null;
    return await res.json();
  }
  async capabilities(){return this.request('/api/public/capabilities');}
  async login(email,password){
    const data=await this.request('/api/studio/login',{method:'POST',body:JSON.stringify({email,password})});
    if(!data.access_token)throw new Error('Login gagal: tidak ada token');
    this.token=data.access_token;this.user=data.user;return data;
  }
  async logout(){
    try{if(this.token)await this.request('/api/studio/logout',{method:'POST'});}
    finally{this.token='';this.user=null;}
  }
  async me(){return this.request('/api/studio/me');}
  async createJob(file,kind,mode,target='auto',motion){
    if(!this.token)throw new Error('Masuk ke akun pengguna Studio dahulu');
    const body=new FormData();body.append('file',file,file.name||`blink.${kind==='photo'?'png':'webm'}`);body.append('kind',kind);body.append('mode',mode);body.append('target',target);
    if(motion)body.append('motion',motion,motion.name||'motion.webm');
    return this.request('/api/studio/jobs',{method:'POST',body,signal:AbortSignal.timeout(120000)});
  }
  async job(id){return this.request(`/api/studio/jobs/${encodeURIComponent(id)}`);}
  async download(id,part='output'){
    if(!this.token)throw new Error('Login Studio dibutuhkan');
    const res=await fetch(`${this.base}/api/studio/jobs/${encodeURIComponent(id)}/download?part=${part}`,{
      headers:{Authorization:`Bearer ${this.token}`},mode:'cors',credentials:'omit',cache:'no-store',signal:AbortSignal.timeout(120000)});
    if(!res.ok)throw new Error(`Unduhan gagal: HTTP ${res.status}`);
    return res.blob();
  }
}
