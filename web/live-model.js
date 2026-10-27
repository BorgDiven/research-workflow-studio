/* Canonical, versioned server records projected into the existing canvas. */
(function(root){
  'use strict';
  const groups={research:'hypotheses',experiment:'experiments',spec:'specs',amendment:'amendments',code:'codes',run:'runs',artifact:'artifacts',protocol:'protocols',dataset:'datasets',evaluation:'evaluations',comparison:'comparisons',analysis:'analyses',report:'reports',conversation:'conversations',proposal:'proposals',usage:'usages'};
  const statusNames={planned:'计划中',running:'运行中',completed:'已完成',failed:'失败',partial:'部分完成',missing:'缺失',undefined:'未定义',available:'可用',unavailable:'不可用',unknown:'位置未知'};
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clone=x=>JSON.parse(JSON.stringify(x));
  function key(ref){if(!ref)return null;return 'ref-'+Array.from(new TextEncoder().encode(JSON.stringify([ref.projectId,ref.type,ref.id,ref.version]))).map(v=>v.toString(16).padStart(2,'0')).join('');}
  const sameRecord=(a,b)=>!!a&&!!b&&a.projectId===b.projectId&&a.type===b.type&&a.id===b.id;
  const empty=()=>({...Object.fromEntries(Object.values(groups).map(g=>[g,[]])),tasks:[],samples:[],meta:{label:'共享后端',isDemo:false},projectId:null,revision:null,envelopes:{},projects:[]});
  function project(snapshot){
    const out=empty(),all=new Map(),own=new Set((snapshot.records||[]).map(e=>key(e.ref)));out.projectId=snapshot.projectId;out.revision=snapshot.revision;out.projects=snapshot.projects||[];
    const p=out.projects.find(p=>p.id===out.projectId);out.meta={label:p?.demo?'合成试装记录':'服务器记录',isDemo:!!p?.demo};
    [...(snapshot.references||[]),...(snapshot.records||[])].forEach(e=>all.set(key(e.ref),e));
    out.envelopes=Object.fromEntries(all);
    const lookup=ref=>all.get(key(ref)), ids=refs=>(refs||[]).map(key), ofType=(refs,type)=>ids((refs||[]).filter(r=>r.type===type));
    for(const [id,env] of all){
      const r=env.effectiveRecord||env.record,ref=env.ref,group=groups[ref.type];if(!group)continue;
      const row={...clone(r),id,ref:clone(ref),displayId:ref.id,recordVersion:ref.version,createdAt:env.createdAt,raw:clone(r),isCurrent:own.has(id),isExternal:ref.projectId!==out.projectId,sourceProject:out.projects.find(p=>p.id===ref.projectId)?.name||ref.projectId,title:r.title||ref.id,status:statusNames[r.status]||r.status||'已登记'};
      if(ref.type==='research')Object.assign(row,{parents:ids(r.parentRefs),status:r.judgment?.label||r.judgment||(r.kind==='exploration'?'开放探索':r.kind==='reproduction'?'待复现':'待人工判断'),kind:r.kind||'hypothesis',stage:r.stage||'idea',plannedActivities:r.plannedActivities||[],experimentIds:[]});
      if(ref.type==='experiment')Object.assign(row,{hypothesisId:key(r.researchRef),protocolId:key(r.protocolRef),members:[],config:r.config||{},fixed:JSON.stringify(r.config||{}),changed:r.title});
      if(ref.type==='code')Object.assign(row,{parentIds:ids(r.parentRefs),parentId:key(r.parentRefs?.[0]),specId:key(r.specRef),amendmentRefs:clone(env.amendmentRefs||[])});
      if(ref.type==='run')Object.assign(row,{codeId:key(r.codeRef),experimentId:key(r.experimentRef),inputIds:ids(r.inputRefs),config:r.config||{},label:r.title});
      if(ref.type==='artifact')Object.assign(row,{runId:key(r.producerRef),config:r.config||{},content:r.content||((r.kind==='image'||r.kind==='image-set')&&r.uri?{kind:'image-set',items:[{uri:r.uri,sampleId:r.sampleId,caption:r.title}]}:r.uri?{kind:'attachment',uri:r.uri,mimeType:r.mimeType||'application/octet-stream'}:null)});
      if(ref.type==='evaluation')Object.assign(row,{codeId:key(r.codeRef),protocolId:key(r.protocolRef),experimentId:key(r.experimentRef),inputArtifactIds:ofType(r.inputRefs,'artifact'),inputIds:ids(r.inputRefs),metrics:[],results:r.results||[]});
      if(ref.type==='analysis')Object.assign(row,{codeId:key(r.codeRef),runId:key(r.runRef),experimentIds:ids(r.experimentRefs),artifactIds:ofType(r.inputRefs,'artifact'),evaluationIds:ofType(r.inputRefs,'evaluation'),inputIds:ids(r.inputRefs),conclusion:r.interpretation||''});
      if(ref.type==='report')Object.assign(row,{analysisIds:ids(r.analysisRefs),evaluationIds:ids(r.evaluationRefs),hypothesisIds:ids(r.researchRefs),inputIds:ids(r.inputRefs),generatorCodeId:key(r.generatorCodeRef),generatorRunId:key(r.generatorRunRef),version:'修订 '+ref.version,summary:r.markdown||'',snapshot:r.snapshot});
      if(ref.type==='usage')Object.assign(row,{experimentId:key(r.experimentRef),artifactIds:ids(r.artifactRefs),role:r.role,label:r.label||r.role});
      out[group].push(row);
    }
    // Versioned status edits do not create another actual experiment or run.
    // Use the newest loaded version for browsing, while every raw ref stays frozen.
    const latestLoaded=rows=>{const logical=new Map();rows.forEach(row=>{const identity=JSON.stringify([row.ref.projectId,row.ref.type,row.ref.id]),previous=logical.get(identity);if(!previous||row.recordVersion>previous.recordVersion)logical.set(identity,row);});return [...logical.values()];};
    out.experiments=latestLoaded(out.experiments);out.runs=latestLoaded(out.runs);
    const experimentId=ref=>out.experiments.find(e=>sameRecord(e.ref,ref))?.id||key(ref);
    const runId=ref=>out.runs.find(r=>sameRecord(r.ref,ref))?.id||key(ref);
    out.usages.forEach(u=>u.experimentId=experimentId(u.raw.experimentRef));
    out.runs.forEach(r=>r.experimentId=experimentId(r.raw.experimentRef));
    out.evaluations.forEach(e=>e.experimentId=experimentId(e.raw.experimentRef));
    out.analyses.forEach(a=>{a.experimentIds=(a.raw.experimentRefs||[]).map(experimentId);a.runId=runId(a.raw.runRef);});
    out.artifacts.forEach(a=>{a.runId=runId(a.raw.producerRef);a.producerVersion=a.raw.producerRef?.version;});
    // The canvas shows one latest card per local research identity. Frozen
    // references remain exact in raw records/readers; presentation does not migrate them.
    out.hypotheses=out.hypotheses.filter(h=>h.isCurrent&&!h.isExternal);
    const currentResearch=ref=>out.hypotheses.find(h=>sameRecord(h.ref,ref));
    out.hypotheses.forEach(h=>{h.parentBindings=(h.raw.parentRefs||[]).map(ref=>({ref,from:currentResearch(ref)?.id||null}));h.parents=h.parentBindings.map(binding=>binding.from).filter(Boolean);});
    out.experiments.forEach(e=>{const h=currentResearch(e.raw.researchRef);e.hypothesisId=h?.id||key(e.raw.researchRef);e.researchVersion=e.raw.researchRef?.version;e.currentResearchVersion=h?.recordVersion;});
    out.hypotheses.forEach(h=>{h.experimentIds=out.experiments.filter(e=>e.hypothesisId===h.id&&e.isCurrent).map(e=>e.id);h.experimentId=h.experimentIds[0]||null;});
    out.experiments.forEach(e=>{e.stage=out.hypotheses.find(h=>h.id===e.hypothesisId)?.stage||'idea';e.members=out.usages.filter(u=>u.experimentId===e.id&&u.isCurrent&&!u.revoked&&!u.removed&&u.status!=='revoked').map(u=>({...u,runId:out.artifacts.find(a=>u.artifactIds.includes(a.id))?.runId||null}));});
    return out;
  }
  function find(data,id){for(const g of Object.values(groups)){const row=data[g]?.find(x=>x.id===id);if(row)return row;}return null;}
  function label(data,ref){const e=data.envelopes[key(ref)];return e?.effectiveRecord?.title||e?.record.title||ref?.id||'未登记';}
  function materialCandidates(snapshot,query='',sample=''){
    if(!snapshot)return [];
    const q=String(query).trim().toLocaleLowerCase();
    return (snapshot.records||[]).filter(e=>{const r=e.effectiveRecord||e.record;return e.ref.type==='artifact'&&e.ref.projectId===snapshot.projectId&&(!sample||r.sampleId===sample)&&(!q||[r.title,r.sampleId,e.ref.id].some(value=>String(value||'').toLocaleLowerCase().includes(q)));});
  }
  function pageWindow(items,index,size){const pages=Math.max(1,Math.ceil(items.length/size)),page=Math.max(0,Math.min(Number.isFinite(index)?index:0,pages-1));return {page,pages,total:items.length,start:page*size,items:items.slice(page*size,(page+1)*size)};}
  function conditionLabel(artifact){
    for(const field of ['condition_id','condition']){const value=artifact.config?.[field];if(typeof value==='string'&&value.trim())return value.trim();if(typeof value==='number'&&Number.isFinite(value))return String(value);}
    return null;
  }
  function outputGroups(artifacts,groupBy='run'){
    const groups=new Map();
    for(const a of artifacts){const kind=a.content?.kind||a.kind,condition=conditionLabel(a),column=groupBy==='condition'?'condition:'+JSON.stringify(condition):a.runId||a.id,sample=a.sampleId??null;
      if(!groups.has(kind))groups.set(kind,{kind,runs:[],samples:[],cells:new Map(),columnLabels:new Map()});const g=groups.get(kind);
      if(!g.columnLabels.has(column)){g.runs.push(column);g.columnLabels.set(column,groupBy==='condition'?(condition??'未登记条件'):column);}if(!g.samples.includes(sample))g.samples.push(sample);
      const cell=JSON.stringify([column,sample]);if(!g.cells.has(cell))g.cells.set(cell,[]);g.cells.get(cell).push(a);
    }
    return [...groups.values()];
  }

  function reportsForExperiment(data,experiment){
    if(!experiment?.ref)return [];
    const used=new Set((experiment.members||[]).flatMap(m=>m.artifactIds)),matching=[];
    for(const report of data.reports.filter(r=>r.isCurrent&&!r.isExternal)){
      const frozen=new Map((report.raw.snapshot?.records||[]).map(e=>[key(e.ref),e])),lookup=ref=>frozen.get(key(ref))||(!report.raw.snapshot?data.envelopes[key(ref)]:null),bound=[],artifacts=new Set(),seen=new Set();
      const visit=ref=>{if(!ref||seen.has(key(ref)))return;seen.add(key(ref));if(ref.type==='experiment'){bound.push(ref);return;}if(ref.type==='artifact'){artifacts.add(key(ref));return;}const e=lookup(ref);if(!e)return;const r=e.record;
        if(r.experimentRef){bound.push(r.experimentRef);return;}if(r.experimentRefs?.length){bound.push(...r.experimentRefs);return;}
        [r.runRef,...(r.analysisRefs||[]),...(r.evaluationRefs||[]),...(r.inputRefs||[])].filter(Boolean).forEach(visit);
      };
      [...(report.raw.analysisRefs||[]),...(report.raw.evaluationRefs||[]),...(report.raw.inputRefs||[])].forEach(visit);
      const score=bound.length?(bound.some(ref=>sameRecord(ref,experiment.ref))?2:0):[...artifacts].some(id=>used.has(id))?1:0;
      if(score)matching.push({report,score});
    }
    return matching.sort((a,b)=>b.score-a.score||String(b.report.createdAt||'').localeCompare(String(a.report.createdAt||''))||b.report.recordVersion-a.report.recordVersion).map(x=>x.report);
  }
  function fitStageWidths(widths,budget,minWidth=172){
    const desired=widths.map(w=>Math.max(minWidth,w));if(desired.reduce((a,b)=>a+b,0)<=budget)return desired;
    const floor=Math.min(minWidth,budget/desired.length),remaining=Math.max(0,budget-floor*desired.length),weights=desired.map(w=>Math.sqrt(Math.max(0,w-floor))),total=weights.reduce((a,b)=>a+b,0);
    return desired.map((w,i)=>floor+(total?remaining*weights[i]/total:remaining/desired.length));
  }
  function safeURL(value){
    if(typeof value!=='string'||!value.trim()||value.includes('\\')||value.startsWith('//'))return null;
    try{const u=new URL(value,'http://localhost/');if(!['http:','https:'].includes(u.protocol))return null;
      if(/^https?:\/\//i.test(value))return value;
      if(/^[a-z][a-z0-9+.-]*:/i.test(value))return null;
      return u.pathname+u.search+u.hash;
    }catch{return null;}
  }

  const api={groups,key,sameRecord,empty,project,find,label,esc,clone,statusNames,safeURL,pageWindow,outputGroups,materialCandidates,conditionLabel,fitStageWidths,reportsForExperiment};root.RWSAdapter=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
