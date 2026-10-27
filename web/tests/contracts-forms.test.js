'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process'),A=require('../live-model.js');
test('actual ready-spec and implementation handlers emit complete valid contracts',async()=>{
  const specRef={projectId:'p',type:'spec',id:'S',version:1},spec={title:'Reusable image method',schemaVersion:1,kind:'inference',status:'ready',purpose:'Render configurable inputs',inputs:[],outputs:[{name:'result',kind:'image',semantic:'final_image',required:true,multiple:false,description:''}],configSchema:{type:'object',properties:{}},dependencies:[],acceptanceChecks:[{id:'check-1',description:'Accepts two input cases'}],capabilities:['image-edit']},D=A.project({projectId:'p',projects:[],records:[{ref:specRef,record:spec}]}),listeners={},writes=[];
  class Data{constructor(form){this.values=form.values;}get(k){return this.values[k]??'';}getAll(k){return this.values[k]||[];}}
  const UI={project:()=>({id:'p',revision:1}),isBusy:()=>false,openDialog(){},fail(e){throw e;},async write(name,args){writes.push({name,arguments:{...args,requestId:'contract-'+writes.length}});}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../contracts.js'),'utf8'),{FormData:Data,document:{addEventListener:(name,fn)=>listeners[name]=fn},window:{RWSAdapter:A,RP_DATA:D,RWSUI:UI}});
  const click=(kind,id)=>listeners.click({target:{closest:()=>({dataset:{contract:kind,id}})}}),submit=form=>listeners.submit({preventDefault(){},target:form});
  click('new');const fields={'port-name':'result','port-kind':'image','port-semantic':'final_image','port-description':''},port={querySelector:selector=>{const name=selector.match(/name="([^"]+)"/)[1];return {value:fields[name],checked:name==='port-required'};}};
  await submit({id:'contract-form',dataset:{project:'p',revision:'1'},values:{title:spec.title,kind:'inference',status:'ready',purpose:spec.purpose,configSchema:'{"type":"object","properties":{}}',checks:'Accepts two input cases',capabilities:'image-edit',dependency:[]},querySelectorAll:selector=>selector.includes('"outputs"')?[port]:[]});
  click('implement',A.key(specRef));await submit({id:'implementation-form',dataset:{project:'p',revision:'1'},values:{title:spec.title,version:'v1',repository:'https://example.org/repo',commit:'abc1234',modulePath:'src/method.py',entrypoint:'src.method:run',capabilities:'image-edit',parent:[]},querySelectorAll:()=>[{dataset:{check:'check-1'},querySelector:selector=>({value:selector.includes('status')?'passed':'python test: 2 cases passed'})}]});
  const payload=JSON.parse(JSON.stringify(writes));assert.deepEqual(payload.map(x=>x.name),['rws_spec_save','rws_code_register']);assert.deepEqual(payload[1].arguments.record.specRef,specRef);assert.equal(payload[1].arguments.record.checkEvidence[0].checkId,'check-1');
  const script=`import json,sys,tempfile
from pathlib import Path
from rws.core import Store,tool_definitions,validate_schema
ops=json.load(sys.stdin);defs={x['name']:x['inputSchema'] for x in tool_definitions()}
for op in ops: validate_schema(op['arguments'],defs[op['name']])
with tempfile.TemporaryDirectory() as temp:
 s=Store(Path(temp)/'test.sqlite3')
 s.call('rws_project_create',dict(projectId='p',name='P',requestId='create'))
 ops[0]['arguments']['record']['id']='S'
 for op in ops:
  op['arguments']['expectedRevision']=s.snapshot('p')['revision']
  assert s.call(op['name'],op['arguments'],actor='human')['ok']
 s.close()
 print('saved contract and implementation')
`;
  assert.match(execFileSync('python3',['-c',script],{cwd:path.resolve(__dirname,'../..'),input:JSON.stringify(payload),encoding:'utf8'}),/saved contract and implementation/);
});
