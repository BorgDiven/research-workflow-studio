'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const A=require('../live-model.js'),M=require('../results-model.js');
const ref=(type,id,version=1)=>({projectId:'p',type,id,version});
test('a training run opens curves before any final artifact is registered',()=>{
  const spec=ref('spec','s'),code=ref('code','c'),run=ref('run','r'),experiment=ref('experiment','e'),research=ref('research','h');
  const records=[{ref:spec,record:{title:'Metric contract',kind:'training',processMetrics:[{id:'loss',unit:'1',axis:'step',scope:'run'}]}},{ref:code,record:{title:'Trainer',kind:'training',specRef:spec}},{ref:run,record:{title:'Active training',kind:'training',codeRef:code,experimentRef:experiment,status:'running',config:{}}}];
  const data=A.project({projectId:'p',revision:1,projects:[{id:'p'}],records,references:[]});
  let rendered,html='';const processHost={},host={get innerHTML(){return html;},set innerHTML(v){html=v;},querySelector:selector=>selector==='.process-host'?processHost:null};
  const window={RP_DATA:data,RWSAdapter:A,RWSResultsModel:M,RPEvidence:{},RWSProcess:{render:(target,props)=>rendered={target,props}}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../results.js'),'utf8'),{window,document:{querySelector:()=>host,addEventListener:()=>{}}});
  window.RWSResults.render({experiment:{id:A.key(experiment),ref:experiment,raw:{researchRef:research}},artifacts:[],evaluations:[],analyses:[],reports:[]});
  assert.equal(rendered.target,processHost);assert.equal(rendered.props.layout,'curve');assert.equal(rendered.props.artifacts.length,0);assert.match(html,/图像与材料/);assert.match(html,/指标/);
});
test('process refresh reads the visible range even before a blur event fires',async()=>{
  const P=require('../process-model.js'),spec=ref('spec','s'),code=ref('code','c'),run=ref('run','r'),experiment=ref('experiment','e');
  const data=A.project({projectId:'p',revision:1,projects:[{id:'p'}],records:[{ref:spec,record:{processMetrics:[{id:'loss'}]}},{ref:code,record:{kind:'training',specRef:spec}},{ref:run,record:{codeRef:code,experimentRef:experiment,status:'running'}}],references:[]});
  const listeners={},requests=[],inputs={from:{value:''},to:{value:''},metric:{value:''}},host={isConnected:true,clientWidth:1240,innerHTML:'',querySelector:s=>{const match=s.match(/data-process-field="(.*?)"/);return match?inputs[match[1]]:null;}};
  const window={RP_DATA:data,RWSAdapter:A,RWSProcessModel:P,RPEvidence:{seriesSample:x=>x,batch:()=>''},RWSLive:{call:async(name,args)=>{requests.push({name,args});return {result:{series:[],total:0,throughSequence:0,truncated:false}};}}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../process.js'),'utf8'),{window,document:{body:{dataset:{}},addEventListener:(name,fn)=>listeners[name]=fn}});
  window.RWSProcess.render(host,{layout:'curve',context:{experiment:{ref:experiment,id:A.key(experiment)}},scope:'experiment',artifacts:[],evaluations:[]});
  await Promise.resolve();await Promise.resolve();inputs.to.value='20';
  listeners.click({target:{closest:()=>({dataset:{process:'refresh'}})}});await Promise.resolve();
  assert.equal(requests.at(-1).args.toX,20);assert.equal(requests.at(-1).name,'rws_metrics_query');
});
