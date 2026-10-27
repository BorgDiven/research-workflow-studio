/* Comparison identity is independent of display names and execution batches. */
(function(root){
  'use strict';
  const stable=value=>JSON.stringify(sort(value));
  function sort(value){if(Array.isArray(value))return value.map(sort);if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(k=>[k,sort(value[k])]));return value;}
  const reference=ref=>ref?[ref.projectId,ref.type,ref.id,ref.version]:null;
  const semanticNames={'final-image':'最终图像','clean-estimate':'预测干净图像','velocity-field':'速度场','input-image':'输入图像',final_image:'最终图像',predicted_clean:'预测干净图像',predicted_clean_image:'预测干净图像',velocity:'速度场',velocity_field:'速度场',attention_map:'注意力图',loss_curve:'损失曲线',metric:'评估指标',metrics:'评估指标',image:'图像',series:'曲线',table:'表格',attachment:'附件','image-set':'图像'};
  function describe(artifact,data){
    const r=artifact.raw||artifact,producer=data.envelopes?.[data.key?.(r.producerRef)]||null;
    const run=data.runs?.find(x=>same(x.ref,r.producerRef)),runRecord=producer?.effectiveRecord||producer?.record||run?.raw||{},codeRef=runRecord.codeRef,code=data.codes?.find(c=>sameExact(c.ref,codeRef));
    // An explicit artifact configuration (even {}) is the actual recorded
    // configuration; a producer may describe a multi-configuration group.
    const actualConfig=Object.hasOwn(r,'config')?r.config:runRecord.config;
    const dataset=r.datasetRef||null,sample=r.sampleId??null,task=r.taskKey??actualConfig?.prompt??null,inputIdentity=r.inputRefs?.length?r.inputRefs.map(reference).sort((a,b)=>stable(a).localeCompare(stable(b))):null;
    // Legacy sample labels are local identities; they are never joined across projects.
    const identity=sample===null?['unresolved',reference(artifact.ref)]:[dataset?reference(dataset):inputIdentity?['inputs',inputIdentity]:['project',artifact.ref.projectId],sample,task];
    const config={...(actualConfig||{})};
    for(const k of ['sampleId','sample_id','case','case_id','prompt','input','input_path','output','output_path','taskKey','task_key'])delete config[k];
    // Only a declared task identity proves these values describe the case.
    // Unequal conditioning remains a real comparison condition.
    for(const k of ['target_positive','instruction','edit_instruction','target_prompt'])if(typeof r.taskKey==='string'&&config[k]===r.taskKey)delete config[k];
    const observation=r.observation||{},semantic=r.semantic||r.content?.kind||r.kind||'attachment';
    return {artifact,id:artifact.id,ref:artifact.ref,caseKey:stable(identity),sampleId:sample,taskKey:task,caseLabel:sample===null?'样本未登记':String(sample)+(task?' · '+task:''),caseSource:dataset?dataset.id+' · r'+dataset.version:artifact.sourceProject||artifact.ref.projectId,unresolved:sample===null,semantic,config,observation,observationKey:stable(observation),codeRef,codeId:code?.id||stable(reference(codeRef)),codeLabel:code?.title||'实现未核定',codeVersion:code?.version||'',code,methodKey:stable(reference(codeRef)||['unresolved',reference(r.producerRef)||reference(artifact.ref)])};
  }
  function same(a,b){return !!a&&!!b&&a.projectId===b.projectId&&a.type===b.type&&a.id===b.id;}
  function sameExact(a,b){return same(a,b)&&a.version===b.version;}
  function observationLabel(o){return [o.label,o.step!==undefined?'step '+o.step:null,o.time!==undefined?'t = '+o.time:null].filter(Boolean).join(' · ')||'未标记时刻';}
  function fields(items){return [...new Set(items.flatMap(x=>Object.keys(x.config)))].sort();}
  function options(items,getKey,getLabel){const map=new Map();items.forEach(x=>{const key=getKey(x);if(!map.has(key))map.set(key,{key,label:getLabel(x)});});return [...map.values()];}
  function matrix(items,view={}){
    const filter=view.filters||{},config=filter.config||{},axis=view.axis||'implementation';
    const scope=items.filter(x=>(!view.semantics?.length||view.semantics.includes(x.semantic))&&(!filter.codeIds?.length||filter.codeIds.includes(x.codeId))&&Object.entries(config).every(([k,v])=>stable(x.config[k])===stable(v))&&Object.entries(view.observation||{}).every(([k,v])=>x.observation[k]===v));
    let kept=scope.filter(x=>(!view.sampleIds?.length||view.sampleIds.includes(x.sampleId))&&(!filter.caseKeys?.length||filter.caseKeys.includes(x.caseKey)));
    if(view.mode==='single'){const selected=filter.caseKeys?.[0]||kept[0]?.caseKey;kept=kept.filter(x=>x.caseKey===selected);}
    const rows=options(kept,x=>x.caseKey,x=>x.caseLabel).map(row=>({...row,item:kept.find(x=>x.caseKey===row.key)})),columns=new Map(),cells=new Map(),visible=new Set(kept);
    // Case selection filters rows; comparable columns come from the same filtered material scope.
    for(const item of scope){
      // Every non-case condition remains in the column identity. A changed setting
      // cannot silently become a repeat of a different setting.
      const columnKey=stable([item.methodKey,item.config,item.observation,item.semantic]);
      const title=axis==='observation'?observationLabel(item.observation):axis.startsWith('config:')?axis.slice(7)+' = '+String(item.config[axis.slice(7)]??'未登记'):item.codeLabel;
      if(!columns.has(columnKey))columns.set(columnKey,{key:columnKey,title,item});
      if(!visible.has(item))continue;
      const cellKey=stable([item.caseKey,columnKey]);if(!cells.has(cellKey))cells.set(cellKey,[]);cells.get(cellKey).push(item);
    }
    const ordered=[...columns.values()];if(axis==='observation')ordered.sort((a,b)=>(a.item.observation.step??a.item.observation.time??Infinity)-(b.item.observation.step??b.item.observation.time??Infinity));else if(axis.startsWith('config:')){const key=axis.slice(7);ordered.sort((a,b)=>String(a.item.config[key]??'').localeCompare(String(b.item.config[key]??''),undefined,{numeric:true}));}
    return {items:kept,rows,columns:ordered,cells,cellKey:(row,column)=>stable([row,column])};
  }
  function selectedCell(items,chosen){if(!items?.length)return null;if(items.length===1)return items[0];return items.find(x=>x.id===chosen)||null;}
  function selectedEvidence(matrix,selections={},selectedIds=[]){const wanted=new Set(selectedIds),all=[];matrix.cells.forEach((items,key)=>{const selected=selectedCell(items,selections[key]);if(selected&&wanted.has(selected.id))all.push(selected);});return all;}
  function coverage(matrix,selected){const cases=new Set(selected.map(x=>x.caseKey)),expected=new Set([...matrix.rows.map(x=>x.key),...cases]);return {expected:expected.size,observed:cases.size,missingSampleIds:matrix.rows.filter(x=>!cases.has(x.key)).map(x=>x.item.sampleId??x.item.caseLabel)};}
  const api={stable,reference,describe,semanticNames,observationLabel,fields,options,matrix,selectedCell,selectedEvidence,coverage,sameExact};root.RWSResultsModel=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
