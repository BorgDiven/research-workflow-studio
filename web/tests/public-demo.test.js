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
function demoUI({manualContext=false, manualProject=false}={}) {
  const source=fs.readFileSync(path.join(__dirname,'../../site/demo-runtime/demo-ui.js'),'utf8');
  const listeners=new Map(), observers=new Set(), posts=[], actions=[], timers=new Set();
  const state={view:'research',hypothesisId:'other-research',focus:'ablation',busy:false,contextText:null};
  const dialogs={studio:{open:false},guide:{open:false},reader:{open:false}};
  const emit=(name,event={})=>(listeners.get(name)||[]).forEach(callback=>callback(event));
  const changed=()=>queueMicrotask(()=>[...observers].forEach(observer=>observer.callback()));
  const scope={value:'experiment',dispatchEvent:event=>{actions.push(['comparison',scope.value,event.type]);changed();}};
  const openContext=()=>{state.contextText={value:'Actual precomputed context',readOnly:false};dialogs.studio.open=true;changed();};
  const completeProject=()=>{window.RP_DATA.projectId=h.projectId;document.body.dataset.projectSurface='workbench';state.busy=false;emit('rws:data');changed();};
  const close=(name)=>({click:()=>{dialogs[name].open=false;actions.push(['close',name]);changed();}});
  const controls={
    '[data-studio="home"]':{click:()=>{document.body.dataset.projectSurface='home';emit('rws:surface-change');changed();}},
    '[data-studio="switch-project"][data-project="showcase-shapes"]':{click:()=>{state.busy=true;actions.push(['switch-project']);if(!manualProject)queueMicrotask(completeProject);}},
    '[data-studio="close-dialog"]':close('studio'), '[data-studio="close-guide"]':close('guide'), '[data-action="close-reader"]':close('reader'),
    '.header-actions [data-studio="context"]':{click:()=>{actions.push(['open-context']);if(!manualContext)queueMicrotask(openContext);}},
  };
  const document={body:{dataset:{projectSurface:'workbench'}},addEventListener:()=>{},querySelectorAll:()=>[],querySelector:selector=>{
    if(selector==='[data-results-field="scope"]')return scope;
    if(selector==='#studio-dialog')return dialogs.studio;
    if(selector==='#guidance-dialog')return dialogs.guide;
    if(selector==='#reader')return dialogs.reader;
    if(selector==='#context-text')return state.contextText;
    return controls[selector]||null;
  }};
  const window={parent:{postMessage:(message,origin)=>posts.push({message,origin})},addEventListener:(name,callback)=>listeners.set(name,[...(listeners.get(name)||[]),callback]),
    RP_DATA:{projectId:h.projectId,hypotheses:[{ref:h,id:'research-key',isCurrent:true}],comparisons:[{ref:ref('comparison','CMP-SHAPES'),id:'comparison-key'}]},
    RPWorkbench:{getContext:()=>({view:state.view,hypothesisId:state.hypothesisId}),setView:next=>{state.view=next;actions.push(['view',next]);emit('rp:context-change');},selectHypothesis:id=>{state.hypothesisId=id;actions.push(['research',id]);},overview:()=>{state.focus=null;actions.push(['overview']);}},
    RWSResults:{reset:()=>actions.push(['reset-results'])},RWSUI:{isBusy:()=>state.busy,notify:message=>actions.push(['notice',message])}};
  const location={search:'?projectId=showcase-shapes',pathname:'/research-workflow-studio/demo/index.html',hash:'',origin:'https://example.test'};
  vm.runInNewContext(source,{window,document,location,URLSearchParams,queueMicrotask,
    setTimeout:callback=>{timers.add(callback);return callback;},clearTimeout:callback=>timers.delete(callback),
    MutationObserver:class{constructor(callback){this.callback=callback;}observe(){observers.add(this);}disconnect(){observers.delete(this);}},
    Event:class{constructor(type){this.type=type;}}});
  const send=(data,extra={})=>emit('message',{source:window.parent,origin:location.origin,data,...extra});
  const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
  return {window,document,state,dialogs,scope,posts,actions,emit,send,flush,openContext,completeProject,
    ready:()=>emit('rws:data'), expire:()=>[...timers].forEach(callback=>callback()),
    replies:()=>posts.filter(item=>item.message.type.startsWith('rws-demo-tour-')).map(item=>item.message)};
}
test('parent navigation drives real workbench exports and reports the actual view',async()=>{
  const ui=demoUI();ui.ready();await ui.flush();
  assert.equal(ui.posts[0].message.type,'rws-demo-ready');assert.equal(ui.posts[1].message.view,'research');
  const request={type:'rws-demo-navigate',view:'outputs'};
  ui.send(request,{origin:'https://foreign.test'});await ui.flush();assert.equal(ui.state.view,'research');
  ui.send(request,{source:{}});await ui.flush();assert.equal(ui.state.view,'research');
  ui.send(request);await ui.flush();assert.equal(ui.state.view,'outputs');assert.equal(ui.scope.value,'comparison-key');
  assert.equal(ui.posts.at(-1).message.view,'outputs');assert.ok(ui.posts.every(item=>item.origin==='https://example.test'));
  ui.window.RPWorkbench.setView('code');await ui.flush();assert.equal(ui.posts.at(-1).message.view,'code');
  ui.send({type:'rws-demo-navigate',view:'invalid'});await ui.flush();assert.equal(ui.state.view,'code');
});
test('three trusted tours select actual research, show actual context, and select fixed comparison',async()=>{
  const ui=demoUI();ui.ready();await ui.flush();
  ui.dialogs.studio.open=ui.dialogs.guide.open=ui.dialogs.reader.open=true;
  ui.send({type:'rws-demo-tour',tour:'trace',requestId:1});await ui.flush();
  assert.equal(ui.state.view,'research');assert.equal(ui.state.hypothesisId,'research-key');assert.equal(ui.state.focus,null);
  assert.ok(Object.values(ui.dialogs).every(dialog=>!dialog.open));
  assert.equal(ui.replies().at(-1).tour,'trace');assert.equal(ui.replies().at(-1).requestId,1);
  ui.send({type:'rws-demo-tour',tour:'context',requestId:2});await ui.flush();
  assert.equal(ui.state.view,'research');assert.equal(ui.dialogs.studio.open,true);
  assert.equal(ui.state.contextText.value,'Actual precomputed context');assert.equal(ui.replies().at(-1).tour,'context');
  assert.ok(ui.actions.some(action=>action[0]==='open-context'));
  ui.send({type:'rws-demo-tour',tour:'compare',requestId:3});await ui.flush();
  assert.equal(ui.state.view,'outputs');assert.equal(ui.scope.value,'comparison-key');assert.equal(ui.dialogs.studio.open,false);
  assert.equal(ui.replies().at(-1).tour,'compare');assert.equal(ui.replies().at(-1).requestId,3);
});
test('foreign, unrelated-source and unknown tours have no effect or acknowledgement',async()=>{
  const ui=demoUI();ui.ready();await ui.flush();const before=ui.actions.length;
  ui.send({type:'rws-demo-tour',tour:'context'},{origin:'https://foreign.test'});
  ui.send({type:'rws-demo-tour',tour:'context'},{source:{}});
  ui.send({type:'rws-demo-tour',tour:'unknown'});
  await ui.flush();assert.equal(ui.actions.length,before);assert.equal(ui.replies().length,0);
});
test('latest early tour waits for data, including project selection from home',async()=>{
  const ui=demoUI();
  ui.send({type:'rws-demo-tour',tour:'trace',requestId:1});
  ui.send({type:'rws-demo-tour',tour:'compare',requestId:2});
  await ui.flush();assert.equal(ui.actions.length,0);assert.equal(ui.replies().length,0);
  ui.document.body.dataset.projectSurface='home';ui.window.RP_DATA.projectId='showcase-signals';
  ui.ready();await ui.flush();
  assert.equal(ui.state.view,'outputs');assert.equal(ui.window.RP_DATA.projectId,h.projectId);
  assert.deepEqual(ui.replies().map(reply=>reply.requestId),[2]);
});
test('rapid tour and manual navigation wait for pending context then close stale overlay',async()=>{
  const ui=demoUI({manualContext:true});ui.ready();await ui.flush();
  ui.send({type:'rws-demo-tour',tour:'context',requestId:1});await ui.flush();
  assert.ok(ui.actions.some(action=>action[0]==='open-context'));assert.equal(ui.replies().length,0);
  ui.send({type:'rws-demo-tour',tour:'trace',requestId:2});
  ui.send({type:'rws-demo-tour',tour:'compare',requestId:3});await ui.flush();
  ui.openContext();await ui.flush();
  assert.equal(ui.state.view,'outputs');assert.equal(ui.dialogs.studio.open,false);
  assert.deepEqual(ui.replies().map(reply=>reply.requestId),[3]);
  ui.send({type:'rws-demo-tour',tour:'context',requestId:4});await ui.flush();
  ui.send({type:'rws-demo-navigate',view:'code'});ui.openContext();await ui.flush();
  assert.equal(ui.state.view,'code');assert.equal(ui.dialogs.studio.open,false);
  assert.deepEqual(ui.replies().map(reply=>reply.requestId),[3]);
});
test('a tour never acknowledges context before the real dialog opens and reports failure',async()=>{
  const ui=demoUI({manualContext:true});ui.ready();await ui.flush();
  ui.send({type:'rws-demo-tour',tour:'context',requestId:8});await ui.flush();
  assert.equal(ui.replies().length,0);ui.expire();await ui.flush();
  assert.equal(ui.replies()[0].type,'rws-demo-tour-error');assert.equal(ui.replies()[0].requestId,8);
  assert.equal(ui.dialogs.studio.open,false);
});
test('repeated ready/load requests reopen one real context dialog and retain the request identity',async()=>{
  const ui=demoUI();ui.ready();await ui.flush();
  const request={type:'rws-demo-tour',tour:'context',requestId:11};
  ui.send(request);await ui.flush();ui.send(request);await ui.flush();
  assert.equal(ui.dialogs.studio.open,true);
  assert.equal(ui.actions.filter(action=>action[0]==='open-context').length,2);
  assert.equal(ui.actions.filter(action=>action[0]==='close'&&action[1]==='studio').length,1);
  assert.ok(ui.replies().every(reply=>reply.type==='rws-demo-tour-ready'&&reply.requestId===11));
});
test('rapid requests while project is loading apply only the latest final tour',async()=>{
  const ui=demoUI({manualProject:true});ui.ready();await ui.flush();
  ui.document.body.dataset.projectSurface='home';ui.window.RP_DATA.projectId='showcase-signals';
  ui.send({type:'rws-demo-tour',tour:'context',requestId:1});await ui.flush();
  ui.send({type:'rws-demo-tour',tour:'compare',requestId:2});await ui.flush();
  assert.equal(ui.replies().length,0);ui.completeProject();await ui.flush();
  assert.equal(ui.state.view,'outputs');assert.equal(ui.scope.value,'comparison-key');
  assert.deepEqual(ui.replies().map(reply=>reply.requestId),[2]);
  assert.ok(!ui.actions.some(action=>action[0]==='open-context'));
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

test('readonly demo intercepts purpose-link editing before live handlers can open a form',()=>{
  const source=fs.readFileSync(path.join(__dirname,'../../site/demo-runtime/demo-ui.js'),'utf8'),listeners=[],notices=[];
  vm.runInNewContext(source,{window:{addEventListener:()=>{},RWSUI:{notify:message=>notices.push(message)}},document:{addEventListener:(name,callback,capture)=>listeners.push({name,callback,capture})},location:{search:'?projectId=showcase-shapes'},URLSearchParams});
  const click=listeners.find(item=>item.name==='click');assert.equal(click.capture,true);
  for(const action of ['edit-research','link-implementation','add-implementation-link','remove-implementation-link']){
    let prevented=false,stopped=false;click.callback({target:{closest:selector=>selector.includes(`[data-studio="${action}"]`)?{}:null},preventDefault:()=>prevented=true,stopImmediatePropagation:()=>stopped=true});
    assert.equal(prevented,true,action);assert.equal(stopped,true,action);
  }
  assert.equal(notices.length,4);assert.ok(notices.every(message=>message.includes('只读演示')));
});
