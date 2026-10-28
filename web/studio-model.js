/* Pure display helpers; no fixtures or browser-authoritative persistence. */
(function(root){
  'use strict';
  const fieldNames={goal:'目标与挑战',foundations:'模型、数据与基线',approach:'当前研究路线',resources:'实验与评估约定',consensus:'已确认的项目认识'},fields=Object.keys(fieldNames),stageNames={idea:'研究探索',formal:'正式实验',ablation:'消融'};
  const current=p=>p?.versions?.at(-1)||{revision:0,fields:Object.fromEntries(fields.map(k=>[k,'']))};
  const changed=p=>p?.draft?fields.filter(k=>p.draft.fields[k]!==current(p).fields[k]):[];
  const stageText=p=>(p.activeStages||[]).map(k=>stageNames[k]).join(' · ')||(p.stagesConfirmedAt?'暂不指定推进阶段':'推进阶段未确认');
  function projectSummary(p,d){
    const local=d.projectId===p.id,research=local?d.hypotheses.filter(x=>x.isCurrent&&!x.isExternal):[],runs=local?d.runs.filter(x=>x.isCurrent&&!x.isExternal):[],usages=local?d.usages.filter(x=>x.isCurrent&&!x.revoked&&!x.removed):[];
    const summary=p.summary||{},researchCount=summary.researchCount??research.length,completed=summary.completedRunCount??runs.filter(r=>r.raw.status==='completed').length,planned=summary.plannedExperimentCount??(local?d.experiments.filter(e=>e.isCurrent&&!e.isExternal&&e.raw.status==='planned').length:0),evaluationCount=summary.evaluationCount??(local?d.evaluations.filter(e=>e.isCurrent&&!e.isExternal).length:0),runStates=['planned','running','partial','failed'].map(status=>({status,count:runs.filter(r=>r.raw.status===status).length})).filter(x=>x.count).map(x=>x.count+' 次'+({planned:'运行计划',running:'运行进行中',partial:'部分完成',failed:'失败'}[x.status]));
    const known=local||!!p.summary,progressText=known?`${researchCount} 项研究 · ${completed} 次运行已完成 · ${evaluationCount} 份评估${local?' · '+usages.length+' 条引用':''}`:'打开项目查看已登记记录';
    return {goal:current(p).fields.goal||'尚未填写项目目的',stageText:stageText(p),progressText,pendingText:known?([planned?`${planned} 项实验计划待开展`:'',...runStates].filter(Boolean).join(' · ')||(researchCount?'暂无其他已登记待办':'登记首个研究问题')):'',hasResearch:researchCount>0,counts:{research:researchCount,completedRuns:completed,plannedExperiments:planned,evaluationRecords:evaluationCount,ownArtifacts:summary.artifactCount??null}};
  }

  function parentRefsForSelection(selected,previous=[],projectId,selfId=null){
    if(selected===undefined)return JSON.parse(JSON.stringify(previous));
    if(selected.some(ref=>ref.projectId!==projectId||ref.type!=='research'||ref.id===selfId))throw new Error('父研究必须来自当前项目，且不能选择自身。');
    const identity=ref=>ref.projectId+'|'+ref.type+'|'+ref.id,ids=new Set(selected.map(identity));
    if(ids.size!==selected.length)throw new Error('父研究不能重复选择。');
    if(ids.size===previous.length&&previous.every(ref=>ids.has(identity(ref))))return JSON.parse(JSON.stringify(previous));
    return selected.map(ref=>JSON.parse(JSON.stringify(previous.find(old=>identity(old)===identity(ref))||ref)));
  }
  function implementationLinksForSelection(selected,previous=[]){
    const links=selected===undefined?previous:selected;
    if(!Array.isArray(links)||links.length>32)throw new Error('每项研究最多关联 32 项实现用途。');
    const seen=new Set();
    return links.map(link=>{const ref=link?.targetRef;if(!ref||!['spec','code'].includes(ref.type)||!ref.projectId||!ref.id||!Number.isInteger(ref.version)||ref.version<1)throw new Error('请选择代码或规范的固定版本。');if(!['implementation','control','diagnostic'].includes(link.role))throw new Error('请选择有效的实现用途。');const identity=JSON.stringify([ref.projectId,ref.type,ref.id,ref.version,link.role]);if(seen.has(identity))throw new Error('相同版本与用途不能重复关联。');seen.add(identity);if(link.note!==undefined&&(typeof link.note!=='string'||link.note.length>1000))throw new Error('用途说明最多 1000 字。');return JSON.parse(JSON.stringify(link));});
  }
  function researchRecord(values,existing=null,projectId=null,selectedParentRefs=undefined,selectedImplementationLinks=undefined){
    const read=key=>String(values[key]??'').trim(),kind=read('kind'),hypothesis=read('hypothesis'),label=read('judgment');
    if(existing&&(existing.ref.projectId!==projectId||existing.ref.type!=='research'))throw new Error('只能编辑当前项目的研究条目。');
    if(!read('title')||!read('question'))throw new Error('请填写研究标题和要回答的问题。');
    if(!['exploration','hypothesis','reproduction'].includes(kind)||!Object.hasOwn(stageNames,read('stage')))throw new Error('研究类型或阶段无效。');
    if(kind==='hypothesis'&&!hypothesis)throw new Error('可检验假设需要写明具体的待检验判断。');
    if(label&&!hypothesis)throw new Error('请先填写明确的待检验假设，再记录支持或反驳判断。');
    const previous=existing?.record||{},previousLabel=typeof previous.judgment==='string'?previous.judgment:previous.judgment?.label;
    if(label&&!['支持','反驳','证据不足',previousLabel].includes(label))throw new Error('请选择有效的研究判断。');
    const record={title:read('title'),question:read('question'),kind,stage:read('stage'),parentRefs:parentRefsForSelection(selectedParentRefs,previous.parentRefs||[],projectId,existing?.ref.id)};
    if(selectedImplementationLinks!==undefined||previous.implementationLinks!==undefined)record.implementationLinks=implementationLinksForSelection(selectedImplementationLinks,previous.implementationLinks||[]);
    if(existing)record.id=existing.ref.id;
    if(previous.status!==undefined)record.status=previous.status;
    if(hypothesis)record.hypothesis=hypothesis;else if(existing&&previous.hypothesis!==undefined)record.hypothesis=null;
    if(label){record.judgment={label,summary:read('judgmentSummary'),limitations:read('judgmentLimitations').split('\n').map(x=>x.trim()).filter(Boolean)};if(previous.judgment?.evidenceRefs)record.judgment.evidenceRefs=JSON.parse(JSON.stringify(previous.judgment.evidenceRefs));}else if(existing&&previous.judgment!==undefined)record.judgment=null;
    return record;
  }
  function contextText(c){
    const ref=r=>r?(r.projectId!==c.projectId?'['+r.projectId+'] ':'')+r.type+'/'+r.id+'@r'+r.version:'未选择';
    const judgement=c.currentResearch?.judgment,hasHypothesis=c.currentResearch?.hasHypothesis??!!(c.currentResearch?.hypothesis||c.currentResearch?.kind==='hypothesis'||judgement),label=typeof judgement==='string'?judgement:judgement?.label||'尚未判断';
    const objects=(c.objects||[]).map(o=>'- '+ref(o.ref)+' · '+o.title+[['状态',o.status],['代码',o.codeRef?ref(o.codeRef):null],['生产者',o.producerRef?ref(o.producerRef):null],['样本',o.sampleId]].filter(([,v])=>v).map(([k,v])=>'；'+k+'：'+v).join(''));
    const facts=items=>(items||[]).map(item=>'- '+[item.title,item.reason,item.status?({'completed':'已完成','planned':'计划中','running':'进行中','failed':'失败','partial':'部分完成'}[item.status]||item.status):null,item.ref?'('+ref(item.ref)+')':null].filter(Boolean).join(' · '));
    return ['项目：'+c.projectName+'（projectId='+c.projectId+'）','本次上下文基础：v'+c.foundation.revision+(c.latestFoundationRevision&&c.latestFoundationRevision!==c.foundation.revision?'；当前项目基础 v'+c.latestFoundationRevision:''),...fields.filter(k=>c.foundation.fields[k]).map(k=>fieldNames[k]+'：'+c.foundation.fields[k]),'', '当前位置：'+(stageNames[c.position.stage]||'项目准备'),'研究：'+ref(c.position.researchRef),'实验：'+ref(c.position.experimentRef),c.researchVersionNotice||c.researchBindingNote||'',c.currentResearch?'当前研究：'+ref(c.currentResearch.ref)+' · '+c.currentResearch.title:'',hasHypothesis?'当前人工判断：'+label+(judgement?.summary?'；依据：'+judgement.summary:''):'',' ',...(c.declaredImplementations?.length?['计划用途（不代表执行）：',...c.declaredImplementations.map(link=>'- '+link.researchTitle+'（'+ref(link.researchRef)+'；'+(link.researchVersionRole==='bound'?'实验绑定版本':'当前版本')+'） → '+link.title+'（'+ref(link.targetRef)+'）；'+(link.roleLabel||link.role)+(link.note?'；'+link.note:'')),...(c.declaredImplementationsTruncated?['更多用途按研究固定版本读取。']:[])]:[]),'','已登记对象：',...objects,c.objectsTruncated?'其余 '+Math.max(0,c.objectCount-c.objects.length)+' 个对象按需读取。':'','','已完成：',...(c.completed?.length?facts(c.completed):['暂无已登记完成记录']),'待完成：',...(c.pending?.length?facts(c.pending):['暂无已登记待办']),'可选下一步：',...(c.suggestedActions||[]).map(s=>'- '+s.label+'：'+s.reason+'；操作 '+s.operation+(s.targetRef?' → '+ref(s.targetRef):'')),'','需要完整记录时调用 rws_record_get；ref 使用上述 projectId、type、id、version。未注明来源项目的对象均属于本项目。',c.notice].filter(line=>line!==undefined&&line!==null).join('\n');
  }

  const api={fieldNames,fields,stageNames,current,changed,stageText,projectSummary,contextText,researchRecord,parentRefsForSelection,implementationLinksForSelection};root.RWSModel=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
