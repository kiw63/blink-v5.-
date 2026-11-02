// BLINK cinematic motion. Presentation only: does not change authentication or media processing.
const reduced=()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches;
export function showRegistrationWelcome(verificationSent){
 const layer=document.getElementById('blink-welcome');if(!layer)return;
 const msg=document.getElementById('welcome-message');
 msg.textContent=verificationSent?'Akun berhasil dibuat! Periksa email untuk verifikasi sebelum masuk.':'Akun berhasil dibuat, tetapi email verifikasi belum terkirim. Hubungi admin untuk aktivasi.';
 layer.hidden=false;document.body.classList.add('welcome-open');
 const close=document.getElementById('welcome-close');const previous=document.activeElement;
 const finish=()=>{layer.hidden=true;document.body.classList.remove('welcome-open');previous?.focus?.({preventScroll:true});};
 close.onclick=finish;close.focus({preventScroll:true});
 if(reduced)return;
 layer.classList.remove('welcome-play');void layer.offsetWidth;layer.classList.add('welcome-play');
}
export function initMotion(){
 const mascot=document.getElementById('blink-scroll-mascot');if(!mascot)return;
 let previous=window.scrollY,scheduled=false,hideTimer;
 const update=()=>{scheduled=false;const current=window.scrollY;
  if(Math.abs(current-previous)<5)return;
  const down=current>previous;previous=current;
  if(reduced()||document.body.classList.contains('intro-active')||document.body.classList.contains('welcome-open'))return;
  mascot.classList.remove('scroll-up','scroll-down','scroll-exit');
  void mascot.offsetWidth;mascot.classList.add(down?'scroll-down':'scroll-up');
  clearTimeout(hideTimer);hideTimer=setTimeout(()=>mascot.classList.add('scroll-exit'),800);
 };
 window.addEventListener('scroll',()=>{if(!scheduled){scheduled=true;requestAnimationFrame(update);}},{passive:true});
}
