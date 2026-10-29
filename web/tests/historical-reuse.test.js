'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),A=require('../live-model.js'),I=require('../interaction-state.js');
const source=fs.readFileSync(require.resolve('../app.js'),'utf8'),slice=(start,end)=>source.slice(source.indexOf('  function '+start+'('),source.indexOf('  function '+end+'('));
const ref=(type,id,version=1,projectId='new')=>({projectId,type,id,version}),env=(type,id,record,version=1,projectId='new')=>({ref:ref(type,id,version,projectId),record});
function fixture(){
  const oldCode=env('code','legacy',{title:'Original method',kind:'inference',version:'old',source:{}},1,'old'),oldRun=env('run','original-run',{title:'Original run',kind:'inference',status:'completed',codeRef:oldCode.ref},1,'old'),oldArtifact=env('artifact','original-output',{title:'Original saved image',kind:'image',semantic:'final-image',producerRef:oldRun.ref,uri:'/saved.png'},1,'old');
  const codes=['inference','analysis','evaluation','report'].map(kind=>env('code',kind,{title:'Refactored '+kind,kind,version:'v1',specRef:ref('spec',kind),source:{historicalArtifactRefs:[oldArtifact.ref],historicalReuseNote:'Reference earlier evidence without claiming a new run.',legacyCodeRefs:[oldCode.ref]}}));
  const specs=codes.map(code=>env('spec',code.ref.id,{title:'Contract '+code.ref.id,kind:code.record.kind,status:'ready',purpose:'Reusable method',inputs:[],outputs:[]}));
  const research=env('research','question',{title:'Current question',kind:'exploration',stage:'idea',implementationLinks:codes.map(code=>({targetRef:code.ref,role:'implementation'}))});
  const snapshot={projectId:'new',projects:[{id:'new',name:'New project'},{id:'old',name:'Historical project'}],records:[research,...specs,...codes],references:[oldCode,oldRun,oldArtifact]};
  return {snapshot,codes,oldCode,oldRun,oldArtifact};
}
function setup(snapshot){const D=A.project(snapshot),context={window:{RP_DATA:D,RWSAdapter:A}};vm.runInNewContext(fs.readFileSync(require.resolve('../evidence.js'),'utf8'),context);return {D,R:context.window.RPEvidence};}
function outputs(D){return vm.runInNewContext(`(()=>{${slice('executions','codeLaneNodes')}return {executions,codeResults};})()`,{D});}
function dispatch(globals){let click;const start=source.indexOf("  document.addEventListener('click',event=>{"),end=source.indexOf("  document.addEventListener('keydown',event=>{",start);vm.runInNewContext(source.slice(start,end),{document:{addEventListener(name,handler){click=handler;}},...globals});return data=>click({target:{closest:()=>({dataset:typeof data==='string'?{action:data}:data})}});}
function canvas(D,research){
  const panel={innerHTML:''},state={selectedCodeId:null,selectedExecution:null,showHistoricalSources:null,codeScope:'experiment',codeRelations:'inheritance',associationHighlight:true};
  const render=vm.runInNewContext(`(()=>{${slice('codeLaneNodes','associationBadge')}${slice('renderCode','layoutCode')}return renderCode;})()`,{D,A,state,layout:{code:{}},codeContextLinks:[],get:(kind,id)=>D[kind]?.find(row=>row.id===id),currentH:()=>research,currentExp:()=>({id:null}),contextCodeLinks:()=>[],esc:A.esc,$:selector=>selector==='#code-content'?panel:null,rememberPanel:()=>({}),captureRects:()=>new Map(),codeResults:outputs(D).codeResults,codeCard:code=>`<article>${code.title}</article>`,regionHeader:()=>'',codeInspector:()=>'',layoutCode(){},restorePanel(){},animateLayout(){},syncLayoutControls(){}});
  render();return panel.innerHTML;
}
test('four own contracted cards hide external source code without inventing spec cards or execution facts',()=>{
  const f=fixture(),oldSpec=env('spec','old-contract',{title:'Old external contract',kind:'inference',status:'ready'},1,'old'),oldResearch=env('research','old-question',{title:'Old external research',kind:'exploration',implementationLinks:[{targetRef:oldSpec.ref,role:'implementation'}]},1,'old'),{D}=setup({...f.snapshot,references:[...f.snapshot.references,oldSpec,oldResearch]}),links=A.researchCodeRelations(D,D.hypotheses[0]),visibility=A.codeVisibility(D),M=outputs(D);
  assert.equal(visibility.showHistoricalSources,false);assert.equal(visibility.historicalSourceCount,1);assert.equal(visibility.hiddenCount,1);assert.equal(visibility.codes.length,4);assert.equal(links.length,4);assert.ok(links.every(link=>link.targetRef.type==='code'));
  const nodes=vm.runInNewContext(`(()=>{${slice('codeLaneNodes','associationBadge')}return codeLaneNodes;})()`,{D,A,state:{showHistoricalSources:null},codeContextLinks:links,currentH:()=>D.hypotheses[0],get:(kind,id)=>D[kind]?.find(row=>row.id===id)});
  assert.equal(D.hypotheses.length,1);assert.equal(D.specs.length,5);assert.equal(['inference','analysis','evaluation','report'].flatMap(kind=>Array.from(nodes(kind))).length,4);
  for(const code of visibility.codes){assert.equal(M.executions(code).length,0);assert.equal(M.codeResults(code).length,0);assert.equal(A.historicalMaterials(D,code).length,1);}
  assert.equal(M.codeResults(D.codes.find(code=>code.isExternal)).length,1);
});
test('legacy projects keep their default; external and non-current contracted references cannot hide sources',()=>{
  const f=fixture(),old={...f.snapshot,projectId:'old',records:[f.oldCode,f.oldRun,f.oldArtifact],references:f.codes},legacy=A.project(old);
  assert.equal(A.codeVisibility(legacy).showHistoricalSources,true);assert.equal(A.codeVisibility(legacy).codes.length,5);
  const d=A.project({...f.snapshot,records:[],references:[...f.codes,f.oldCode]});assert.equal(A.codeVisibility(d).showHistoricalSources,true);
  const foreign=A.project({...f.snapshot,records:[],references:[{...f.oldCode,record:{...f.oldCode.record,specRef:ref('spec','foreign',1,'old')}}]});assert.equal(A.codeVisibility(foreign).showHistoricalSources,true);
  assert.equal(A.codeVisibility(legacy,false).codes.length,1);assert.equal(A.codeVisibility(A.project(f.snapshot),true).codes.length,5);
});
test('declared external implementation, control and diagnostic stay visible beside collapsible provenance code',()=>{
  for(const role of ['implementation','control','diagnostic']){
    const f=fixture(),external=env('code','explicit-use',{title:'Explicit external '+role,kind:'inference',version:'v1',source:{}},1,'old');
    f.snapshot.records.find(record=>record.ref.type==='research').record.implementationLinks.push({targetRef:external.ref,role});
    const {D}=setup({...f.snapshot,references:[...f.snapshot.references,external]}),research=D.hypotheses[0],visibility=A.codeVisibility(D,null,research),html=canvas(D,research);
    assert.equal(visibility.codes.length,5);assert.ok(visibility.codes.some(code=>code.id===A.key(external.ref)));assert.ok(!visibility.codes.some(code=>code.id===A.key(f.oldCode.ref)));assert.equal(visibility.historicalSourceCount,1);assert.equal(visibility.hiddenCount,1);
    assert.equal(A.codeVisibility(D,false,research).codes.length,5);assert.equal(A.codeVisibility(D,true,research).codes.length,6);
    assert.match(html,/显示历史来源代码.* · 1<\/button>/);assert.match(html,new RegExp('Explicit external '+role));assert.doesNotMatch(html,/Original method/);
    // Changing the selected research removes only that research's declaration protection.
    assert.equal(A.codeVisibility(D,null,{raw:{implementationLinks:[]}}).historicalSourceCount,2);
  }
});
test('an explicitly declared external specification protects only implementations of its exact revision',()=>{
  const f=fixture(),spec=env('spec','external-spec',{title:'External contract',kind:'inference',status:'ready'},1,'old'),exact=env('code','exact-implementation',{title:'Exact external implementation',kind:'inference',version:'v1',specRef:spec.ref,source:{}},1,'old'),newer=env('code','other-implementation',{title:'Other spec revision implementation',kind:'inference',version:'v2',specRef:{...spec.ref,version:2},source:{}},1,'old');
  f.snapshot.records.find(record=>record.ref.type==='research').record.implementationLinks.push({targetRef:spec.ref,role:'control'});
  const {D}=setup({...f.snapshot,references:[...f.snapshot.references,spec,exact,newer]}),research=D.hypotheses[0],visibility=A.codeVisibility(D,null,research),html=canvas(D,research);
  assert.equal(visibility.codes.length,5);assert.ok(visibility.codes.some(code=>code.id===A.key(exact.ref)));assert.ok(!visibility.codes.some(code=>code.id===A.key(newer.ref)));assert.equal(visibility.historicalSourceCount,2);assert.equal(visibility.hiddenCount,2);assert.match(html,/显示历史来源代码.* · 2<\/button>/);assert.match(html,/Exact external implementation/);assert.doesNotMatch(html,/Other spec revision implementation|Original method/);
});
test('historical materials retain exact original producer/code references and remain separate from own outputs',()=>{
  const f=fixture(),before=JSON.stringify(f.snapshot),{D,R}=setup(f.snapshot),code=D.codes.find(c=>!c.isExternal),item=A.historicalMaterials(D,code)[0],html=R.render('code',code.id);
  assert.deepEqual(item.ref,f.oldArtifact.ref);assert.deepEqual(item.producerRef,f.oldRun.ref);assert.deepEqual(item.codeRef,f.oldCode.ref);assert.equal(JSON.stringify(f.snapshot),before);
  assert.match(html,/历史复用材料/);assert.match(html,/重构一致性未验证/);assert.match(html,/不计为本版产出或执行/);assert.match(html,/真实生产者/);assert.match(html,/Original saved image/);assert.match(html,/Original run/);assert.match(html,/data-action="related-code"/);assert.match(html,/Original method/);assert.match(html,/来源凭据 · 0 项/);
  assert.match(R.render('artifact',A.key(f.oldArtifact.ref)),new RegExp('data-action="related-code" data-id="'+A.key(f.oldCode.ref)+'"'));
});
test('actual inspector overview and outputs separate historical evidence from one real newly produced artifact',()=>{
  const f=fixture(),run=env('run','new-run',{title:'New actual run',kind:'inference',status:'completed',codeRef:f.codes[0].ref}),artifact=env('artifact','new-output',{title:'New actual output',producerRef:run.ref,kind:'image',uri:'/new.png'}),{D,R}=setup({...f.snapshot,records:[...f.snapshot.records,run,artifact]}),code=D.codes.find(c=>c.ref.id==='inference'),M=outputs(D),s={codeDetailHistory:[],codeDetailTab:'overview'},section=(title,body)=>`<section><h3>${title}</h3>${body}</section>`;
  const inspector=vm.runInNewContext(`(()=>{${slice('codeDetails','specLibrary')}return codeInspector;})()`,{D,A,I,state:s,codeContextLinks:[],window:{RPEvidence:R},get:(kind,id)=>D[kind]?.find(row=>row.id===id),currentH:()=>D.hypotheses[0],esc:A.esc,inspectorSection:section,inspectorText:text=>`<p>${text}</p>`,previewRecords:()=>'',executions:M.executions,button:(type,id,label)=>`<button>${label}</button>`,researchLinkList:()=>''});
  assert.deepEqual(Array.from(M.codeResults(code),r=>r.title),['New actual output']);
  const overview=inspector(code,false,M.codeResults(code));assert.match(overview,/1 项产物 · 1 项执行/);assert.match(overview,/历史复用材料/);assert.match(overview,/Original saved image/);
  s.codeDetailTab='outputs';const html=inspector(code,false,M.codeResults(code));assert.match(html,/全部产出 · 1/);assert.match(html,/New actual output/);assert.match(html,/历史复用材料/);assert.match(html,/重构一致性未验证/);assert.match(html,/Original saved image/);
});
test('missing artifact and producer versions never resolve to newer loaded records',()=>{
  const f=fixture(),newArtifact={...f.oldArtifact,ref:{...f.oldArtifact.ref,version:2},record:{...f.oldArtifact.record,title:'NEWER OUTPUT'}},newRun={...f.oldRun,ref:{...f.oldRun.ref,version:2},record:{...f.oldRun.record,title:'NEWER RUN'}};
  const first=setup({...f.snapshot,references:[f.oldCode,f.oldRun,newArtifact]}),code=first.D.codes.find(c=>!c.isExternal),html=first.R.render('code',code.id);
  assert.equal(A.historicalMaterials(first.D,code)[0].artifact,undefined);assert.match(html,/此精确产物版本未载入/);assert.match(html,/disabled/);assert.doesNotMatch(html,/NEWER OUTPUT/);
  const second=setup({...f.snapshot,references:[f.oldCode,newRun,f.oldArtifact]}),secondCode=second.D.codes.find(c=>!c.isExternal),item=A.historicalMaterials(second.D,secondCode)[0];assert.equal(item.producer,undefined);assert.equal(item.codeRef,undefined);assert.deepEqual(item.producerRef,f.oldRun.ref);assert.doesNotMatch(second.R.render('code',secondCode.id),/NEWER RUN/);
  const newerCode={...f.oldCode,ref:{...f.oldCode.ref,version:2},record:{...f.oldCode.record,title:'NEWER CODE'}},third=setup({...f.snapshot,references:[newerCode,f.oldRun,f.oldArtifact]}),thirdCode=third.D.codes.find(c=>!c.isExternal),thirdHtml=third.R.render('code',thirdCode.id);assert.equal(A.historicalMaterials(third.D,thirdCode)[0].code,undefined);assert.doesNotMatch(thirdHtml,/NEWER CODE|data-action="related-code"/);
});
test('historical source navigation reveals and selects an exact hidden code while retaining research and highlight state',()=>{
  const {D}=setup(fixture().snapshot),old=D.codes.find(c=>c.isExternal),s={hypothesisId:'question',experimentId:'experiment',associationHighlight:false,selectedCodeId:null,selectedExecution:null,showHistoricalSources:null,codeDetailHistory:[]};
  const select=vm.runInNewContext(`(()=>{${slice('selectCode','selectExecution')}return selectCode;})()`,{state:s,D,A,I,get:(kind,id)=>D[kind]?.find(row=>row.id===id),contextCodeLinks:()=>[],currentH:()=>D.hypotheses[0],executionCode:()=>null,executions:outputs(D).executions,closeReader(){},renderCode(){},status(){},emitContext(){},layout:{code:{}}});
  assert.equal(A.codeVisibility(D,s.showHistoricalSources).hiddenCount,1);dispatch({state:s,selectCode:select,setView(){},selectH(){throw Error('Provenance navigation must retain the research');}})({action:'related-code',id:old.id});assert.equal(s.selectedCodeId,old.id);assert.equal(s.showHistoricalSources,true);assert.equal(A.codeVisibility(D,s.showHistoricalSources).hiddenCount,0);assert.equal(s.hypothesisId,'question');assert.equal(s.experimentId,'experiment');assert.equal(s.associationHighlight,false);
});
test('show/hide control changes visibility only, preserving details and the independent highlight state',()=>{
  const {D}=setup(fixture().snapshot),s={hypothesisId:'question',selectedCodeId:'inference',associationHighlight:false,showHistoricalSources:null,codeDetailHistory:[{type:'artifact',id:'saved',scope:'fixed'}]},before=structuredClone(s),click=dispatch({state:s,A,D,currentH:()=>D.hypotheses[0],renderCode(){}});
  click('toggle-historical-sources');assert.deepEqual(s,{...before,showHistoricalSources:true});click('toggle-historical-sources');assert.deepEqual(s,{...before,showHistoricalSources:false});
});
test('historical reader navigation stays inside a frozen report and never opens live canvas sources',()=>{
  const f=fixture(),report=env('report','frozen',{title:'Frozen report',markdown:'Report',inputRefs:[f.codes[0].ref],snapshot:{records:[f.codes[0],f.oldArtifact]}}),{R}=setup({...f.snapshot,records:[...f.snapshot.records,report]}),scope=R.scopeForReport(A.key(report.ref)),html=R.render('code',A.key(f.codes[0].ref),{scope});
  assert.match(html,/Original saved image/);assert.match(html,/重构一致性未验证/);assert.doesNotMatch(html,/Original method|Original run|data-action="related-code"/);
});
test('1056 exact historical materials use bounded initial pagination while retaining every reference',()=>{
  const f=fixture(),artifacts=Array.from({length:1056},(_,i)=>({...f.oldArtifact,ref:{...f.oldArtifact.ref,id:'history-'+i},record:{...f.oldArtifact.record,title:'Historical output '+i}}));
  f.codes[0].record.source.historicalArtifactRefs=artifacts.map(artifact=>artifact.ref);
  const {D,R}=setup({...f.snapshot,references:[f.oldCode,f.oldRun,...artifacts]}),code=D.codes.find(c=>c.ref.id==='inference'),html=R.historicalReuse(code);
  assert.equal(A.historicalMaterials(D,code).length,1056);assert.equal((html.match(/class="historical-material"/g)||[]).length,6);assert.match(html,/历史材料 · 1056 项 · 1\/176 页/);assert.match(html,/Historical output 5/);assert.doesNotMatch(html,/Historical output 6/);assert.equal(code.raw.source.historicalArtifactRefs.length,1056);
});
