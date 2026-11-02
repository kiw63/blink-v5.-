export function initIntro(){
  const intro=document.getElementById('blink-intro');
  const button=document.getElementById('intro-enter');
  if(!intro||!button)return;
  const query=new URLSearchParams(location.search);
  if(query.has('verify')||query.has('reset')){intro.hidden=true;return;}
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.body.classList.add('intro-active');
  let closed=false,scheduled=false,point={x:0,y:0};
  function pointer(e){
    if(reduced||closed)return;
    const nx=e.clientX/window.innerWidth,ny=e.clientY/window.innerHeight;
    point={x:(nx-.5)*24,y:(ny-.5)*18,px:`${(nx*100).toFixed(2)}%`,py:`${(ny*100).toFixed(2)}%`};
    if(scheduled)return;scheduled=true;
    requestAnimationFrame(()=>{
      scheduled=false;if(closed)return;
      intro.style.setProperty('--move-x',`${point.x.toFixed(2)}px`);
      intro.style.setProperty('--move-y',`${point.y.toFixed(2)}px`);
      intro.style.setProperty('--mouse-x',point.px);
      intro.style.setProperty('--mouse-y',point.py);
    });
  }
  function enter(){
    if(closed)return;closed=true;
    intro.removeEventListener('pointermove',pointer);
    document.removeEventListener('keydown',keyHandler);
    document.body.classList.remove('intro-active');
    intro.classList.add('outro');
    setTimeout(()=>{
      intro.hidden=true;intro.classList.remove('outro');
      const selected=document.querySelector('.nav-item.active');
      selected?.focus({preventScroll:true});
    },reduced?0:920);
  }
  function keyHandler(e){if(e.key==='Escape')enter();}
  if(!reduced)intro.addEventListener('pointermove',pointer,{passive:true});
  document.addEventListener('keydown',keyHandler);
  button.addEventListener('click',enter,{once:true});
}
