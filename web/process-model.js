/* Display-only comparison rules. Process streams become evidence only after freezing. */
(function(root){
  'use strict';
  const stable=value=>JSON.stringify(sort(value));
  function sort(value){if(Array.isArray(value))return value.map(sort);if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(key=>[key,sort(value[key])]));return value;}
  function known(value){
    if(value==null||value==='')return false;
    if(typeof value==='string')return !['unknown','unspecified','unrecorded'].includes(value.trim().toLowerCase())&&!!value.trim();
    if(typeof value==='object')return Object.keys(value).length>0&&value.known!==false&&value.kind!=='unknown';
    return false;
  }
  function dimensions(item,{protocol=false}={}){
    const missing=['metric','unit','scope',...(protocol?['protocol']:[])].filter(key=>!known(item[key]));
    return {missing,key:missing.length?null:stable([item.metric,item.unit,item.scope,item.protocol||null,item.axis||null])};
  }
  function groups(items,options={}){
    const result=new Map();
    items.forEach((item,index)=>{
      const d=dimensions(item,options),key=d.key||'unresolved:'+index;
      if(!result.has(key))result.set(key,{key,items:[],comparable:!d.missing.length,missing:d.missing,metric:item.metric,unit:item.unit,scope:item.scope,protocol:item.protocol});
      result.get(key).items.push(item);
    });
    return [...result.values()];
  }
  function curves(items,axis='step'){
    if(!['step','epoch','time'].includes(axis))throw new Error('请选择已登记的步数、轮次或时间坐标。');
    return groups(items,{protocol:true}).map(group=>({...group,axis,series:group.items.map(item=>{
      const segments=[];let segment=[];
      const end=()=>{if(segment.length)segments.push(segment);segment=[];};
      for(const point of item.points||[]){
        const x=point[axis],y=point.value;
        if(!Number.isFinite(x)||!Number.isFinite(y)||point.status&&point.status!=='available'){end();continue;}
        // A reset or repeated x value starts another segment. Never merge runs or average repeats.
        if(segment.length&&x<=segment.at(-1).x)end();
        segment.push({x,y,raw:point});
      }
      end();return {item,segments,valid:segments.reduce((n,points)=>n+points.length,0),total:(item.points||[]).length};
    })}));
  }
  function metricGroups(items){return groups(items,{protocol:true}).map(group=>({...group,rows:group.items.map(item=>({...item,displayValue:Number.isFinite(item.value)?item.value:null,missing:!Number.isFinite(item.value)}))}));}
  function extent(series){
    let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;
    series.forEach(line=>line.segments.forEach(segment=>segment.forEach(({x,y})=>{xmin=Math.min(xmin,x);xmax=Math.max(xmax,x);ymin=Math.min(ymin,y);ymax=Math.max(ymax,y);})));return xmin===Infinity?null:{xmin,xmax,ymin,ymax};
  }
  const refKey=ref=>ref?[ref.projectId,ref.type,ref.id,ref.version]:null;
  function observedScope(series){
    const dataset=series.datasetRef||series.sampleSelection?.datasetRef;
    if(!dataset)return null;
    return {datasetRef:dataset,sampleIds:[...(series.sampleSelection?.sampleIds||[])].sort(),split:series.split||'',kind:series.scope,sampleId:series.sampleId||null};
  }
  function trackedLines(response,label=ref=>ref.id){
    return (response?.series||[]).map(series=>({id:stable([refKey(series.runRef),series.metricId,series.split,series.sampleId]),runRef:series.runRef,
      label:label(series.runRef),metric:series.metricId,name:series.name||series.metricId,unit:series.unit,axis:series.axis,
      scope:observedScope(series),protocol:series.protocolRef||series.definitionRef,split:series.split||'',live:true,
      points:series.points.map(point=>({step:point.x,epoch:point.x,time:point.timestamp?Date.parse(point.timestamp)/1000:series.axis==='time'?point.x:null,value:point.value,sequence:point.sequence,reason:point.reason})),raw:series}));
  }
  function frozenLines(envelope,label){
    const record=envelope.raw||envelope.record||envelope;
    if(record.source?.kind==='metric-history-snapshot')return trackedLines({series:record.source.series||[]},()=>label||record.title).map(line=>({...line,live:false,artifactRef:envelope.ref}));
    const content=record.content;
    if(content?.kind!=='series')return [];
    const x=content.xAxis||content.x||{},y=content.yAxis||content.y||{};
    return [{id:stable(refKey(envelope.ref)),label:label||record.title,metric:content.name||record.semantic||content.label,unit:y.unit||null,
      scope:record.datasetRef?{datasetRef:record.datasetRef,sampleId:record.sampleId||null,taskKey:record.taskKey||null}:null,
      protocol:record.source?.protocolRef||record.source?.definitionRef||null,axis:x.label||'x',live:false,artifactRef:envelope.ref,
      points:(content.points||[]).map(point=>({step:Array.isArray(point)?point[0]:point.x,value:Array.isArray(point)?point[1]:point.y}))}];
  }
  function evaluationMetrics(evaluations){
    return evaluations.flatMap(e=>{const record=e.raw||e.record||e;return (record.results||[]).filter(r=>r.kind==='metric').map((result,index)=>({
      id:stable([refKey(e.ref),index]),evaluationRef:e.ref,label:e.title||record.title,metric:result.metricId||result.name,unit:result.unit,
      protocol:record.protocolRef,scope:record.datasetRef?{datasetRef:record.datasetRef,sampleId:result.sampleId||null,sampleIds:[...(result.sampleIds||[])].sort(),aggregation:result.aggregation||null}:null,
      value:result.value,status:result.status,reason:result.reason,raw:result}));});
  }
  function artifactMetrics(artifacts){
    return artifacts.flatMap(a=>{const record=a.raw||a.record||a,result=record.content;if(result?.kind!=='metric')return [];
      return [{id:stable(refKey(a.ref)),artifactRef:a.ref,label:a.title||record.title,metric:result.metricId||result.name,unit:result.unit,
        protocol:record.source?.protocolRef||record.source?.definitionRef||null,
        scope:record.datasetRef?{datasetRef:record.datasetRef,sampleId:record.sampleId||null,taskKey:record.taskKey||null}:null,
        value:result.value,status:result.status,reason:result.reason,raw:result}];});
  }
  function freezeRequest(response,runRef,filters={}){
    if(!Number.isInteger(response?.throughSequence)||response.truncated||response.offset>0)throw new Error('请先完整读取选定区间；缩小范围后再固定证据。');
    if(!(response.series||[]).some(s=>stable(refKey(s.runRef))===stable(refKey(runRef))&&s.points.length))throw new Error('该运行没有当前查询范围内的数据点。');
    return {runRef,throughSequence:response.throughSequence,...(filters.metricIds?.length?{metricIds:filters.metricIds}:{}),...Object.fromEntries(['fromX','toX'].filter(k=>filters[k]!==undefined).map(k=>[k,filters[k]]))};
  }
  const api={stable,known,dimensions,groups,curves,metricGroups,extent,trackedLines,frozenLines,evaluationMetrics,artifactMetrics,freezeRequest};root.RWSProcessModel=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
