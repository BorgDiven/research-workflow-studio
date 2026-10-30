'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process'),A=require('../live-model.js'),M=require('../results-model.js');
const ref=(type,id)=>({projectId:'p',type,id,version:1}),env=(type,id,record)=>({ref:ref(type,id),record});
function browser(extra=[]){
  const records=[env('code','C',{title:'Method',kind:'inference',version:'v1'}),env('run','R',{codeRef:ref('code','C'),config:{cfg:4},status:'completed'}),...['S1','S2'].map((sampleId,i)=>env('artifact','A'+(i+1),{title:'Output '+sampleId,kind:'image',semantic:'final_image',sampleId,producerRef:ref('run','R'),config:{cfg:4},content:{kind:'image-set',items:[{uri:'/sample.png'}]}})),...extra],D=A.project({projectId:'p',projects:[{id:'p',name:'Project'}],records}),listeners={},writes=[],host={innerHTML:'',querySelector:()=>({scrollTop:0})};
  const UI={project:()=>({id:'p',revision:1}),isBusy:()=>false,openDialog(){},closeDialog(){},fail(error){throw error;},async write(name,args){writes.push({name,arguments:{...args,requestId:'ui-'+writes.length}});}};
  class Data{constructor(form){this.values=form.values;}get(key){return this.values[key]??'';}getAll(key){return this.values[key]||[];}}
  const context={FormData:Data,document:{querySelector:()=>host,addEventListener:(name,fn)=>listeners[name]=fn},window:{RWSAdapter:A,RWSResultsModel:M,RP_DATA:D,RPEvidence:{typed:()=>'',batch:(items,fn)=>items.map(fn).join(''),refLink:()=>''},RWSUI:UI}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../results.js'),'utf8'),context);
  context.window.RWSResults.render({experiment:{ref:ref('experiment','E')},artifacts:D.artifacts,evaluations:[],analyses:[],reports:[]});
  return {writes,host,data:D,choose:(key,value)=>listeners.change({target:{dataset:{resultsChoice:key},value}}),spec:()=>context.window.RWSResults.spec(),click:action=>listeners.click({target:{closest:()=>({dataset:{results:action}})}}),select:id=>listeners.change({target:{dataset:{resultsSelect:A.key(ref('artifact',id))},checked:true}}),change:(field,value)=>listeners.change({target:{dataset:{resultsField:field},value}}),submit:(values,id='evidence-desk-form')=>listeners.submit({preventDefault(){},target:{id,dataset:{project:'p',revision:'1'},values}})};
}
test('actual comparison, analysis and report form payloads satisfy backend schema and save',async()=>{
  const ui=browser();ui.select('A1');ui.click('save');await ui.submit({title:'Browser comparison',fixed:'{}',description:'Compare methods'});ui.click('analysis');await ui.submit({title:'Browser analysis',observations:'One image inspected',interpretation:'Partial evidence',scope:'S1 and S2',limitations:'S2 not selected',expected:'2'});ui.click('report');await ui.submit({title:'Browser report',markdown:'# Report\n\nPartial evidence.',analysis:[],evaluation:[]});
  assert.deepEqual(ui.writes.map(w=>w.name),['rws_comparison_save','rws_analysis_save','rws_report_create_revision']);
  const payload=JSON.parse(JSON.stringify(ui.writes));assert.deepEqual(payload[0].arguments.record.varyingConditions,['implementation']);assert.deepEqual(payload[1].arguments.record.scope.sampleIds,['S1','S2']);assert.deepEqual(payload[1].arguments.record.coverage,{expected:2,observed:1,missingSampleIds:['S2']});
  const script=`import json,sys,tempfile
from pathlib import Path
from rws.core import Store,tool_definitions,validate_schema
payload=json.load(sys.stdin)
defs={t['name']:t['inputSchema'] for t in tool_definitions()}
for op in payload: validate_schema(op['arguments'],defs[op['name']])
with tempfile.TemporaryDirectory() as temp:
 s=Store(Path(temp)/'test.sqlite3'); n=0
 def put(name,record):
  global n
  n+=1
  return s.call(name,dict(projectId='p',requestId='fixture-'+str(n),expectedRevision=s.snapshot('p')['revision'],record=record))['result']['ref']
 s.call('rws_project_create',dict(projectId='p',name='Test',requestId='project'))
 h=put('rws_research_save',dict(id='H',title='Question',question='What changes?',kind='exploration'))
 e=put('rws_experiment_save',dict(id='E',title='Experiment',researchRef=h))
 c=put('rws_code_register',dict(id='C',title='Method',kind='inference',version='v1',source='method.py'))
 r=put('rws_run_register',dict(id='R',title='Producer',codeRef=c,experimentRef=e,config={'cfg':4},status='completed'))
 for i in (1,2): put('rws_artifact_register',dict(id='A'+str(i),title='Output',kind='image',semantic='final_image',sampleId='S'+str(i),producerRef=r,config={'cfg':4},availability='unknown'))
 for op in payload:
  op['arguments']['expectedRevision']=s.snapshot('p')['revision']
  result=s.call(op['name'],op['arguments'],actor='human')
  assert result['ok'],result
 print('saved 3 browser forms')
 s.close()
`;
  assert.match(execFileSync('python3',['-c',script],{cwd:path.resolve(__dirname,'../..'),input:JSON.stringify(payload),encoding:'utf8'}),/saved 3 browser forms/);
});

test('method column form preserves exact members and saving pins groups to included inputs',async()=>{
  const ui=browser();ui.select('A1');ui.select('A2');ui.click('method-group');
  await ui.submit({group:'',label:'Native comparison'},'method-group-form');
  assert.equal(ui.writes.length,0);assert.equal(ui.spec().axis,'method');
  const groups=JSON.parse(JSON.stringify(ui.spec().methodGroups));assert.deepEqual(groups,[{id:'method-1',label:'Native comparison',artifactRefs:[ref('artifact','A1'),ref('artifact','A2')]}]);
  assert.match(ui.host.innerHTML,/生成来源见各张结果/);assert.match(ui.host.innerHTML,/配置与生成来源/);
  ui.click('save');await ui.submit({title:'Grouped comparison',fixed:'{}',description:'Native evidence from selected results'});
  const record=JSON.parse(JSON.stringify(ui.writes[0].arguments.record));assert.deepEqual(record.viewSpec.methodGroups,groups);
  assert.deepEqual(record.inputRefs,[ref('artifact','A1'),ref('artifact','A2')]);
  const comparison=env('comparison','CMP',record);ui.data.comparisons.push({...comparison,id:A.key(comparison.ref),raw:record,title:record.title,isCurrent:true});
  ui.change('scope',A.key(comparison.ref));assert.deepEqual(JSON.parse(JSON.stringify(ui.spec().methodGroups)),groups);
});

test('removing a result from a comparison method column does not remove its source',async()=>{
  const ui=browser();ui.select('A1');ui.click('method-group');await ui.submit({group:'',label:'Native'},'method-group-form');
  ui.click('method-group');await ui.submit({group:'__remove__',label:''},'method-group-form');
  assert.equal(ui.spec().methodGroups.length,0);assert.equal(ui.data.artifacts.length,2);assert.equal(ui.writes.length,0);
});

test('grouping duplicate cases from two codes requires an explicit candidate and keeps its source',async()=>{
  const extra=[env('code','C2',{title:'New method',kind:'inference',version:'v2'}),env('run','R2',{codeRef:ref('code','C2'),status:'completed'}),env('artifact','A3',{title:'New native output',kind:'image',semantic:'final_image',sampleId:'S1',producerRef:ref('run','R2'),config:{cfg:4}})];
  const ui=browser(extra);ui.select('A1');ui.select('A3');ui.click('method-group');await ui.submit({group:'',label:'Native comparison'},'method-group-form');
  assert.equal(ui.spec().filters.selectedArtifactIds.length,0);assert.match(ui.host.innerHTML,/2 份候选结果/);
  const items=ui.data.artifacts.map(a=>M.describe(a,{...ui.data,key:A.key})),matrix=M.matrix(items,ui.spec()),[cellKey]=[...matrix.cells].find(([,candidates])=>candidates.length===2);
  ui.choose(cellKey,A.key(ref('artifact','A3')));ui.select('A3');ui.click('save');await ui.submit({title:'Chosen candidate',fixed:'{}',description:'Review explicitly selected output'});
  const saved=JSON.parse(JSON.stringify(ui.writes[0].arguments.record));assert.equal(saved.viewSpec.filters.selections[cellKey],A.key(ref('artifact','A3')));
  assert.deepEqual(saved.viewSpec.filters.selectedArtifactIds,[A.key(ref('artifact','A3'))]);
  assert.match(ui.host.innerHTML,/New method/);assert.match(ui.host.innerHTML,/p \/ R2/);
  assert.equal(ui.data.artifacts.find(a=>a.ref.id==='A3').raw.producerRef.id,'R2');
});

test('a missing pinned candidate requires an explicit replacement even when only one remains',()=>{
  const ui=browser(),items=ui.data.artifacts.map(a=>M.describe(a,{...ui.data,key:A.key})),grid=M.matrix(items,{}),row=grid.rows.find(r=>r.item.sampleId==='S1'),key=grid.cellKey(row.key,grid.columns[0].key);
  const record={title:'Pinned missing choice',inputRefs:[ref('artifact','A1')],viewSpec:{mode:'multi',filters:{selections:{[key]:A.key(ref('artifact','missing'))}}}},comparison=env('comparison','CMP',record);
  ui.data.comparisons.push({...comparison,id:A.key(comparison.ref),raw:record,title:record.title,isCurrent:true});ui.change('scope',A.key(comparison.ref));
  assert.match(ui.host.innerHTML,/1 份候选结果/);assert.match(ui.host.innerHTML,/data-results-choice=/);assert.match(ui.host.innerHTML,/请选择要查看的产出/);
  ui.choose(key,A.key(ref('artifact','A1')));assert.match(ui.host.innerHTML,/配置与生成来源/);
});
