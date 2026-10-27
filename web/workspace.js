/* Fullscreen changes presentation only; research and execution selection stay intact. */
(() => {
  'use strict';
  const button=document.querySelector('#workspace-fullscreen');
  const syncWorkspace=()=>document.body.classList.toggle('has-active-workspace',!document.querySelector('#workspace').hidden);
  let immersive=false,previousScroll=0;
  function setImmersive(next){
    if(next===immersive)return;
    if(next){previousScroll=window.scrollY;window.scrollTo({top:0,behavior:'instant'});}
    immersive=next;
    document.body.classList.toggle('workspace-immersive',immersive);
    button.textContent=immersive?'退出全屏':'全屏工作区';
    button.setAttribute('aria-pressed',String(immersive));
    button.title=immersive?'Esc 退出全屏工作区':'';
    if(!immersive)window.scrollTo({top:previousScroll,behavior:'instant'});
    requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')));
  }
  button.addEventListener('click',()=>setImmersive(!immersive));
  document.addEventListener('keydown',event=>{
    if(event.key!=='Escape'||document.querySelector('dialog[open]'))return;
    if(immersive){event.preventDefault();setImmersive(false);button.focus({preventScroll:true});}
  });
  window.addEventListener('rws:surface-change',event=>{
    if(event.detail.surface!=='workbench'||!event.detail.hasWorkbench)setImmersive(false);
    syncWorkspace();
  });
  syncWorkspace();
})();
