'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),M=require('../process-model.js');
const scope={datasetRef:{projectId:'p',type:'dataset',id:'D',version:1},split:'validation'},protocol={projectId:'p',type:'protocol',id:'P',version:1};
const line=(id,extra={})=>({id,label:id,metric:'loss',unit:'1',scope,protocol,points:[{step:0,time:0,value:3},{step:1,time:20,value:2},{step:2,time:40,value:1}],...extra});
test('only exact metric, unit, scope and protocol overlay; object key order is irrelevant',()=>{
  const same=line('b',{scope:{split:'validation',datasetRef:scope.datasetRef}}),otherUnit=line('c',{unit:'percent'}),otherDataset=line('d',{scope:{...scope,datasetRef:{...scope.datasetRef,version:2}}}),otherMetric=line('e',{metric:'accuracy'}),otherProtocol=line('f',{protocol:{...protocol,version:2}});
  assert.deepEqual(M.curves([line('a'),same,otherUnit,otherDataset,otherMetric,otherProtocol]).map(g=>g.series.length),[2,1,1,1,1]);
});
test('unrecorded range or unit stays isolated instead of silently matching',()=>{
  for(const extra of [{scope:null},{scope:{}},{scope:'unknown'},{scope:{known:false}},{unit:''},{metric:null}]){const result=M.curves([line('a',extra),line('b',extra)]);assert.equal(result.length,2);assert.ok(result.every(g=>!g.comparable));}
});
test('missing values and unknown coordinate break lines without zero imputation or mutation',()=>{
  const source=line('a',{points:[{step:0,time:0,value:0},{step:1,time:1,value:null},{step:2,time:2,value:4},{step:3,time:3,value:0,status:'missing'},{step:4,time:null,value:2}]}),before=JSON.stringify(source),step=M.curves([source],'step')[0].series[0],time=M.curves([source],'time')[0].series[0];
  assert.deepEqual(step.segments.map(s=>s.map(p=>p.y)),[[0],[4],[2]]);assert.deepEqual(time.segments.map(s=>s.map(p=>p.y)),[[0],[4]]);assert.equal(step.total,5);assert.equal(step.valid,3);assert.equal(JSON.stringify(source),before);assert.deepEqual(M.extent([step]),{xmin:0,xmax:4,ymin:0,ymax:4});
});
test('repeated steps and resumed counters are retained as distinct points',()=>{const data=line('a',{points:[{step:0,value:2},{step:1,value:1},{step:1,value:1.5},{step:0,value:4}]});assert.deepEqual(M.curves([data])[0].series[0].segments.map(s=>s.length),[2,1,1]);});
test('metric tables require a recorded protocol and keep missing distinct from zero',()=>{
  const rows=[line('a',{value:0}),line('b',{value:null,status:'missing'}),line('c',{value:8,protocol:null}),line('d',{value:9,protocol:null})],result=M.metricGroups(rows);
  assert.deepEqual(result.map(g=>g.rows.length),[2,1,1]);assert.equal(result[0].rows[0].displayValue,0);assert.equal(result[0].rows[0].missing,false);assert.equal(result[0].rows[1].displayValue,null);assert.equal(result[0].rows[1].missing,true);assert.deepEqual(result[1].missing,['protocol']);
});
const ref=(type,id,version=1)=>({projectId:'p',type,id,version});
const tracked=(id,extra={})=>({runRef:ref('run',id),metricId:'loss',name:'Loss',unit:'1',axis:'step',scope:'run',split:'train',sampleId:null,definitionRef:ref('spec','training'),datasetRef:ref('dataset','D'),sampleSelection:{sampleIds:['b','a']},points:[{x:0,value:1,sequence:1},{x:1,value:null,reason:'missing',sequence:2},{x:2,value:.5,sequence:3}],...extra});
test('tracked streams group only matching definitions and input selection; missing data identity stays separate',()=>{
  const response={series:[tracked('a'),tracked('b',{sampleSelection:{sampleIds:['a','b']}}),tracked('c',{sampleSelection:{sampleIds:['a']}}),tracked('d',{axis:'epoch'}),tracked('e',{datasetRef:null}),tracked('f',{datasetRef:null})]};
  const groups=M.curves(M.trackedLines(response));assert.deepEqual(groups.map(g=>g.series.length),[2,1,1,1,1]);assert.deepEqual(groups[0].series[0].segments.map(s=>s.length),[1,1]);
});
test('frozen curves never read later stream points and preserve the sampled range',()=>{
  const source={kind:'metric-history-snapshot',throughSequence:3,series:[tracked('a')]};
  const record={ref:ref('artifact','snapshot'),raw:{title:'Frozen',source}};
  const before=JSON.stringify(record),lines=M.frozenLines(record);assert.equal(lines[0].live,false);assert.equal(lines[0].points.length,3);assert.equal(lines[0].artifactRef.id,'snapshot');assert.equal(JSON.stringify(record),before);
  const live={series:[tracked('a',{points:[{x:40,value:.1,sequence:4}]})]};assert.equal(M.trackedLines(live)[0].points[0].step,40);assert.equal(M.frozenLines(record)[0].points.at(-1).step,2);
});
test('freeze pins exact observed watermark and refuses partially loaded queries',()=>{
  const runRef=ref('run','a'),response={series:[tracked('a')],throughSequence:3,truncated:false};
  assert.deepEqual(M.freezeRequest(response,runRef,{metricIds:['loss'],fromX:0,toX:2}),{runRef,throughSequence:3,metricIds:['loss'],fromX:0,toX:2});
  for(const bad of [{...response,truncated:true},{...response,offset:1},{...response,throughSequence:null},{...response,series:[]}])assert.throws(()=>M.freezeRequest(bad,runRef));
});
test('time axis requires actual timestamps; evaluation missing values stay distinct from zero',()=>{
  const lines=M.trackedLines({series:[tracked('a')]});assert.equal(M.curves(lines,'time')[0].series[0].valid,0);
  const evaluations=[{ref:ref('evaluation','ev'),raw:{title:'Eval',protocolRef:ref('protocol','P'),datasetRef:ref('dataset','D'),results:[{kind:'metric',name:'error',unit:'1',value:0},{kind:'metric',name:'error',unit:'1',value:null,status:'missing'}]}}];
  assert.deepEqual(M.metricGroups(M.evaluationMetrics(evaluations))[0].rows.map(r=>r.displayValue),[0,null]);
});
