'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../../site/demo-runtime/demo-api.js'), 'utf8');
const ref = (type, id, version=1) => ({projectId:'showcase-shapes',type,id,version});
const key = r => JSON.stringify([r.projectId,r.type,r.id,r.version]);
const h = ref('research','H5'), e = ref('experiment','E5'), c = ref('code','C1'), r = ref('run','R-LOCAL');
function fixture() {
  const records = [h,e,c,r].map(ref => ({ref,record:ref.type==='experiment'?{researchRef:h}:{title:ref.id}}));
  const base = {projectId:h.projectId,position:{researchRef:h,experimentRef:e},notice:'仅依据已登记记录'};
  return {schemaVersion:1,mode:'offline-fictional-readonly',home:{projects:[{id:h.projectId,demo:true}],projectId:null,records:[],references:[]},snapshots:{[h.projectId]:{projectId:h.projectId,revision:1,records}},records:Object.fromEntries(records.map(x=>[key(x.ref),x])),mutationNames:['rws_research_save','rws_overview_apply'],contexts:{[JSON.stringify([h.projectId,key(h),key(e)])]:{base,variants:{'[]':{objectIndexes:[0],objectCount:1,objectsTruncated:false},[JSON.stringify([key(c),key(r)])]:{objectIndexes:[0,1,2],objectCount:3,objectsTruncated:false}}}},contextObjects:[{ref:h},{ref:c},{ref:r}]};
}
function api() {
  const requests=[], events=[], db=fixture();
  const window={RP_DATA:{old:true},RWSAdapter:{project:value=>({projectId:value.projectId})},dispatchEvent:event=>events.push(event)};
  const ctx={window,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>db};}};
  vm.runInNewContext(script,ctx);
  return {L:window.RWSLive,window,requests,events,db};
}
test('static adapter fetches only one relative showcase document and clones reads',async()=>{
  const {L,requests}=api();
  const first=await L.read(h.projectId);first.records.length=0;
  assert.equal((await L.read(h.projectId)).records.length,4);
  assert.equal((await L.read()).projects.length,1);
  assert.equal(requests.length,1);assert.equal(requests[0].url,'showcase.json');assert.equal(requests[0].options.credentials,'omit');
  await assert.rejects(L.read('private-project'),error=>error.code==='demo_not_found');
  await assert.rejects(L.read('__proto__'),error=>error.code==='demo_not_found');
});
test('known context selection resolves exact records and precomputed code/run variant',async()=>{
  const {L}=api();
  const response=await L.call('rws_get_context',{projectId:h.projectId,researchRef:h,experimentRef:e,selectionRefs:[c,r]});
  assert.equal(response.result.objects[1].ref.id,'C1');assert.equal(response.result.objects[2].ref.id,'R-LOCAL');
  assert.equal((await L.call('rws_get_context',{projectId:h.projectId,experimentRef:e})).result.objectCount,1);
  assert.equal((await L.call('rws_record_get',{ref:{projectId:h.projectId,type:'code',id:'C1'}})).result.ref.version,1);
  assert.equal((await L.call('rws_project_list')).result[0].demo,true);
  await assert.rejects(L.call('rws_get_context',{projectId:h.projectId,researchRef:h,experimentRef:e,selectionRefs:[r,c]}),error=>error.code==='demo_unsupported');
  await assert.rejects(L.call('rws_record_get',{ref:{...c,version:2}}),error=>error.code==='demo_not_found');
});
test('every mutation and session fails truthfully; unknown reads never return fabricated success',async()=>{
  const {L,requests}=api();
  await assert.rejects(L.mutate('anything',{private:'text'}),error=>error.code==='demo_readonly');
  await assert.rejects(L.session(),error=>error.code==='demo_readonly');
  assert.equal(requests.length,0);
  for(const name of ['rws_research_save','rws_overview_apply'])await assert.rejects(L.call(name,{}),error=>error.code==='demo_readonly');
  for(const name of ['rws_code_find','rws_result_query','unknown'])await assert.rejects(L.call(name,{}),error=>error.code==='demo_unsupported');
  assert.equal(requests.length,1);
});
test('apply keeps production projection/event contract without allowing snapshot mutation',async()=>{
  const {L,window,events}=api(), next=await L.read(h.projectId);
  L.apply(next);next.revision=100;
  assert.equal(window.RP_DATA.projectId,h.projectId);assert.equal(window.RP_DATA.old,undefined);
  assert.equal(L.getSnapshot().revision,1);assert.equal(events[0].type,'rws:data');
  const retrieved=L.getSnapshot();retrieved.revision=99;assert.equal(L.getSnapshot().revision,1);
});
test('parent navigation drives real workbench exports and reports the actual view',async()=>{
  const source=fs.readFileSync(path.join(__dirname,'../../site/demo-runtime/demo-ui.js'),'utf8');
  const listeners={}, microtasks=[], posts=[], selections=[];
  let view='research', resets=0;
  const scope={value:'',dispatchEvent:event=>selections.push(['comparison',scope.value,event.type])};
  const document={body:{dataset:{projectSurface:'workbench'}},addEventListener:()=>{},querySelectorAll:()=>[],querySelector:selector=>selector==='[data-results-field="scope"]'?scope:null};
  const window={parent:{postMessage:(message,origin)=>posts.push({message,origin})},addEventListener:(name,callback)=>listeners[name]=callback,
    RP_DATA:{projectId:h.projectId,hypotheses:[{ref:h,id:'research-key',isCurrent:true}],comparisons:[{ref:ref('comparison','CMP-SHAPES'),id:'comparison-key'}]},
    RPWorkbench:{getContext:()=>({view}),setView:next=>{view=next;listeners['rp:context-change']();},selectHypothesis:id=>selections.push(['research',id])},
    RWSResults:{reset:()=>resets++},RWSUI:{isBusy:()=>false}};
  const location={search:'?projectId=showcase-shapes',pathname:'/research-workflow-studio/demo/index.html',hash:'',origin:'https://example.test'};
  vm.runInNewContext(source,{window,document,location,URLSearchParams,queueMicrotask:callback=>microtasks.push(callback),Event:class{constructor(type){this.type=type;}}});
  const flush=()=>{while(microtasks.length)microtasks.shift()();};
  listeners['rws:data']();flush();
  assert.equal(posts[0].message.type,'rws-demo-ready');assert.equal(posts[1].message.view,'research');
  const request={source:window.parent,origin:location.origin,data:{type:'rws-demo-navigate',view:'outputs'}};
  listeners.message({...request,origin:'https://foreign.test'});flush();assert.equal(view,'research');
  listeners.message({...request,source:{}});flush();assert.equal(view,'research');
  listeners.message(request);flush();assert.equal(view,'outputs');assert.equal(resets,1);
  assert.ok(selections.some(item=>item[0]==='comparison'&&item[1]==='comparison-key'));
  assert.equal(posts.at(-1).message.view,'outputs');assert.ok(posts.every(item=>item.origin===location.origin));
  window.RPWorkbench.setView('code');flush();assert.equal(posts.at(-1).message.view,'code');
  listeners.message({...request,data:{type:'rws-demo-navigate',view:'invalid'}});flush();assert.equal(view,'code');
});
test('demo strips live write-form startup parameters before application boot',()=>{
  const source=fs.readFileSync(path.join(__dirname,'../../site/demo-runtime/demo-ui.js'),'utf8');
  for(const search of ['?projectId=showcase-shapes&stages=1&review=1&kept=test','?review=1']) {
    const changes=[];
    const location={search,pathname:'/research-workflow-studio/demo/index.html',hash:'#example'};
    vm.runInNewContext(source,{window:{addEventListener:()=>{}},document:{addEventListener:()=>{}},location,URLSearchParams,history:{replaceState:(_state,_title,url)=>changes.push(url)}});
    assert.equal(changes.length,1);
    const url=new URL(changes[0],'https://example.test');
    assert.equal(url.searchParams.has('review'),false);assert.equal(url.searchParams.has('stages'),false);
    assert.equal(url.searchParams.get('projectId'),'showcase-shapes');assert.equal(url.hash,'#example');
    if(search.includes('kept'))assert.equal(url.searchParams.get('kept'),'test');
  }
});
