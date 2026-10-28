/* Process inspection shares records with the evidence desk; live points are not report inputs. */
(() => {
  'use strict';
  const A=window.RWSAdapter,M=window.RWSProcessModel,D=window.RP_DATA,esc=A.esc;
  const colors=['#2778b6','#14877b','#9654ba','#ce7c26','#c64e70','#657742'];
  let host=null,options=null,key='',ticket=0,response=null,error='',busy=false,loadedRevision=null,resizeObserver=null,lastWidth=0;
  const state={runs:new Set(),metric:'',from:'',to:'',axis:'step',source:'live'};
  const same=(a,b)=>a&&b&&a.projectId===b.projectId&&a.type===b.type&&a.id===b.id;
  const runIdentity=run=>JSON.stringify([run.ref.projectId,run.ref.id]);
  const find=ref=>A.find(D,A.key(ref));
  const isDemo=()=>document.body.dataset.demo==='offline-fictional-readonly';
  function runLabel(ref){const r=find(ref)||D.runs.find(row=>same(row.ref,ref));return r?.title||ref.id;}
  function runSpec(run){const code=find(run.raw.codeRef);return code&&find(code.raw.specRef)?.raw;}
  function choices(){
    if(options.collection)return [];
    const e=options.context.experiment,producerIds=new Set(options.artifacts.map(a=>a.runId));
    return D.runs.filter(run=>run.isCurrent&&!run.isExternal&&(options.scope==='project'||same(run.raw.experimentRef,e.ref)||producerIds.has(run.id))&&(runSpec(run)?.processMetrics||[]).length);
  }
  function filters(){
    const out={};if(state.metric)out.metricIds=[state.metric];
    for(const [field,value] of [['fromX',state.from],['toX',state.to]])if(value!==''){const n=Number(value);if(!Number.isFinite(n)||n<0)throw new Error('坐标范围需要非负数。');out[field]=n;}
    if(out.fromX!==undefined&&out.toX!==undefined&&out.fromX>out.toX)throw new Error('起点不能大于终点。');
    return out;
  }
  function fmt(n){if(!Number.isFinite(n))return '—';return Number(n.toPrecision(5)).toLocaleString('zh-CN',{maximumFractionDigits:5});}
  function sourceButton(ref,label){return ref?`<button class="button small" data-action="inspect" data-type="${esc(ref.type)}" data-id="${esc(A.key(ref))}">${esc(label)}</button>`:'';}
  function plot(group,width){
    const bounds=M.extent(group.series);if(!bounds)return '<div class="process-empty">没有此坐标轴下的有效点；原始缺失记录保留。</div>';
    const {xmin,xmax,ymin,ymax}=bounds,w=Math.max(520,width-84),right=w-24,px=x=>64+(x-xmin)/(xmax-xmin||1)*(right-64),py=y=>176-(y-ymin)/(ymax-ymin||1)*148;
    const tickX=x=>state.axis==='time'&&x>1e8?new Date(x*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):fmt(x);
    return `<svg class="process-plot" viewBox="0 0 ${w} 220" role="img" aria-label="${esc(group.metric)} · ${group.series.length} 条曲线">${[0,.5,1].map(t=>`<path d="M64 ${28+t*148}H${right}" class="process-grid-line"/><text x="54" y="${32+t*148}" text-anchor="end">${esc(fmt(ymax-t*(ymax-ymin)))}</text>`).join('')}<path d="M64 22V176H${right+5}" class="process-axis"/>${group.series.map((line,index)=>line.segments.map(segment=>{const points=window.RPEvidence.seriesSample(segment.map(p=>[p.x,p.y]),600),color=colors[index%colors.length];return `<polyline fill="none" stroke="${color}" stroke-width="2.4" points="${points.map(p=>`${px(p[0])},${py(p[1])}`).join(' ')}"/>${points.length<=60?points.map(p=>`<circle cx="${px(p[0])}" cy="${py(p[1])}" r="3" fill="${color}"><title>${esc(line.item.label)} · ${esc(fmt(p[0]))}: ${esc(fmt(p[1]))}</title></circle>`).join(''):''}`;}).join('')).join('')}<text x="64" y="204">${esc(tickX(xmin))}</text><text x="${right}" y="204" text-anchor="end">${esc(tickX(xmax))}</text></svg>`;
  }
  function curvesHTML(lines,width=host?.clientWidth||1000){
    if(!lines.length)return '<div class="process-empty"><strong>还没有曲线</strong><p>选择已登记过程指标的运行，或添加已有曲线材料。</p></div>';
    return M.curves(lines,state.axis).map(group=>`<section class="process-card"><header><div><h3>${esc(group.items[0].name||group.metric||'曲线')}</h3><span>${esc(group.unit==='1'?'无量纲':group.unit||'单位未登记')} · ${esc(state.axis==='time'?'时间':group.items[0].axis||'记录坐标')}</span></div><span class="process-tag ${group.comparable?'':'is-unknown'}">${group.comparable?'同定义与数据范围':'单独展示 · 比较条件未齐'}</span></header>${plot(group,width)}<div class="process-legend">${group.series.map((line,index)=>`<div><i style="background:${colors[index%colors.length]}"></i><strong>${esc(line.item.label)}</strong><span>${line.valid}/${line.total} 个有效点</span>${sourceButton(line.item.artifactRef||line.item.runRef,'来源')}</div>`).join('')}</div><details><summary>范围与原始数值</summary><p class="process-scope">${esc(JSON.stringify(group.scope||'数据范围未登记'))}</p>${group.series.map(line=>`<div class="process-values"><strong>${esc(line.item.label)}</strong>${window.RPEvidence.batch(line.item.points,p=>`<div><span>${esc(fmt(p[state.axis]))}</span><span>${esc(fmt(p.value))}</span><span>${esc(p.reason||'')}</span></div>`,'记录点',30)}</div>`).join('')}</details></section>`).join('');
  }
  function metricTable(rows,title){
    if(!rows.length)return '';
    return `<section class="process-card"><header><h3>${esc(title)}</h3><span>${rows.length} 个同口径分组</span></header>${rows.map(group=>`<div class="process-metric-group"><div class="process-metric-label"><strong>${esc(group.metric||'指标')}</strong><span>${esc(group.unit==='1'?'无量纲':group.unit||'单位未登记')}</span>${!group.comparable?'<small>条件未齐，单独展示</small>':''}</div><table class="process-metric-table"><thead><tr><th>方法 / 记录</th><th>数值</th><th>范围 / 状态</th><th>来源</th></tr></thead><tbody>${group.rows.map(row=>`<tr><th>${esc(row.label)}</th><td class="metric-value">${esc(fmt(row.displayValue))}</td><td>${esc(row.reason||row.status||'已记录')}</td><td>${sourceButton(row.evaluationRef||row.artifactRef||row.runRef,'查看')}</td></tr>`).join('')}</tbody></table><details><summary>比较口径</summary><p class="process-scope">${esc(JSON.stringify({scope:group.scope||'未登记',definition:group.protocol||'未登记'}))}</p></details></div>`).join('')}</section>`;
  }
  function allLines(){return state.source==='live'&&!options.collection?M.trackedLines(response,runLabel):options.artifacts.flatMap(a=>M.frozenLines(a));}
  function paint(){
    if(!host?.isConnected)return;
    const available=choices(),metricOptions=new Map();available.forEach(run=>(runSpec(run)?.processMetrics||[]).forEach(metric=>metricOptions.set(metric.id,metric.name||metric.id)));
    const live=state.source==='live'&&!options.collection;
    const selected=available.filter(run=>state.runs.has(runIdentity(run))),lines=allLines();
    host.innerHTML=`<div class="process-toolbar"><div><strong>${options.layout==='curve'?'过程与曲线':'指标对比'}</strong><span>${options.collection?'固定对比材料':'当前材料范围'}</span></div><label>内容<select data-process-field="source"><option value="live" ${live?'selected':''} ${options.collection?'disabled':''}>过程记录</option><option value="frozen" ${!live?'selected':''}>固定材料</option></select></label>${available.length&&live?`<details class="process-runs"><summary>运行来源 · 已选 ${selected.length}</summary><div>${available.map(run=>`<label><input type="checkbox" data-process-run="${esc(runIdentity(run))}" ${state.runs.has(runIdentity(run))?'checked':''}><span>${esc(run.title)}<small>${esc(JSON.stringify(run.raw.config||{}))}</small></span></label>`).join('')}</div></details><label>指标<select data-process-field="metric"><option value="">全部指标</option>${[...metricOptions].map(([id,name])=>`<option value="${esc(id)}" ${state.metric===id?'selected':''}>${esc(name)}</option>`).join('')}</select></label><label>从<input type="number" min="0" step="any" data-process-field="from" value="${esc(state.from)}" placeholder="起点"></label><label>到<input type="number" min="0" step="any" data-process-field="to" value="${esc(state.to)}" placeholder="终点"></label><button class="button" data-process="refresh" ${busy?'disabled':''}>${busy?'读取中…':'读取区间'}</button>`:''}<label>横轴<select data-process-field="axis"><option value="step" ${state.axis==='step'?'selected':''}>记录坐标</option><option value="time" ${state.axis==='time'?'selected':''}>记录时间</option></select></label></div>${error?`<p class="process-error" role="alert">${esc(error)}</p>`:''}${response?.truncated?'<p class="process-error">当前区间超过 5,000 个点，仅显示已读取部分。请缩小范围或减少运行来源后再固定证据。</p>':''}<div class="process-body">${options.layout==='curve'?curvesHTML(lines):metricTable(M.metricGroups([...M.evaluationMetrics(options.evaluations),...M.artifactMetrics(options.artifacts)]),'评测指标')+metricTable(M.metricGroups(lines.filter(line=>line.points.length).map(line=>{const point=line.points.at(-1);return {...line,value:point.value,status:'区间末点 · '+fmt(point.step),reason:point.reason};})),'过程指标 · 当前区间末点')||'<div class="process-empty">尚无当前范围的指标记录。</div>'}</div>${available.length&&live?`<div class="process-footer"><span>${response?`已读取 ${response.series.reduce((n,s)=>n+s.points.length,0)} / ${response.total} 个点`:'选择运行来源后读取过程记录'} · ${response?'固定后可用于分析和报告':'过程观察不等于评测结论'}</span><div>${selected.filter(run=>response?.series.some(s=>same(s.runRef,run.ref)&&s.points.length)).map(run=>`<button class="button small" data-process="freeze" data-run="${esc(run.id)}" ${busy||response?.truncated?'disabled':''}>固定 ${esc(run.title)}</button>`).join('')}</div></div>`:''}`;
  }
  async function query(){
    if(!host?.isConnected||!options)return;
    for(const field of ['from','to','metric']){const input=host.querySelector('[data-process-field="'+field+'"]');if(input)state[field]=input.value;}
    const mine=++ticket,projectId=D.projectId,revision=D.revision,runRefs=choices().filter(run=>state.runs.has(runIdentity(run))).map(run=>run.ref);
    error='';if(!runRefs.length){response=null;paint();return;}
    if(runRefs.length>20){error='一次最多比较 20 个运行来源。';paint();return;}
    busy=true;paint();try{const result=await window.RWSLive.call('rws_metrics_query',{projectId,runRefs,...filters(),limit:5000});if(mine!==ticket||projectId!==D.projectId)return;response=result.result;loadedRevision=revision;}catch(e){if(mine===ticket){error=e.message;response=null;}}finally{if(mine===ticket){busy=false;paint();}}
  }
  function render(target,props){
    if(host!==target&&typeof ResizeObserver!=='undefined'){
      resizeObserver?.disconnect();lastWidth=target.clientWidth;
      resizeObserver=new ResizeObserver(()=>{if(target!==host||!target.isConnected)return;const width=target.clientWidth;if(Math.abs(width-lastWidth)>1){lastWidth=width;const top=target.querySelector('.process-body')?.scrollTop||0;paint();const body=target.querySelector('.process-body');if(body)body.scrollTop=top;}});
      resizeObserver.observe(target);
    }
    host=target;options=props;const next=M.stable([D.projectId,props.context.experiment?.id,props.scope,props.collection?.id]);
    if(next!==key){key=next;ticket++;response=null;error='';busy=false;state.runs=new Set(choices().slice(0,6).map(runIdentity));state.metric='';state.from='';state.to='';state.source=choices().length&&!props.collection?'live':'frozen';}
    paint();if(state.source==='live'&&(!response||loadedRevision!==D.revision)&&!busy&&choices().some(run=>state.runs.has(runIdentity(run))))query();
  }
  document.addEventListener('input',event=>{
    const input=event.target,field=input.dataset.processField;
    if(field==='from'||field==='to'){state[field]=input.value;ticket++;response=null;busy=false;}
  });
  document.addEventListener('change',event=>{
    const input=event.target;if(input.dataset.processRun){if(input.checked)state.runs.add(input.dataset.processRun);else state.runs.delete(input.dataset.processRun);response=null;query();}
    else if(input.dataset.processField){const field=input.dataset.processField;state[field]=input.value;if(field==='axis')paint();else if(field==='source'){paint();if(state.source==='live'&&!response)query();}else{ticket++;response=null;busy=false;paint();}}
  });
  document.addEventListener('click',event=>{const button=event.target.closest('[data-process]');if(!button)return;
    if(button.dataset.process==='refresh'){query();return;}
    if(button.dataset.process!=='freeze')return;
    if(isDemo()){window.RWSUI.notify('只读演示；固定证据需要你的工作台后端。');return;}
    try{const run=D.runs.find(r=>r.id===button.dataset.run),p=window.RWSUI.project(),request=M.freezeRequest(response,run.ref,filters());window.RWSUI.openDialog('固定过程证据',`<form id="process-freeze-form" data-project="${esc(p.id)}" data-revision="${p.revision}"><p>将“${esc(run.title)}”当前已读取区间保存为独立材料。后续数据点不会改变这份证据。</p><label class="overview-field">材料名称<input name="title" value="${esc(run.title+' · 过程快照')}" required></label><input type="hidden" name="query" value="${esc(JSON.stringify(request))}"><button type="submit" class="button primary">固定当前证据</button></form>`);}catch(e){window.RWSUI.fail(e);}
  });
  document.addEventListener('submit',async event=>{const form=event.target;if(form.id!=='process-freeze-form')return;event.preventDefault();const UI=window.RWSUI;if(UI.isBusy())return;try{if(form.dataset.project!==UI.project()?.id)throw new Error('项目已切换，请重新选择证据。');const data=new FormData(form);await UI.write('rws_metrics_snapshot',{projectId:form.dataset.project,expectedRevision:Number(form.dataset.revision),title:String(data.get('title')).trim(),...JSON.parse(data.get('query'))},{after:result=>{response=null;window.RPWorkbench.inspect('artifact',A.key(result.result.ref));}});}catch(e){UI.fail(e);}});
  function frozenPreview(record){const old=state.axis;state.axis='step';try{return `<div class="process-frozen">${curvesHTML(M.frozenLines(record,record.title),document.querySelector('#reader')?.clientWidth||window.innerWidth-80)}</div>`;}finally{state.axis=old;}}
  window.RWSProcess={render,frozenPreview,reset:()=>{ticket++;key='';response=null;busy=false;}};
})();
