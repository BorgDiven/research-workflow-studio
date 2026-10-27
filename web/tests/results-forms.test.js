'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process'),A=require('../live-model.js'),M=require('../results-model.js');
const ref=(type,id)=>({projectId:'p',type,id,version:1}),env=(type,id,record)=>({ref:ref(type,id),record});
function browser(){
  const records=[env('code','C',{title:'Method',kind:'inference',version:'v1'}),env('run','R',{codeRef:ref('code','C'),config:{cfg:4},status:'completed'}),...['S1','S2'].map((sampleId,i)=>env('artifact','A'+(i+1),{title:'Output '+sampleId,kind:'image',semantic:'final_image',sampleId,producerRef:ref('run','R'),config:{cfg:4},content:{kind:'image-set',items:[{uri:'/sample.png'}]}}))],D=A.project({projectId:'p',projects:[{id:'p',name:'Project'}],records}),listeners={},writes=[],host={innerHTML:'',querySelector:()=>({scrollTop:0})};
  const UI={project:()=>({id:'p',revision:1}),isBusy:()=>false,openDialog(){},fail(error){throw error;},async write(name,args){writes.push({name,arguments:{...args,requestId:'ui-'+writes.length}});}};
  class Data{constructor(form){this.values=form.values;}get(key){return this.values[key]??'';}getAll(key){return this.values[key]||[];}}
  const context={FormData:Data,document:{querySelector:()=>host,addEventListener:(name,fn)=>listeners[name]=fn},window:{RWSAdapter:A,RWSResultsModel:M,RP_DATA:D,RPEvidence:{typed:()=>'',batch:(items,fn)=>items.map(fn).join(''),refLink:()=>''},RWSUI:UI}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../results.js'),'utf8'),context);
  context.window.RWSResults.render({experiment:{ref:ref('experiment','E')},artifacts:D.artifacts,evaluations:[],analyses:[],reports:[]});
  return {writes,click:action=>listeners.click({target:{closest:()=>({dataset:{results:action}})}}),select:id=>listeners.change({target:{dataset:{resultsSelect:A.key(ref('artifact',id))},checked:true}}),submit:values=>listeners.submit({preventDefault(){},target:{id:'evidence-desk-form',dataset:{project:'p',revision:'1'},values}})};
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
