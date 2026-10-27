/* One server authority for browser and MCP. Unsent text stays in the open form. */
(() => {
  'use strict';
  let csrf=null,snapshot=null,requestCache=new Map();
  async function fetchJSON(url,options={}){
    let response;try{response=await fetch(url,{credentials:'same-origin',cache:'no-store',...options});}catch{throw Object.assign(new Error('连接失败；内容仍保留在当前表单，尚未确认保存。'),{code:'offline'});}
    let value;try{value=await response.json();}catch{throw new Error('服务器返回了无法读取的响应。');}
    if(!response.ok||value.ok===false)throw Object.assign(new Error(value.error?.message||'请求未完成'),{code:value.error?.code||'http_error',details:value.error?.details,status:response.status});return value;
  }
  async function session(){csrf=(await fetchJSON('/api/session')).csrfToken;if(!csrf)throw new Error('无法建立人工审阅会话。');}
  async function call(name,args={},human=false){
    if(human&&!csrf)await session();
    const send=()=>fetchJSON(human?'/api/human/call':'/api/call',{method:'POST',headers:{'Content-Type':'application/json',...(human?{'X-RWS-CSRF':csrf}:{})},body:JSON.stringify({name,arguments:args})});
    try{return await send();}catch(error){
      // Session rejection happens before the business transaction. Reuse the exact
      // operation/request ID once; scientific approval and conflicts are not retried.
      if(!human||error.code!=='session_expired')throw error;
      await session();return send();
    }
  }
  async function mutate(name,args,human=false){
    const cacheKey=JSON.stringify([name,args,human]);let requestId=requestCache.get(cacheKey);if(!requestId){requestId=crypto.randomUUID();requestCache.set(cacheKey,requestId);}
    const result=await call(name,{...args,requestId},human);requestCache.delete(cacheKey);return result;
  }
  async function read(projectId){return fetchJSON('/api/state'+(projectId?'?projectId='+encodeURIComponent(projectId):''));}
  function apply(next){const previous=snapshot;snapshot=next;const data=window.RWSAdapter.project(next);Object.keys(window.RP_DATA).forEach(k=>delete window.RP_DATA[k]);Object.assign(window.RP_DATA,data);window.dispatchEvent(new CustomEvent('rws:data',{detail:{snapshot:next,previous}}));}
  window.RWSLive={read,apply,call,mutate,getSnapshot:()=>snapshot,session};
})();
