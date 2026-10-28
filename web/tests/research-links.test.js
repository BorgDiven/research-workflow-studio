'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const A=require('../live-model.js'),M=require('../studio-model.js');
const ref=(type,id,version=1,projectId='p')=>({projectId,type,id,version});
const env=(type,id,record,version=1,projectId='p')=>({ref:ref(type,id,version,projectId),record:{title:id,...record}});
const h=id=>env('research',id,{kind:'exploration',question:'What can be observed?',stage:'idea'});
const e=(id,hid)=>env('experiment',id,{researchRef:ref('research',hid),status:'planned',foundationRevision:1});
const c=(id,extra={})=>env('code',id,{kind:'inference',version:'v1',...extra});
const run=(id,cid,eid,extra={})=>env('run',id,{codeRef:ref('code',cid),experimentRef:ref('experiment',eid),status:'completed',...extra});
const artifact=(id,rid)=>env('artifact',id,{producerRef:ref('run',rid),kind:'image'});
function fixture(extra=[]){return {projectId:'p',revision:1,projects:[{id:'p',name:'Synthetic project'}],records:[h('H1'),h('H2'),e('E1','H1'),e('E2','H2'),c('C1'),c('C2'),run('R1','C1','E1'),run('R2','C2','E1'),artifact('A1','R1'),artifact('A2','R2'),...extra],references:[]};}
const current=(d,type,id)=>d[A.groups[type]].find(row=>row.ref.id===id&&row.ref.projectId==='p');
const relations=(d,id,options)=>A.researchCodeRelations(d,current(d,'research',id),options);
const codeIds=links=>links.filter(link=>link.targetRef.type==='code').map(link=>link.targetRef.id).sort();
const reused=()=>env('usage','U2',{experimentRef:ref('experiment','E2'),artifactRefs:[ref('artifact','A1'),ref('artifact','A2')],role:'control'});

test('one usage of two producers highlights both codes and both reverse research links without moving artifacts',()=>{
  const s=fixture([reused()]),before=JSON.stringify(s),d=A.project(s),member=current(d,'experiment','E2').members[0];
  assert.equal(member.runId,null);assert.deepEqual(member.runIds.sort(),[A.key(ref('run','R1')),A.key(ref('run','R2'))].sort());
  assert.deepEqual(codeIds(relations(d,'H2')),['C1','C2']);
  for(const code of d.codes){assert.deepEqual(A.researchForCode(d,code).map(x=>x.research.ref.id).sort(),['H1','H2']);assert.equal(relations(d,'H2').find(link=>link.id===code.id).facts[0].kind,'reused');}
  assert.equal(JSON.stringify(s),before);assert.equal(current(d,'artifact','A1').raw.producerRef.id,'R1');
});

test('revoked or removed usage disappears from relationships while its producer remains',()=>{
  for(const field of ['revoked','removed']){const u=reused();u.record[field]=true;const d=A.project(fixture([u]));assert.deepEqual(relations(d,'H2'),[]);assert.equal(current(d,'artifact','A1').raw.producerRef.id,'R1');assert.deepEqual(A.researchForCode(d,current(d,'code','C1')).map(x=>x.research.ref.id),['H1']);}
});

test('whole research includes all experiments; experiment scope excludes other experiments and research-wide declarations',()=>{
  const s=fixture([e('E3','H2'),run('R3','C2','E3')]);s.records.find(x=>x.ref.id==='H2').record.implementationLinks=[{targetRef:ref('code','C1'),role:'control'}];
  const d=A.project(s);assert.deepEqual(codeIds(relations(d,'H2')),['C1','C2']);
  assert.deepEqual(relations(d,'H2',{experiment:current(d,'experiment','E2')}),[]);
  assert.deepEqual(codeIds(relations(d,'H2',{experiment:current(d,'experiment','E3')})),['C2']);
});

test('purpose links work before runs and inherit only the exact specification revision',()=>{
  const s=fixture();s.records=s.records.filter(x=>!['run','artifact'].includes(x.ref.type));
  s.records.push(env('spec','S',{purpose:'Probe',kind:'analysis',status:'draft'}),env('spec','S',{purpose:'Changed probe',kind:'analysis',status:'ready'},2));
  s.records.find(x=>x.ref.id==='C1').record.specRef=ref('spec','S',1);s.records.find(x=>x.ref.id==='C2').record.specRef=ref('spec','S',2);
  s.records.find(x=>x.ref.id==='H2').record.implementationLinks=[{targetRef:ref('spec','S',1),role:'diagnostic',note:'Inspect velocity'}];
  const d=A.project(s),links=relations(d,'H2');assert.deepEqual(codeIds(links),['C1']);assert.equal(links.length,2);
  assert.ok(links.every(link=>link.facts.every(f=>f.kind==='declared')));assert.equal(A.relatedExecution(links.find(x=>x.targetRef.type==='code')),null);
  assert.deepEqual(A.relationLabels(links[0]),['计划用途 · 诊断']);assert.equal(links[0].targetRef.version,1);
});

test('same code and artifact IDs from another project do not bind a local implementation',()=>{
  const u=env('usage','U2',{experimentRef:ref('experiment','E2'),artifactRefs:[ref('artifact','A1',1,'foreign')],role:'control'}),s=fixture([u]);
  s.references.push(env('artifact','A1',{producerRef:ref('run','R1',1,'foreign')},1,'foreign'),env('run','R1',{codeRef:ref('code','C1',1,'foreign'),status:'completed'},1,'foreign'),env('code','C1',{kind:'inference',version:'foreign'},1,'foreign'));
  const d=A.project(s),links=relations(d,'H2');assert.equal(links.length,1);assert.equal(links[0].targetRef.projectId,'foreign');assert.equal(A.researchForCode(d,current(d,'code','C1')).length,1);
});

test('run plans stay distinct from actual execution and selection prefers the scoped execution',()=>{
  const d=A.project(fixture([run('R3','C1','E2',{status:'planned'})])),link=relations(d,'H2')[0];
  assert.deepEqual(A.relationLabels(link),['运行计划']);assert.deepEqual(A.relatedExecution(link),{type:'run',id:current(d,'run','R3').id});
});

test('evaluation, analysis and report generators follow explicit research evidence; unbound similar inputs do not',()=>{
  const analysis=env('analysis','AN',{codeRef:ref('code','CA'),experimentRefs:[ref('experiment','E2')],inputRefs:[]});
  const s=fixture([c('CE',{kind:'evaluation'}),c('CA',{kind:'analysis'}),c('CR',{kind:'report'}),env('evaluation','EV',{codeRef:ref('code','CE'),experimentRef:ref('experiment','E2'),inputRefs:[],results:[]}),analysis,env('report','RP',{generatorCodeRef:ref('code','CR'),analysisRefs:[analysis.ref],snapshot:{records:[analysis, e('E2','H2')]}}),env('analysis','unbound',{codeRef:ref('code','C1'),inputRefs:[ref('artifact','A1')],observations:'Same image is not an experiment binding'})]);
  const d=A.project(s);assert.deepEqual(codeIds(relations(d,'H2')),['CA','CE','CR']);
});

test('missing declared target remains visible as unresolved instead of selecting a latest revision',()=>{
  const s=fixture();s.records.find(x=>x.ref.id==='H2').record.implementationLinks=[{targetRef:ref('spec','MISSING',1),role:'implementation'}];
  s.records.push(env('spec','MISSING',{purpose:'Later',kind:'inference'},2));const link=relations(A.project(s),'H2')[0];assert.equal(link.targetRef.version,1);assert.equal(link.available,false);
});

test('research kind, process state and scientific judgment remain different display fields',()=>{
  const s=fixture();s.records[0].record.status='completed';s.records[1].record.kind='hypothesis';s.records[1].record.hypothesis='A clear proposition';
  const d=A.project(s);assert.equal(current(d,'research','H1').kindLabel,'探索');assert.equal(current(d,'research','H1').status,'已完成');assert.equal(current(d,'research','H1').judgmentLabel,null);assert.equal(current(d,'research','H2').kindLabel,'假设验证');assert.equal(current(d,'research','H2').judgmentLabel,'待判断');
});

test('research form preserves exact purpose links by default and clears only explicitly',()=>{
  const links=[{targetRef:ref('spec','S',2,'foreign'),role:'diagnostic',note:'Fixed probe'}],existing={ref:ref('research','H'),record:{implementationLinks:links}},values={title:'Question',question:'Why?',kind:'exploration',stage:'idea'};
  assert.deepEqual(M.researchRecord(values,existing,'p').implementationLinks,links);
  assert.deepEqual(M.researchRecord(values,existing,'p',undefined,[]).implementationLinks,[]);
  assert.deepEqual(links[0].targetRef,ref('spec','S',2,'foreign'));
  assert.throws(()=>M.implementationLinksForSelection([...links,...links]),/重复/);
  assert.throws(()=>M.implementationLinksForSelection([{...links[0],targetRef:{...links[0].targetRef,version:undefined}}]),/固定版本/);
  assert.throws(()=>M.implementationLinksForSelection([{...links[0],role:'untyped'}]),/用途/);
});

test('frozen report research and code readers never offer live reverse navigation or later purpose associations',()=>{
  const oldResearch=h('H2'),source=c('C1'),report=env('report','RP',{markdown:'Frozen',researchRefs:[oldResearch.ref],snapshot:{records:[oldResearch,source]}}),s=fixture([report]);
  s.records.find(x=>x.ref.id==='H2').ref.version=2;s.records.find(x=>x.ref.id==='H2').record.implementationLinks=[{targetRef:ref('code','C2'),role:'control',note:'Later purpose'}];
  const d=A.project(s),context={window:{RP_DATA:d,RWSAdapter:A}};vm.runInNewContext(fs.readFileSync(require.resolve('../evidence.js'),'utf8'),context);const R=context.window.RPEvidence,scope=R.scopeForReport(A.key(report.ref));
  const researchHTML=R.render('hypothesis',A.key(oldResearch.ref),{scope}),codeHTML=R.render('code',A.key(source.ref),{scope});
  assert.doesNotMatch(researchHTML,/Later purpose|data-action="research-code"/);assert.doesNotMatch(codeHTML,/data-action="open-research"|data-studio="link-implementation"/);
});

test('copied context labels purpose declarations without creating a judgment for open exploration',()=>{
  const context={projectId:'p',projectName:'Synthetic',foundation:{revision:1,fields:{}},position:{researchRef:ref('research','H2'),stage:'idea'},currentResearch:{ref:ref('research','H2'),title:'Explore',kind:'exploration',hasHypothesis:false},objects:[],completed:[],pending:[],suggestedActions:[],declaredImplementations:[{researchRef:ref('research','H2'),researchTitle:'Explore',researchVersionRole:'current',targetRef:ref('spec','Probe',2),title:'Probe specification',role:'diagnostic',roleLabel:'诊断',note:'Inspect only'}]};
  const text=M.contextText(context);assert.match(text,/计划用途（不代表执行）/);assert.match(text,/Probe specification/);assert.match(text,/spec\/Probe@r2/);assert.doesNotMatch(text,/当前人工判断/);
});

test('artifact-only reports associate their renderer through exact selected material without inheriting producer experiment ownership',()=>{
  const s=fixture([reused(),c('CR',{kind:'report'}),env('report','RP',{generatorCodeRef:ref('code','CR'),inputRefs:[ref('artifact','A1')],snapshot:{records:[artifact('A1','R1'),run('R1','C1','E1'),c('C1'),e('E1','H1')]}})]),d=A.project(s);
  assert.equal(A.reportsForExperiment(d,current(d,'experiment','E2')).length,1);
  assert.ok(codeIds(relations(d,'H2')).includes('CR'));
  // H1 produced the image but did not select it as an experiment material.
  assert.equal(A.reportsForExperiment(d,current(d,'experiment','E1')).length,0);
  assert.ok(!codeIds(relations(d,'H1')).includes('CR'));
  assert.deepEqual(A.researchForCode(d,current(d,'code','CR')).map(x=>x.research.ref.id),['H2']);
});

test('comparison-only reports use exact frozen comparison inputs and agree with the report list',()=>{
  const cmp=env('comparison','CMP',{inputRefs:[ref('artifact','A2')],fixedConditions:{},varyingConditions:[]}),s=fixture([reused(),c('CR',{kind:'report'}),cmp,env('report','RP',{generatorCodeRef:ref('code','CR'),comparisonRefs:[cmp.ref],snapshot:{records:[cmp,artifact('A2','R2'),run('R2','C2','E1'),c('C2')]}})]);
  const d=A.project(s);assert.equal(A.reportsForExperiment(d,current(d,'experiment','E2')).length,1);assert.ok(codeIds(relations(d,'H2')).includes('CR'));
  // The report must not resolve a missing comparison from current live data.
  s.records.find(x=>x.ref.type==='report').record.snapshot.records=[];
  const incomplete=A.project(s);assert.equal(A.reportsForExperiment(incomplete,current(incomplete,'experiment','E2')).length,0);assert.ok(!codeIds(relations(incomplete,'H2')).includes('CR'));
});

test('explicit competing experiment binding outranks shared artifacts and report research labels',()=>{
  const an=env('analysis','AN1',{experimentRefs:[ref('experiment','E1')],inputRefs:[ref('artifact','A1')]}),s=fixture([reused(),c('CR',{kind:'report'}),an,env('report','RP',{generatorCodeRef:ref('code','CR'),researchRefs:[ref('research','H2')],analysisRefs:[an.ref],inputRefs:[ref('artifact','A1')],snapshot:{records:[an,artifact('A1','R1'),run('R1','C1','E1'),e('E1','H1')]}})]),d=A.project(s);
  assert.equal(A.reportsForExperiment(d,current(d,'experiment','E2')).length,0);assert.ok(!codeIds(relations(d,'H2')).includes('CR'));
  assert.equal(A.reportsForExperiment(d,current(d,'experiment','E1')).length,1);assert.ok(codeIds(relations(d,'H1')).includes('CR'));
});

test('planned evaluation inputs remain planned associations rather than evidence reused by the new research',()=>{
  const d=A.project(fixture([c('CE',{kind:'evaluation'}),env('evaluation','EV',{codeRef:ref('code','CE'),experimentRef:ref('experiment','E2'),status:'planned',inputRefs:[ref('artifact','A1')],results:[]})])),links=relations(d,'H2');
  assert.deepEqual(A.relationLabels(links.find(link=>link.targetRef.id==='CE')),['运行计划']);
  assert.deepEqual(A.relationLabels(links.find(link=>link.targetRef.id==='C1')),['计划输入']);
  assert.ok(links.every(link=>link.facts.every(f=>!['used','reused'].includes(f.kind))));
});
