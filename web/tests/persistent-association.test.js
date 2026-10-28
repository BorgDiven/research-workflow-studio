'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),I=require('../interaction-state.js'),A=require('../live-model.js');
const source=fs.readFileSync(require.resolve('../app.js'),'utf8');
const implementation=(start,end)=>source.slice(source.indexOf('  function '+start+'('),source.indexOf('  function '+end+'('));
const plain=value=>JSON.parse(JSON.stringify(value));
function state(){return {view:'code',hypothesisId:'H2',experimentId:'E2',selectedCodeId:null,selectedSpecId:null,selectedMissingId:null,selectedExecution:null,associationHighlight:true,codeDetailTab:'overview',codeDetailHistory:[]};}
function dispatcher(globals={}){
  let click;const start=source.indexOf("  document.addEventListener('click',event=>{"),end=source.indexOf("  document.addEventListener('keydown',event=>{",start);
  vm.runInNewContext(source.slice(start,end),{document:{addEventListener(name,handler){click=handler;}},...globals});return click;
}
test('cancel/show association changes presentation only, retaining source, selected code, execution and fixed detail history',()=>{
  const s=state();I.selectCode(s,'C1',{type:'run',id:'R1'});s.codeDetailHistory=[{type:'artifact',id:'A1',scope:'report-snapshot'}];
  const before=plain(s);I.setAssociationHighlight(s,false);assert.deepEqual(s,{...before,associationHighlight:false});I.setAssociationHighlight(s,true);assert.deepEqual(s,before);
});
test('selecting another or unrelated node, repeated node click and clearing selection keep the source and association visibility',()=>{
  const s=state();I.selectCode(s,'C-related',{type:'run',id:'R1'});s.codeDetailHistory=[{type:'report',id:'RP',scope:'snapshot'}];
  I.selectCode(s,'C-unrelated',null);assert.equal(s.hypothesisId,'H2');assert.equal(s.associationHighlight,true);assert.equal(s.codeDetailHistory.length,0);
  I.selectCode(s,'C-unrelated',null,true);assert.equal(s.selectedCodeId,null);assert.equal(s.hypothesisId,'H2');assert.equal(s.associationHighlight,true);
  I.setAssociationHighlight(s,false);I.selectCode(s,'C-related',null);I.clearSelection(s);assert.equal(s.associationHighlight,false);
});
test('specification selection clears prior code, execution and fixed snapshot and double-click only deselects the specification',()=>{
  const s=state();I.selectCode(s,'C',{type:'run',id:'R'});s.codeDetailHistory=[{scope:'snapshot'}];
  I.selectDefinition(s,'spec','p:spec:S:2');assert.equal(s.selectedSpecId,'p:spec:S:2');assert.equal(s.selectedCodeId,null);assert.equal(s.selectedExecution,null);assert.deepEqual(s.codeDetailHistory,[]);
  I.selectDefinition(s,'spec','p:spec:S:2',true);assert.equal(s.selectedSpecId,null);assert.equal(s.hypothesisId,'H2');assert.equal(s.associationHighlight,true);
});
test('actual research-code navigation closes the reader, enables every association and preserves code selection without opening a reader',()=>{
  const s=state();s.associationHighlight=false;s.selectedCodeId='C';const calls=[];
  const show=vm.runInNewContext(`(()=>{${implementation('showResearchCodes','toggleAssociationHighlight')}return showResearchCodes;})()`,{state:s,I,selectH(){throw Error('Same source should remain');},closeReader:()=>calls.push('close'),setView:v=>calls.push(v),renderCode:()=>calls.push('render'),status(){},currentH:()=>({title:'Question'}),inspect(){throw Error('Must not open bottom reader');}});
  show('H2');assert.deepEqual(calls,['close','code','render']);assert.equal(s.associationHighlight,true);assert.equal(s.selectedCodeId,'C');assert.equal(s.hypothesisId,'H2');
});
test('actual cancel/show handler never closes details or changes the selected research',()=>{
  const s=state();s.selectedCodeId='C';s.codeDetailHistory=[{type:'code',id:'C'}];const before=plain(s);
  const toggle=vm.runInNewContext(`(()=>{${implementation('toggleAssociationHighlight','relationButton')}return toggleAssociationHighlight;})()`,{I,state:s,renderCode(){},status(){},emitContext(){},currentH(){return {kind:'exploration'};},A,D:{}});
  toggle();assert.deepEqual(s,{...before,associationHighlight:false});
});
test('actual click dispatch routes nested code details right, leaves external reader routing alone and clears only selection on blank canvas',()=>{
  const calls=[],s=state(),click=dispatcher({state:s,inspectCodeDetail:(...x)=>calls.push(['right',...x]),inspect:(...x)=>calls.push(['reader',...x]),clearCodeSelection:()=>{I.clearSelection(s);calls.push(['clear']);}});
  const button={dataset:{action:'inspect',type:'artifact',id:'A'},closest:q=>q==='#code-inspector'?{}:null};
  click({target:{closest:()=>button},preventDefault(){}});assert.deepEqual(calls[0],['right','artifact','A']);
  button.closest=q=>q==='#reader'?{}:null;click({target:{closest:()=>button},preventDefault(){}});assert.equal(calls[1][0],'reader');assert.equal(calls[1][4].inside,true);
  s.selectedCodeId='C';click({target:{closest:q=>q==='.code-scroll'?{}:null}});assert.equal(s.selectedCodeId,null);assert.equal(s.hypothesisId,'H2');assert.equal(s.associationHighlight,true);
});
test('actual sidebar controller preserves report scope through nested references and scope survives display toggle',()=>{
  const s=state(),body={scrollTop:81},scopes=[],controller=vm.runInNewContext(`(()=>{${implementation('inspectCodeDetail','codeInspector')}return inspectCodeDetail;})()`,{I,state:s,$:()=>body,window:{RPEvidence:{resolve:(id,scope)=>{scopes.push([id,scope]);return {ref:{type:id==='RP'?'report':'artifact'}};},scopeForReport:()=> 'fixed-RP'}},renderCode(){},closeReader(){}});
  controller('report','RP');controller('evaluation','EV');controller('artifact','A');controller('run','R');controller('code','C');
  assert.deepEqual(scopes,[['RP',null],['EV','fixed-RP'],['A','fixed-RP'],['R','fixed-RP'],['C','fixed-RP']]);assert.ok(s.codeDetailHistory.every(x=>x.scope==='fixed-RP'));
  I.setAssociationHighlight(s,false);assert.equal(s.codeDetailHistory.at(-1).scope,'fixed-RP');I.selectCode(s,'new-live-code',null);assert.deepEqual(s.codeDetailHistory,[]);
});
test('canvas definitions expose exact spec versions and unavailable refs without substituting a newer available version',()=>{
  const specs=[{id:'p:spec:S:1',kind:'analysis',purpose:'fixed spec'},{id:'p:spec:M:2',kind:'inference'}],links=[{id:'p:spec:S:1',targetRef:{type:'spec',version:1},available:true},{id:'p:spec:M:1',targetRef:{type:'spec',version:1},available:false},{id:'p:code:C:1',targetRef:{type:'code',version:1},available:true}];
  const nodes=vm.runInNewContext(`(()=>{${implementation('codeLaneNodes','associationBadge')}return codeLaneNodes;})()`,{D:{codes:[{id:'p:code:C:1',kind:'analysis'}]},codeContextLinks:links,get:(kind,id)=>specs.find(s=>s.id===id)});
  assert.deepEqual(plain(nodes('analysis')).map(x=>x.id),['p:code:C:1','p:spec:S:1']);assert.deepEqual(plain(nodes('unavailable')).map(x=>x.id),['p:spec:M:1']);assert.equal(nodes('inference').length,0);
});
test('frozen sidebar rendering cannot fall through to later live code or artifact records',()=>{
  const ref=(type,id)=>({projectId:'p',type,id,version:1}),env=(type,id,record)=>({ref:ref(type,id),record});
  const code=env('code','C',{title:'Snapshot implementation',kind:'inference',source:{description:'Frozen source'}}),run=env('run','R',{codeRef:code.ref,kind:'inference',status:'completed'}),artifact=env('artifact','A',{title:'Snapshot output',producerRef:run.ref}),evaluation=env('evaluation','EV',{inputRefs:[artifact.ref],status:'completed'}),report=env('report','RP',{title:'Report',markdown:'Frozen',evaluationRefs:[evaluation.ref],snapshot:{records:[code,run,artifact,evaluation]}});
  const live={...code,record:{...code.record,title:'Later edited source'}},D=A.project({projectId:'p',projects:[],records:[live,run,artifact,evaluation,report]}),context={window:{RP_DATA:D,RWSAdapter:A}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../evidence.js'),'utf8'),context);const R=context.window.RPEvidence,scope=R.scopeForReport(A.key(report.ref));
  assert.match(R.render('code',A.key(code.ref),{scope}),/Snapshot implementation/);assert.doesNotMatch(R.render('code',A.key(code.ref),{scope}),/Later edited source|data-action="open-research"/);assert.match(R.render('artifact',A.key(artifact.ref),{scope}),/Snapshot output/);
});

function refreshHarness(selectedMissingId,loaded=[],links=[{id:selectedMissingId}]){
  const s={...state(),hypothesisId:'H',experimentId:'E',selectedMissingId,associationHighlight:false},D={projectId:'p',hypotheses:[{id:'H',title:'Question',experimentId:'E'}],experiments:[{id:'E',hypothesisId:'H'}],codes:loaded.filter(x=>x.ref.type==='code'),specs:loaded.filter(x=>x.ref.type==='spec')},get=(kind,id)=>D[kind]?.find(x=>x.id===id);
  const start=source.indexOf('  function refreshData('),end=source.indexOf('  window.RPWorkbench=',start);
  const refresh=vm.runInNewContext(`(()=>{${source.slice(start,end)}return refreshData;})()`,{state:s,D,I,layout:{research:{},code:{}},get,contextCodeLinks:()=>links,currentH:()=>get('hypotheses',s.hypothesisId),currentItem:()=>get('hypotheses',s.hypothesisId),currentExp:()=>get('experiments',s.experimentId),window:{RWSAdapter:A},render(){},status(){},emitContext(){}});
  return {state:s,refresh:()=>refresh({detail:{previous:{projectId:'p',records:[]}}})};
}
test('actual refresh restores only the exact selected missing spec/code version when it becomes available',()=>{
  for(const type of ['spec','code']){
    const ref={projectId:'p',type,id:'S',version:1},id=A.key(ref),h=refreshHarness(id,[{id,ref}]);h.refresh();
    assert.equal(h.state.selectedMissingId,null);assert.equal(h.state[type==='spec'?'selectedSpecId':'selectedCodeId'],id);assert.equal(h.state.associationHighlight,false);assert.equal(h.state.hypothesisId,'H');
  }
});
test('actual refresh retains an unresolved fixed reference if only a newer version was loaded',()=>{
  const old={projectId:'p',type:'spec',id:'S',version:1},newer={...old,version:2},h=refreshHarness(A.key(old),[{id:A.key(newer),ref:newer}]);h.refresh();assert.equal(h.state.selectedMissingId,A.key(old));assert.equal(h.state.selectedSpecId,null);
});
test('actual refresh clears an unresolved selection when its association is removed, including stale detail history',()=>{
  const ref={projectId:'p',type:'spec',id:'S',version:1},id=A.key(ref),h=refreshHarness(id,[{id,ref}],[]);h.state.codeDetailHistory=[{type:'spec',id}];h.refresh();assert.equal(h.state.selectedMissingId,null);assert.equal(h.state.selectedSpecId,null);assert.deepEqual(h.state.codeDetailHistory,[]);assert.equal(h.state.associationHighlight,false);assert.equal(h.state.hypothesisId,'H');
});
test('spec-only cards keep a visible pending-implementation status beside the version while relation labels remain present',()=>{
  const ref={projectId:'p',type:'spec',id:'S',version:1},id=A.key(ref),relation={id,targetRef:ref,title:'Method contract',available:true,facts:[{kind:'declared',role:'implementation'}]},s=state(),D={codes:[]},spec={id,kind:'inference',purpose:'A long purpose',definitionLink:relation},html=vm.runInNewContext(`(()=>{${implementation('associationBadge','configLabel')}return codeCard;})()`,{D,state:s,codeContextLinks:[relation],A,esc:A.esc});
  assert.match(html(spec),/class="definition-state pending-implementation">待实现<\/span>/);assert.match(html(spec),/计划用途/);
  // A newer specification binding is not an implementation of this exact version.
  D.codes=[{specId:A.key({...ref,version:2})}];assert.match(html(spec),/definition-state pending-implementation">待实现/);
  D.codes=[{specId:id}];assert.doesNotMatch(html(spec),/>待实现<\/span>/);assert.match(html(spec),/definition-state has-implementation">已登记 1 版实现/);
});
