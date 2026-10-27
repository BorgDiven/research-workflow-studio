/* Exact-version readers. Report navigation stays inside its frozen closure. */
(() => {
  'use strict';
  const D=window.RP_DATA,A=window.RWSAdapter,esc=A.esc,frozen=new Map(),scopes=new Map(),scopeFoundations=new Map(),collections=new Map();
  let activeScope=null,collectionNumber=0;
  const names={research:'研究条目',experiment:'实验',spec:'代码块规范',code:'代码版本',run:'运行',artifact:'产物',protocol:'评估约定',dataset:'数据集',evaluation:'评估',comparison:'对比集合',analysis:'分析',report:'报告',conversation:'会话',proposal:'基础建议',usage:'材料引用'};
  const kindNames={hypothesis:'可检验假设',exploration:'开放探索',reproduction:'复现',inference:'推理',training:'训练',evaluation:'评估',analysis:'分析',report:'报告'};
  const empty=text=>`<p class="evidence-empty">${esc(text)}</p>`;
  const section=(title,body)=>`<section class="evidence-section"><h3>${esc(title)}</h3>${body}</section>`;
  const asText=value=>typeof value==='string'?value:JSON.stringify(value,null,2);
  const pre=value=>`<pre class="record-text">${esc(asText(value??''))}</pre>`;
  function env(id,scope=activeScope){if(scope)return scopes.get(scope)?.get(id);const current=D.envelopes[id],cached=frozen.get(id);if(current?.ref.type==='report'&&!current.record.snapshot?.records&&cached?.record.snapshot?.records)return cached;return current||cached;}
  const get=ref=>env(A.key(ref));
  function scoped(scope,fn){const before=activeScope;activeScope=scope;try{return fn();}finally{activeScope=before;}}
  function scopeForReport(id,fromScope=null){
    const report=env(id,fromScope);if(!report||report.ref.type!=='report')return null;
    const snapshot=report.record.snapshot||{},scope='report:'+id;if(snapshot.recordRefs&&!fromScope&&scopes.has(scope))return scope;const map=new Map([[id,report]]);
    if(Array.isArray(snapshot.records))snapshot.records.forEach(e=>{map.set(A.key(e.ref),e);frozen.set(A.key(e.ref),e);});
    else if(Array.isArray(snapshot.recordRefs))snapshot.recordRefs.forEach(ref=>{const e=fromScope?scopes.get(fromScope)?.get(A.key(ref)):null;if(e)map.set(A.key(ref),e);});
    const foundations=new Map((fromScope?scopeFoundations.get(fromScope)||[]:[]).map(x=>[x.projectId+'|'+x.foundation.revision,x]));[...(snapshot.projectFoundations||[]),...(snapshot.foundation?[{projectId:report.ref.projectId,foundation:snapshot.foundation}]:[])].forEach(x=>foundations.set(x.projectId+'|'+x.foundation.revision,x));scopeFoundations.set(scope,[...foundations.values()]);scopes.set(scope,map);frozen.set(id,report);return scope;
  }
  function entries(type){
    if(activeScope)return [...(scopes.get(activeScope)?.values()||[])].filter(e=>e.ref.type===type);
    const group=A.groups[type];return (D[group]||[]).map(row=>env(row.id)).filter(Boolean);
  }
  function refLink(ref,label){
    if(!ref)return '';const e=get(ref),type=ref.type==='research'?'hypothesis':ref.type==='usage'?'link':ref.type;
    return `<button class="evidence-link" data-action="inspect" data-type="${esc(type)}" data-id="${A.key(ref)}" ${!e?'disabled title="此固定快照未包含该记录"':''}>${esc(label||e?.effectiveRecord?.title||e?.record.title||ref.id)} <small>${ref.projectId!==D.projectId?'来源：'+esc(D.projects.find(p=>p.id===ref.projectId)?.name||ref.projectId)+' · ':''}${esc(ref.id)} · r${ref.version}</small></button>`;
  }
  function provenance(ref){const p=D.projects.find(p=>p.id===ref.projectId);return `<div class="canonical-source ${ref.projectId!==D.projectId?'external-source':''}"><strong>${ref.projectId!==D.projectId?'来源项目：':'项目：'}${esc(p?.name||ref.projectId)}</strong><span>${esc(names[ref.type]||ref.type)} · ${esc(ref.id)} · 固定记录 r${ref.version}</span></div>`;}
  function collectionMarkup(token){
    const c=collections.get(token),pages=Math.max(1,Math.ceil(c.items.length/c.size));c.page=Math.max(0,Math.min(c.page,pages-1));
    return scoped(c.scope,()=>`<div class="paged-collection" data-collection="${token}"><div class="paged-content">${c.items.slice(c.page*c.size,(c.page+1)*c.size).map(c.render).join('')}</div>${pages>1?`<div class="collection-pager"><span>${esc(c.label)} · ${c.items.length} 项 · ${c.page+1}/${pages} 页</span><button class="button small" data-collection-page="${token}" data-direction="-1" ${c.page===0?'disabled':''}>上一页</button><button class="button small" data-collection-page="${token}" data-direction="1" ${c.page===pages-1?'disabled':''}>下一页</button></div>`:''}</div>`);
  }
  function batch(items,render,label='记录',size=24){
    if(!items.length)return '';
    if(items.length<=size)return items.map(render).join('');
    const token='collection-'+(++collectionNumber);collections.set(token,{items,render,label,size,page:0,scope:activeScope});return collectionMarkup(token);
  }
  function refs(title,values){const content=values?.length?`<div class="evidence-actions">${batch(values,r=>refLink(r),'固定引用',30)}</div>`:empty(activeScope?'此快照未包含该类记录':'尚未登记');return values?.length>8?`<details class="reference-fold"><summary>${esc(title)} · ${values.length} 个固定版本</summary>${content}</details>`:section(title,content);}
  function facts(items){return `<dl class="evidence-facts">${items.filter(([,value])=>value!==undefined&&value!==null&&value!=='').map(([label,value])=>`<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`).join('')}</dl>`;}
  function readableList(value){return Array.isArray(value)?`<ul class="evidence-list">${value.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:`<p class="record-prose">${esc(value||'尚未登记')}</p>`;}
  function codeSource(record){
    const source=typeof record.source==='object'&&record.source?record.source:{},text=value=>typeof value==='string'?value:JSON.stringify(value),locations=[];
    if(record.repository)locations.push(['登记仓库',text(record.repository)]);
    if(source.repository)locations.push(['历史仓库',text(source.repository)]);
    const list=value=>Array.isArray(value)?value:value?[value]:[];
    list(source.locatedGitRepositories).forEach(path=>locations.push(['历史定位',text(path)]));
    list(source.sourceFiles).forEach(path=>locations.push(['历史源码文件',text(path)]));
    const candidates=[['源码地址',typeof record.source==='string'?record.source:source.uri],['源码地址',source.url],['源码存档',source.archiveUri],['登记仓库',record.repository],['历史仓库',source.repository],['来源清单',source.manifestUri],['来源回执',source.receiptUri]],seen=new Set();
    const links=candidates.flatMap(([label,value])=>{const url=typeof value==='string'&&/^(?:https?:\/\/|\/materials\/|\/assets\/)/i.test(value)?A.safeURL(value):null;if(!url||!/^https?:\/\//i.test(url)&&!/^\/(?:materials|assets)\//.test(url)||seen.has(url))return [];seen.add(url);return [{label,url}];});
    return {description:record.purpose||record.description||source.description||'',descriptionLabel:record.purpose?'实现用途':'登记说明',commit:record.commit||source.commit||'',commitLabel:record.commit?'Git commit':'历史来源 commit',modulePath:record.modulePath||'',entrypoint:record.entrypoint||'',locations,links};
  }
  function codeSourceMarkup(record){
    const source=codeSource(record);
    return (source.description?section(source.descriptionLabel,readableList(source.description)):'')+facts([['代码类别',kindNames[record.kind]||record.kind],['代码版本',record.version],['模块路径',source.modulePath||'尚未登记'],['调用入口',source.entrypoint||'尚未登记'],[source.commitLabel,source.commit||'尚未登记']])+section('源码与来源',facts(source.locations)+source.links.map(link=>`<a class="button" href="${esc(link.url)}" target="_blank" rel="noopener">${esc(link.label)} ↗</a>`).join('')+(!record.modulePath||!record.entrypoint?'<p class="evidence-empty">历史定位与来源凭据不等于已登记可调用接口。</p>':'')+`<details><summary>完整来源记录</summary>${pre(record.source)}</details>`);
  }
  function unavailableURI(uri){return uri?.startsWith('file:')?'原地址是本机文件链接，网页无法直接读取；需登记受管附件或可访问的 HTTP 地址。':'未提供可访问的图像地址；未补用其他产物。';}
  function imageItem(item){
    const e=item.artifactRef?get(item.artifactRef):null,r=e?.record||{},original=item.uri||r.uri||r.content?.items?.[0]?.uri,uri=A.safeURL(original),available=!['unavailable','missing','unknown'].includes(item.availability||r.availability);
    return `<figure class="typed-image">${uri&&available?`<a href="${esc(uri)}" target="_blank" rel="noopener"><img src="${esc(uri)}" loading="lazy" decoding="async" alt="${esc(item.caption||r.title||item.sampleId||'登记图像')}"></a>`:empty(available?unavailableURI(original):'登记的图像位置不可用；来源仍保留')}${!uri&&original?`<code class="unavailable-uri">${esc(original)}</code>`:''}<figcaption>${esc(item.caption||r.title||'图像')}${item.sampleId?' · 样本 '+esc(item.sampleId):''}</figcaption>${item.artifactRef?provenance(item.artifactRef)+refLink(item.artifactRef,'查看固定来源'):''}</figure>`;
  }
  function seriesSample(points,limit=600){
    if(points.length<=limit)return points;
    const selected=[{index:0,point:points[0]}],size=Math.ceil((points.length-2)/Math.floor((limit-2)/2));
    for(let start=1;start<points.length-1;start+=size){let min=start,max=start;for(let i=start+1;i<Math.min(start+size,points.length-1);i++){if(points[i][1]<points[min][1])min=i;if(points[i][1]>points[max][1])max=i;}[...new Set([min,max])].sort((a,b)=>a-b).forEach(index=>selected.push({index,point:points[index]}));}
    selected.push({index:points.length-1,point:points.at(-1)});return selected.map(x=>x.point);
  }
  function typed(result){
    if(!result)return empty('尚无可展示内容');const label=result.label||result.name||result.metricId||'';
    if(result.kind==='metric')return `<div class="typed-metric"><span>${esc(label)}</span><strong>${result.value==null?esc(A.statusNames[result.status]||result.status||'缺失'):esc(result.value)} <small>${esc(result.unit||'')}</small></strong><p>${esc([result.sampleId&&'样本 '+result.sampleId,result.sampleIds&&'样本 '+result.sampleIds.join('、'),result.aggregation,result.reason].filter(Boolean).join(' · '))}</p></div>`;
    if(result.kind==='series'){
      const points=(result.points||[]).map(p=>Array.isArray(p)?p:[p.x,p.y]).filter(p=>p.every(Number.isFinite)),x=result.xAxis||result.x||{},y=result.yAxis||result.y||{};
      if(!points.length)return empty('曲线没有有效数值点');let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;for(const [px,py] of points){xmin=Math.min(xmin,px);xmax=Math.max(xmax,px);ymin=Math.min(ymin,py);ymax=Math.max(ymax,py);}
      const draw=seriesSample(points),px=v=>48+(v-xmin)/(xmax-xmin||1)*480,py=v=>170-(v-ymin)/(ymax-ymin||1)*140;
      return `<div class="typed-series"><strong>${esc(label||'数值序列')}</strong><svg viewBox="0 0 560 220" role="img" aria-label="${esc(label)}，${points.length} 个登记数据点"><path d="M48 20V170H535" fill="none" stroke="#b4beca"/><polyline points="${draw.map(p=>px(p[0])+','+py(p[1])).join(' ')}" fill="none" stroke="#347b9c" stroke-width="2"/>${draw.length<=100?draw.map(p=>`<circle cx="${px(p[0])}" cy="${py(p[1])}" r="3" fill="#347b9c"><title>${esc(p.join(', '))}</title></circle>`).join(''):''}<text x="48" y="190">${esc(xmin)}</text><text x="500" y="190">${esc(xmax)}</text><text x="5" y="35">${esc(ymax)}</text><text x="5" y="170">${esc(ymin)}</text><text x="190" y="212">${esc(x.label||'x')} ${esc(x.unit||'')}</text></svg><p>${esc(y.label||'y')} ${esc(y.unit||'')} · ${points.length} 个登记点${draw.length<points.length?'；图中按区间保留极值，显示 '+draw.length+' 点':''}</p><details><summary>查看完整数值（分页）</summary>${batch(points,p=>`<div class="series-value"><span>${esc(p[0])}</span><span>${esc(p[1])}</span></div>`,'数据点',50)}</details></div>`;
    }
    if(result.kind==='image-set')return `<div class="typed-images">${batch(result.items||[],imageItem,'图像',12)||empty('图像集合为空')}</div>`;
    if(result.kind==='table'){const cs=result.columns||[],rows=result.rows||[];return `<div class="typed-table"><strong>${esc(label)}</strong>${batch(Array.from({length:Math.ceil(rows.length/50)},(_,i)=>rows.slice(i*50,(i+1)*50)),page=>`<table><thead><tr>${cs.map(c=>`<th>${esc(c.label||c.key||c.name)}</th>`).join('')}</tr></thead><tbody>${page.map(row=>`<tr>${cs.map(c=>`<td>${row[c.key||c.name]==null?'—':esc(row[c.key||c.name])}</td>`).join('')}</tr>`).join('')}</tbody></table>`,'表格分段（每段最多50行）',1)||empty('没有登记表格行')}</div>`;}
    if(result.kind==='attachment'){const url=['unavailable','missing','unknown'].includes(result.availability)?null:A.safeURL(result.uri);return `<div class="typed-attachment"><strong>${esc(label||'附件')}</strong><p>${esc(result.mimeType||result.mediaType||'')} · ${esc(result.uri||'未登记路径')}</p>${url?`<a class="button" href="${esc(url)}" target="_blank" rel="noopener">打开附件 ↗</a>`:empty(result.uri?.startsWith('file:')?unavailableURI(result.uri):'未提供可访问的 HTTP 附件地址')}</div>`;}
    return empty('该内容尚未声明受支持的展示格式');
  }
  function inlineMarkdown(text){
    const token=/(`[^`]+`|\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*)/g;let out='',last=0;for(const match of text.matchAll(token)){out+=esc(text.slice(last,match.index));const value=match[0];if(value.startsWith('`'))out+='<code>'+esc(value.slice(1,-1))+'</code>';else if(value.startsWith('**'))out+='<strong>'+esc(value.slice(2,-2))+'</strong>';else{const link=/^\[([^\]]+)\]\(([^)]+)\)$/.exec(value),url=A.safeURL(link[2]);out+=url?`<a href="${esc(url)}" target="_blank" rel="noopener">${esc(link[1])}</a>`:esc(link[1]+'（'+link[2]+'）');}last=match.index+value.length;}return out+esc(text.slice(last));
  }
  function markdown(text){
    const lines=String(text||'').replace(/\r\n?/g,'\n').split('\n');let out='',paragraph=[],list=null,code=null;
    const flush=()=>{if(paragraph.length){out+='<p>'+paragraph.map(inlineMarkdown).join('<br>')+'</p>';paragraph=[];}if(list){out+='</'+list+'>';list=null;}};
    for(const line of lines){if(/^\s*```/.test(line)){if(code){out+='<pre><code>'+esc(code.join('\n'))+'</code></pre>';code=null;}else{flush();code=[];}continue;}if(code){code.push(line);continue;}const heading=/^(#{1,4})\s+(.+)$/.exec(line),item=/^\s*(?:([-*+])|(\d+)\.)\s+(.+)$/.exec(line);if(heading){flush();const level=Math.min(4,heading[1].length+1);out+=`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`;}else if(item){if(paragraph.length){out+='<p>'+paragraph.map(inlineMarkdown).join('<br>')+'</p>';paragraph=[];}const tag=item[2]?'ol':'ul';if(list!==tag){if(list)out+='</'+list+'>';list=tag;out+='<'+tag+'>';}out+='<li>'+inlineMarkdown(item[3])+'</li>';}else if(!line.trim()){flush();}else{if(list){out+='</'+list+'>';list=null;}paragraph.push(line);}}
    if(code)out+='<pre><code>'+esc(code.join('\n'))+'</code></pre>';flush();return `<div class="report-markdown">${out||empty('报告正文为空')}</div>`;
  }
  function foundation(record){if(!record)return empty('报告未登记项目基础快照');const labels={goal:'目标与挑战',foundations:'模型、数据与基线',approach:'当前研究路线',resources:'实验与评估约定',consensus:'已确认的项目认识'};return `<p><strong>基础 v${esc(record.revision)}</strong></p><p class="column-config">${esc([record.at,record.origin].filter(Boolean).join(' · '))}</p><div class="foundation-document">${Object.entries(labels).filter(([key])=>record.fields?.[key]).map(([key,label])=>`<section><h3>${label}</h3><p>${esc(record.fields[key])}</p></section>`).join('')}</div>`;}
  function artifact(e){
    const r=e.effectiveRecord||e.record,run=get(r.producerRef),runRecord=run?.effectiveRecord||run?.record,code=get(runRecord?.codeRef),currentRun=!activeScope&&D.runs.find(x=>!x.isExternal&&A.sameRecord(x.ref,r.producerRef));
    const content=r.content||((r.kind==='image'||r.kind==='image-set')&&r.uri?{kind:'image-set',items:[{uri:r.uri,sampleId:r.sampleId,caption:r.title}]}:r.uri?{kind:'attachment',uri:r.uri,mimeType:r.mimeType||'application/octet-stream'}:null);
    const source=!r.producerRef||r.provenance==='unresolved'?section('原始生产者未核定',readableList(r.description||'此材料保留原始来源记录；尚未绑定实际运行与代码。')+pre(r.source||{})):section('实际生产来源',refLink(r.producerRef,runRecord?.title)+' '+refLink(runRecord?.codeRef,code?.effectiveRecord?.title||code?.record.title)+(currentRun&&currentRun.recordVersion!==r.producerRef.version?'<p>产物来源是运行记录 r'+r.producerRef.version+'；同一次运行的当前状态记录为 r'+currentRun.recordVersion+'。</p>':'')+facts([['样本',r.sampleId],['可用性',A.statusNames[r.availability]||r.availability]])+`<details><summary>实际配置</summary>${pre(r.config||{})}</details>`);
    return facts([['产出语义',r.semantic],['编辑任务',r.taskKey],['观察步',r.observation?.step],['观察时刻',r.observation?.time]])+refs('输入身份',[r.datasetRef,...(r.inputRefs||[])].filter(Boolean))+source+section('登记内容',['unavailable','missing','unknown'].includes(r.availability)?empty('产物位置未确认或不可用；原始来源记录保留。')+(r.uri?pre(r.uri):''):typed(content))+`<button class="button" data-studio="reuse-artifact" data-ref="${A.key(e.ref)}">引用到当前项目实验</button>`;
  }
  function render(type,id,context={}){
    if(type==='draft')return `<div class="evidence"><h2>准备研究对话</h2><p>从共享后端读取项目基础、当前位置与已登记材料。</p><button class="button primary" data-studio="context">生成当前上下文</button></div>`;
    const initial=context.scope||null,e=env(id,initial);if(!e)return `<div class="evidence">${empty(initial?'该记录不在报告的固定来源快照内；未读取当前项目记录替代。':'该固定版本未载入；请刷新记录后重试。')}</div>`;
    if(!initial)Object.entries(D.envelopes).forEach(([key,value])=>{if(!frozen.has(key))frozen.set(key,value);});
    const scope=e.ref.type==='report'?scopeForReport(id,initial):initial;
    return scoped(scope,()=>{
      const r=e.effectiveRecord||e.record,t=e.ref.type;let body='';
      if(t==='research'){
        const exps=entries('experiment').filter(x=>A.sameRecord(x.record.researchRef,e.ref));body=section('研究问题',readableList(r.question))+facts([['研究类型',kindNames[r.kind]||r.kind],['阶段',{idea:'研究探索',formal:'正式实验',ablation:'消融'}[r.stage]||r.stage],['待检验假设',r.hypothesis],['人工判断',typeof r.judgment==='string'?r.judgment:r.judgment?.label||'尚未判断']])+(r.judgment?.summary?section('判断依据',readableList(r.judgment.summary)):'')+(r.judgment?.limitations?section('局限',readableList(r.judgment.limitations)):'')+refs('派生自',r.parentRefs)+section(activeScope?'快照中的实验':'实验',batch(exps,x=>refLink(x.ref),'实验')||empty(activeScope?'此快照未包含实验记录':'尚未登记实验'));
      }else if(t==='experiment'){
        const base=activeScope?scopeFoundations.get(activeScope)?.find(x=>x.projectId===e.ref.projectId&&x.foundation.revision===r.foundationRevision)?.foundation:D.projects.find(p=>p.id===e.ref.projectId)?.versions.find(v=>v.revision===r.foundationRevision);
        const usages=entries('usage').filter(x=>A.sameRecord(x.record.experimentRef,e.ref)&&!x.record.revoked&&!x.record.removed),runs=entries('run').filter(x=>A.sameRecord(x.record.experimentRef,e.ref)),current=!activeScope&&D.hypotheses.find(h=>A.sameRecord(h.ref,r.researchRef));
        body=refs('所属研究',[r.researchRef])+facts([['研究绑定','基于研究 r'+r.researchRef.version+(current?'，当前 r'+current.recordVersion:'')],['状态',A.statusNames[r.status]||r.status],['项目基础','v'+r.foundationRevision]])+`<details><summary>实验所基于的项目基础 v${esc(r.foundationRevision)}</summary>${base?foundation(base):empty('此固定快照未包含该版本的基础正文；没有用当前基础替代。')}</details><details><summary>实验配置</summary>${pre(r.config||{})}</details>`+refs('评估约定',r.protocolRef?[r.protocolRef]:[])+section(activeScope?'快照中的材料引用':'指定材料引用',batch(usages,u=>refLink(u.ref,u.record.label),'引用')||empty(activeScope?'此快照未包含材料引用记录':'尚未选定材料'))+section(activeScope?'快照中的运行':'实际运行',batch(runs,x=>refLink(x.ref),'运行')||empty(activeScope?'此快照未包含运行记录':'尚无运行'));
      }else if(t==='spec'){
        const portTable=ports=>`<table class="contract-reader-table"><thead><tr><th>名称</th><th>类型与语义</th><th>约束</th></tr></thead><tbody>${(ports||[]).map(p=>`<tr><th>${esc(p.name)}</th><td>${esc(p.kind)}${p.semantic?' · '+esc(p.semantic):''}${p.description?'<small>'+esc(p.description)+'</small>':''}</td><td>${p.required===false?'可选':'必需'}${p.multiple?' · 多个':''}</td></tr>`).join('')}</tbody></table>`;
        body=facts([['职责',kindNames[r.kind]||r.kind],['状态',r.status==='ready'?'可用于构建':'草案']])+section('目的',readableList(r.purpose))+section('输入',portTable(r.inputs))+section('输出',portTable(r.outputs))+section('验收要求',readableList((r.acceptanceChecks||[]).map(c=>c.description)))+section('能力',readableList(r.capabilities))+refs('依赖模块',r.dependencies)+`<details><summary>参数约束</summary>${pre(r.configSchema)}</details>`+(!activeScope&&e.ref.projectId===D.projectId?`<div class="review-actions"><button class="button" data-contract="edit" data-id="${id}">修改规范</button><button class="button primary" data-contract="implement" data-id="${id}" ${r.status==='ready'?'':'disabled'}>登记实现</button></div>`:'');
      }else if(t==='code'){
        const executions=['run','evaluation','analysis','report'].flatMap(type=>entries(type)).filter(x=>{const record=x.effectiveRecord||x.record;return A.key(record.codeRef||record.generatorCodeRef)===id;});
        body=codeSourceMarkup(r)+refs('依据规范',r.specRef?[r.specRef]:[])+section('提交的检查证据',(r.checkEvidence||[]).map(c=>`<article class="check-evidence" data-status="${esc(c.status)}"><strong>${esc(c.checkId)}</strong><span>${esc({passed:'通过',failed:'失败',skipped:'未完成'}[c.status]||c.status)}</span><p>${esc(c.evidence)}</p></article>`).join('')||empty('未登记检查证据'))+refs('继承版本',r.parentRefs)+`<details><summary>来源凭据 · ${executions.length} 项</summary>${batch(executions,x=>refLink(x.ref),'执行记录')||empty('尚无执行记录')}</details>`;
      }else if(t==='run')body=refs('实际代码',r.codeRef?[r.codeRef]:[])+facts([['运行类别',kindNames[r.kind]||r.kind],['状态',A.statusNames[r.status]||r.status]])+`<details><summary>运行配置</summary>${pre(r.config||{})}</details>`+refs('固定输入',r.inputRefs)+refs('所属实验',r.experimentRef?[r.experimentRef]:[])+section(activeScope?'报告快照中的本次产物':'本次生产的产物',batch(entries('artifact').filter(x=>A.sameRecord(x.record.producerRef,e.ref)),x=>refLink(x.ref),'产物')||empty(activeScope?'此快照未包含产物记录':'尚未登记产物'));
      else if(t==='artifact')body=artifact(e);
      else if(t==='evaluation')body=refs('评估代码与协议',[r.codeRef,r.protocolRef].filter(Boolean))+refs('固定输入',r.inputRefs)+(r.pairs?.length?section('预测与参考配对',batch(r.pairs,pair=>`<div class="evaluation-pair"><span>${esc(pair.sampleId)}</span><div>预测 ${refLink(pair.predictionRef)}</div><div>参考 ${refLink(pair.referenceRef)}</div></div>`,'配对样本',20)):'')+section('评估状态',facts([['状态',r.status==='completed'?'已登记完成':A.statusNames[r.status]||r.status]])+(r.sampleStatuses?`<details><summary>逐样本状态</summary>${pre(r.sampleStatuses)}</details>`:'')+readableList(r.notes||''))+section('导入的结果',batch(r.results||[],typed,'结果',10)||empty('尚无结果'));
      else if(t==='analysis')body=refs('实验',r.experimentRefs)+refs('依据材料',r.inputRefs)+refs('对比视图',r.comparisonRefs)+refs('分析代码与运行',[r.codeRef,r.runRef].filter(Boolean))+section('观察',readableList(r.observations))+section('解释',readableList(r.interpretation))+(r.scope?section('适用范围',readableList(r.scope.description||r.scope.sampleIds)):'')+(r.coverage?section('覆盖',facts([['预期输入',r.coverage.expected],['已观察',r.coverage.observed],['缺失样本',(r.coverage.missingSampleIds||[]).join('、')||'无已登记缺失']])):'')+section('限制',readableList(r.limitations));
      else if(t==='report'){
        const records=[...(scopes.get(scope)?.values()||[])].filter(x=>A.key(x.ref)!==id);
        body=section('报告正文',markdown(r.markdown)+`<details><summary>查看 Markdown 原文</summary>${pre(r.markdown)}</details>`)+section('当时的项目基础',foundation(r.snapshot?.foundation))+refs('固定输入',r.inputRefs)+refs('固定对比',r.comparisonRefs)+refs('固定评估',r.evaluationRefs)+refs('固定分析',r.analysisRefs)+refs('报告生成器与凭据',[r.generatorCodeRef,r.generatorRunRef].filter(Boolean))+`<details class="report-sources"><summary>完整固定来源 · ${records.length} 个版本</summary><p>后续查看来源仍限于这份报告的快照。</p><div class="evidence-actions">${batch(records,x=>refLink(x.ref),'固定来源',30)}</div></details>`;
      }else if(t==='usage')body=refs('使用于',[r.experimentRef])+facts([['用途',r.role],['说明',r.label],['状态',r.revoked?'已移除':'有效引用']])+refs('精确产物清单',r.artifactRefs)+(!activeScope&&!r.revoked?`<button class="button" data-studio="remove-usage" data-ref="${id}">移除这条引用</button>`:'');
      else if(t==='comparison')body=section('比较条件',facts([['固定条件',asText(r.fixedConditions)],['比较变化',asText(r.varyingConditions)],['布局',r.viewSpec?.mode==='single'?'单样本':r.viewSpec?.mode==='multi'?'多样本':null]]))+refs('浏览集合',r.inputRefs)+(r.viewSpec?`<details><summary>固定视图设置</summary>${pre(r.viewSpec)}</details>`:'');
      else body=pre(r);
      return `<div class="evidence" data-evidence-type="${esc(t)}"><div class="evidence-title"><span>${esc(names[t]||t)}${scope?' · 报告固定快照':''}</span><h2>${esc(r.title||r.label||e.ref.id)}</h2></div>${provenance(e.ref)}${body}${e.amendmentRefs?.length?`<details><summary>已应用 ${e.amendmentRefs.length} 项人工修订</summary>${pre(e.amendmentRefs)}<h4>原始记录</h4>${pre(e.record)}</details>`:''}</div>`;
    });
  }
  if(typeof document!=='undefined')document.addEventListener('click',event=>{const b=event.target.closest('[data-collection-page]');if(!b)return;const c=collections.get(b.dataset.collectionPage),host=b.closest('.paged-collection');if(!c||!host)return;c.page+=Number(b.dataset.direction);const token=b.dataset.collectionPage,direction=b.dataset.direction;host.outerHTML=collectionMarkup(token);document.querySelector(`[data-collection="${token}"] [data-direction="${direction}"]:not([disabled])`)?.focus({preventScroll:true});});
  window.RPEvidence={render,typed,refLink,provenance,resolve:env,scopeForReport,markdown,seriesSample,batch,codeSource,clear:()=>{frozen.clear();scopes.clear();scopeFoundations.clear();collections.clear();}};
})();
