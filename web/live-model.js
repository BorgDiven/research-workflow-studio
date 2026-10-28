/* Canonical, versioned server records projected into the existing canvas. */
(function(root){
  'use strict';
  const groups={research:'hypotheses',experiment:'experiments',spec:'specs',amendment:'amendments',code:'codes',run:'runs',artifact:'artifacts',protocol:'protocols',dataset:'datasets',evaluation:'evaluations',comparison:'comparisons',analysis:'analyses',report:'reports',conversation:'conversations',proposal:'proposals',usage:'usages',server:'servers',repository:'repositories',environment:'environments',operation:'operations'};
  const statusNames={planned:'计划中',running:'运行中',completed:'已完成',failed:'失败',partial:'部分完成',missing:'缺失',undefined:'未定义',available:'可用',unavailable:'不可用',unknown:'位置未知'};
  const researchKinds={exploration:'探索',hypothesis:'假设验证',reproduction:'复现'},implementationRoles={implementation:'研究实现',control:'对照',diagnostic:'诊断'};
  const judgmentLabel=r=>r?.hypothesis?(typeof r.judgment==='string'?r.judgment:r.judgment?.label)||'待判断':null;
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
      if(ref.type==='research')Object.assign(row,{parents:ids(r.parentRefs),kindLabel:researchKinds[r.kind]||'研究',judgmentLabel:judgmentLabel(r),kind:r.kind||'hypothesis',stage:r.stage||'idea',plannedActivities:r.plannedActivities||[],experimentIds:[]});
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
    out.experiments=latestLoaded(out.experiments);out.runs=latestLoaded(out.runs);out.operations=latestLoaded(out.operations);
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
    out.experiments.forEach(e=>{e.stage=out.hypotheses.find(h=>h.id===e.hypothesisId)?.stage||'idea';e.members=out.usages.filter(u=>u.experimentId===e.id&&u.isCurrent&&!u.revoked&&!u.removed&&u.status!=='revoked').map(u=>{const runIds=[...new Set(out.artifacts.filter(a=>u.artifactIds.includes(a.id)).map(a=>a.runId).filter(Boolean))];return {...u,runIds,runId:runIds.length===1?runIds[0]:null};});});
    return out;
  }
  function find(data,id){for(const g of Object.values(groups)){const row=data[g]?.find(x=>x.id===id);if(row)return row;}return null;}
  function label(data,ref){const e=data.envelopes[key(ref)];return e?.effectiveRecord?.title||e?.record.title||ref?.id||'未登记';}
  // Purpose links are declarations. Actual use is resolved only from execution
  // and explicit evidence references, never from matching titles or samples.
  function researchCodeRelations(data,research,{experiment=null}={}){
    if(!research?.ref)return [];
    const result=new Map(),lookup=ref=>data.envelopes[key(ref)],record=e=>e?.effectiveRecord||e?.record;
    const experiments=data.experiments.filter(e=>e.isCurrent&&!e.isExternal&&sameRecord(e.raw.researchRef,research.ref)&&(!experiment||sameRecord(e.ref,experiment.ref)));
    const inScope=ref=>experiments.some(e=>sameRecord(e.ref,ref));
    function add(targetRef,fact){
      if(!targetRef||!['code','spec'].includes(targetRef.type))return;
      const id=key(targetRef),env=lookup(targetRef),value=record(env);
      if(!result.has(id))result.set(id,{id,targetRef:clone(targetRef),title:value?.title||targetRef.id,kind:value?.kind,available:!!env,facts:[]});
      const row=result.get(id),signature=JSON.stringify(fact);if(!row.facts.some(f=>JSON.stringify(f)===signature))row.facts.push(fact);
    }
    for(const link of experiment?[]:research.raw.implementationLinks||[]){
      const fact={kind:'declared',role:link.role,note:link.note||'',targetRef:clone(link.targetRef)};
      add(link.targetRef,fact);
      if(link.targetRef.type==='spec')data.codes.filter(c=>key(c.raw.specRef)===key(link.targetRef)).forEach(c=>add(c.ref,{...fact,viaSpecRef:clone(link.targetRef)}));
    }
    function executionFor(ref){const groups={run:'runs',evaluation:'evaluations',analysis:'analyses',report:'reports'};return (data[groups[ref?.type]]||[]).find(row=>sameRecord(row.ref,ref));}
    function trace(ref,kind,sourceRef,resolve=lookup,seen=new Set()){
      if(!ref||seen.has(key(ref)))return;seen.add(key(ref));const env=resolve(ref),r=record(env);if(!r)return;
      const relationKind=kind==='planned-input'?'planned-input':kind==='planned'||r.status==='planned'?'planned':kind;
      const codeRef=r.codeRef||r.generatorCodeRef;
      if(codeRef){const ex=executionFor(ref);add(codeRef,{kind:relationKind,sourceRef:clone(sourceRef||ref),executionRef:clone(ref),execution:ex?{type:ref.type,id:ex.id}:null,status:r.status||null});}
      // Read the producer exactly; browsing may select a later status revision.
      if(ref.type==='artifact')trace(r.producerRef,relationKind,sourceRef||ref,resolve,seen);
      const inputs=[...(r.inputRefs||[]),...(r.analysisRefs||[]),...(r.evaluationRefs||[]),...(r.comparisonRefs||[]),r.runRef,r.generatorRunRef].filter(Boolean);
      inputs.forEach(input=>trace(input,relationKind==='planned'||relationKind==='planned-input'?'planned-input':'reused',sourceRef||ref,resolve,seen));
    }
    data.runs.filter(r=>inScope(r.raw.experimentRef)).forEach(r=>trace(r.ref,r.raw.status==='planned'?'planned':'used',r.ref));
    data.usages.filter(u=>u.isCurrent&&!u.isExternal&&!u.revoked&&!u.removed&&u.raw.status!=='revoked'&&inScope(u.raw.experimentRef)).forEach(u=>(u.raw.artifactRefs||[]).forEach(ref=>trace(ref,'reused',u.ref)));
    data.evaluations.filter(e=>e.isCurrent&&!e.isExternal&&inScope(e.raw.experimentRef)).forEach(e=>trace(e.ref,'used',e.ref));
    data.analyses.filter(a=>a.isCurrent&&!a.isExternal&&(a.raw.experimentRefs||[]).some(inScope)).forEach(a=>trace(a.ref,'used',a.ref));
    data.reports.filter(r=>r.isCurrent&&!r.isExternal).forEach(report=>{
      const evidence=reportEvidence(data,report),direct=!evidence.bound.length&&!experiment&&(report.raw.researchRefs||[]).some(ref=>sameRecord(ref,research.ref));
      if(direct||experiments.some(e=>reportMatch(evidence,e)))trace(report.ref,'used',report.ref,evidence.lookup);
    });
    return [...result.values()];
  }
  function researchForCode(data,code){return data.hypotheses.map(research=>({research,relation:researchCodeRelations(data,research).find(link=>key(link.targetRef)===key(code?.ref))})).filter(item=>item.relation);}
  function relationLabels(link){return [...new Set((link?.facts||[]).map(f=>f.kind==='declared'?'计划用途 · '+(implementationRoles[f.role]||f.role):f.kind==='planned'?'运行计划':f.kind==='planned-input'?'计划输入':f.kind==='reused'?'引用证据':'执行记录'))];}
  function relatedExecution(link){return link?.facts.find(f=>f.kind==='used'&&f.execution)?.execution||link?.facts.find(f=>f.execution)?.execution||null;}
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

  function reportEvidence(data,report){
    const frozen=new Map((report.raw.snapshot?.records||[]).map(e=>[key(e.ref),e])),lookup=ref=>key(ref)===key(report.ref)?{ref:report.ref,record:report.raw}:frozen.get(key(ref))||(!report.raw.snapshot?data.envelopes[key(ref)]:null),bound=[],artifacts=new Set(),seen=new Set();
    const visit=ref=>{if(!ref||seen.has(key(ref)))return;seen.add(key(ref));if(ref.type==='experiment'){bound.push(ref);return;}if(ref.type==='artifact'){artifacts.add(key(ref));return;}const e=lookup(ref);if(!e)return;const r=e.effectiveRecord||e.record;
      if(r.experimentRef){bound.push(r.experimentRef);return;}if(r.experimentRefs?.length){bound.push(...r.experimentRefs);return;}
      [r.runRef,...(r.analysisRefs||[]),...(r.evaluationRefs||[]),...(r.inputRefs||[]),...(r.comparisonRefs||[])].filter(Boolean).forEach(visit);
    };
    [...(report.raw.analysisRefs||[]),...(report.raw.evaluationRefs||[]),...(report.raw.inputRefs||[]),...(report.raw.comparisonRefs||[])].forEach(visit);
    return {bound,artifacts,lookup};
  }
  function reportMatch(evidence,experiment){
    const used=new Set((experiment.members||[]).flatMap(m=>m.artifactIds));
    return evidence.bound.length?(evidence.bound.some(ref=>sameRecord(ref,experiment.ref))?2:0):[...evidence.artifacts].some(id=>used.has(id))?1:0;
  }
  function reportsForExperiment(data,experiment){
    if(!experiment?.ref)return [];
    const matching=[];
    for(const report of data.reports.filter(r=>r.isCurrent&&!r.isExternal)){const score=reportMatch(reportEvidence(data,report),experiment);if(score)matching.push({report,score});}
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

  const api={groups,key,sameRecord,empty,project,find,label,esc,clone,statusNames,researchKinds,implementationRoles,judgmentLabel,researchCodeRelations,researchForCode,relationLabels,relatedExecution,safeURL,pageWindow,outputGroups,materialCandidates,conditionLabel,fitStageWidths,reportsForExperiment};root.RWSAdapter=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
