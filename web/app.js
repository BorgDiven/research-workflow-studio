/* Shared server records, with desktop research and code topology preserved. */
(() => {
  'use strict';
  const D=window.RP_DATA, $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const get=(kind,id)=>D[kind]?.find(x=>x.id===id), unique=a=>[...new Set(a)];
  const state={view:'research',hypothesisId:null,taskId:null,selectedCodeId:null,browseProjectCodes:false,codeRelations:'inheritance',selectedExecution:null,cfg:'4',showExtra:false,sample:'all',repeat:{},readerHistory:[],draftExperiment:null,experimentId:null,outputKind:'all',outputCollection:'experiment',outputGroupBy:'run',outputPages:{}};
  let toastTimer,lineFrame,stageLayoutFrame,projectStages=new Set();
  const layout={research:{focus:null,returnState:null,detailOpened:false},code:{focus:null,returnState:null}};
  const reducedMotion=()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const viewportFor=view=>$(view==='research'?'#research-viewport':view==='code'?'.code-scroll':'.comparison-scroll');
  function scrollPosition(view){const vp=viewportFor(view);return {left:vp?.scrollLeft||0,top:vp?.scrollTop||0};}
  function restoreScroll(view,p){const vp=viewportFor(view);if(vp){vp.scrollLeft=p.left;vp.scrollTop=p.top;}}
  function getLayoutState(){return {view:state.view,research:{overview:!layout.research.focus,focus:layout.research.focus,detailOpened:layout.research.detailOpened,scroll:scrollPosition('research'),canReturn:!!layout.research.focus},code:{overview:!layout.code.focus,focus:layout.code.focus,scroll:scrollPosition('code'),canReturn:!!layout.code.focus},projectStages:[...projectStages]};}
  function setProjectStages(stageIds){
    const next=new Set((Array.isArray(stageIds)?stageIds:[]).filter(id=>['idea','formal','ablation'].includes(id)));
    if(next.size===projectStages.size&&[...next].every(id=>projectStages.has(id)))return [...projectStages];
    projectStages=next;
    $$('.research-group[data-stage]').forEach(el=>{const active=projectStages.has(el.dataset.stage);el.classList.toggle('is-project-active',active);const mark=el.querySelector('.project-stage-marker');if(mark)mark.hidden=!active;});
    cancelAnimationFrame(stageLayoutFrame);stageLayoutFrame=requestAnimationFrame(()=>{const panel=$('#stage-research');if(state.view==='research'&&panel&&!panel.hidden&&panel.getClientRects().length)layoutResearch();});
    return [...projectStages];
  }
  function syncLayoutControls(){
    const l=layout[state.view],back=$('[data-action="layout-return"]'),overviewButton=$('[data-action="layout-overview"]');
    if(back)back.hidden=!l?.focus;if(overviewButton)overviewButton.hidden=true;
  }
  function focusRegion(view,target){
    const l=layout[view],allowed=view==='research'?['foundation','idea','formal','ablation']:['inference','evaluation','analysis','report'];if(!l||!allowed.includes(target))return;
    if(l.focus===target){exitFocus();return;}
    if(!l.returnState)l.returnState={scroll:scrollPosition(view)};
    l.focus=target;renderLayout(view);
    const targetLane=view==='code'?$('.lane[data-kind="'+target+'"]'):null;
    restoreScroll(view,{left:0,top:targetLane?Math.max(0,targetLane.offsetTop-8):0});syncLayoutControls();
  }
  function exitFocus(){
    const view=state.view,l=layout[view];if(!l?.focus)return;
    const saved=l.returnState?.scroll||{left:0,top:0};l.focus=null;l.returnState=null;
    renderLayout(view);restoreScroll(view,saved);syncLayoutControls();
  }
  function overview(){if(layout[state.view]?.focus)exitFocus();}
  function captureRects(view){const map=new Map();$$('#'+view+'-content [data-layout-key]').forEach(el=>{if(el.getClientRects().length)map.set(el.dataset.layoutKey,el.getBoundingClientRect());});return map;}
  function animateLayout(view,before){
    if(reducedMotion()||view!==state.view)return;
    $$('#'+view+'-content [data-layout-key]').forEach(el=>{
      const old=before.get(el.dataset.layoutKey),now=el.getBoundingClientRect();
      if(!old||!now.width||!now.height)return;
      const parentScale=Number(el.closest('.research-tree')?.dataset.scale||1),dx=(old.left-now.left)/parentScale,dy=(old.top-now.top)/parentScale,sx=old.width/now.width,sy=old.height/now.height;
      if(Math.abs(dx)+Math.abs(dy)+Math.abs(sx-1)+Math.abs(sy-1)<.5)return;
      el.animate([{transformOrigin:'top left',transform:'translate('+dx+'px,'+dy+'px) scale('+sx+','+sy+')'},{transformOrigin:'top left',transform:'none'}],{duration:320,easing:'cubic-bezier(.22,1,.36,1)'});
    });
    followLines();
  }
  function followLines(){cancelAnimationFrame(lineFrame);const until=performance.now()+(reducedMotion()?0:350);const frame=()=>{if(state.view==='research')drawResearch();else if(state.view==='code')drawCode();if(performance.now()<until)lineFrame=requestAnimationFrame(frame);};frame();}
  function renderLayout(view){if(view==='research')renderResearch();else if(view==='code')renderCode();}
  const currentH=()=>get('hypotheses',state.hypothesisId)||{id:null,title:'尚无研究条目',status:'待登记',kind:'exploration',experimentIds:[]};
  const currentItem=()=>get('tasks',state.taskId)||currentH();
  const currentExp=()=>get('experiments',state.experimentId||get('tasks',state.taskId)?.experimentId||currentH().experimentId)||{id:null,title:'尚未登记实验',members:[],config:{},hypothesisId:state.hypothesisId};
  const memberLinks=()=>D.experiments.flatMap(e=>e.members.map(m=>({...m,experimentId:e.id,hypothesisId:e.hypothesisId})));
  const artifactsForExp=e=>unique(e.members.flatMap(m=>m.artifactIds)).map(id=>get('artifacts',id)).filter(Boolean);
  const evaluationsForExp=e=>D.evaluations.filter(v=>v.experimentId===e.id&&e.id||v.isCurrent&&v.inputArtifactIds.some(id=>e.members.some(m=>m.artifactIds.includes(id))));
  const analysesForExp=e=>D.analyses.filter(a=>a.experimentIds.includes(e.id));
  const reportsForH=h=>D.reports.filter(r=>r.raw.researchRefs?.some(ref=>window.RWSAdapter.sameRecord(ref,h.ref)));
  const reportsForExp=e=>window.RWSAdapter.reportsForExperiment(D,e);
  function notify(s){$('#toast').textContent=s;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),2800);}
  function status(s){$('#status').textContent=s;}
  function imageStyle(image){return image?`background-position:${image.col/3*100}% ${image.row*100}%`:'';}
  function button(type,id,label,classes='button small'){return `<button class="${classes}" data-action="inspect" data-type="${type}" data-id="${esc(id)}">${esc(label)}</button>`;}
  const prose=value=>Array.isArray(value)?value.join('；'):typeof value==='string'?value:'';
  const researchSummary=n=>prose(n.question||n.purpose||n.hypothesis)||'研究问题尚未补充';
  function codeSummary(code){
    const spec=get('specs',code.specId),purpose=prose(code.purpose||spec?.purpose);if(purpose)return purpose;
    const capabilities=code.capabilities||spec?.capabilities;if(Array.isArray(capabilities)&&capabilities.length)return '能力：'+capabilities.slice(0,3).join('、');
    const kinds=unique(codeResults(code).flatMap(item=>item.semantic?[item.semantic]:item.content?.kind?[item.content.kind]:(item.results||[]).map(result=>result.kind)));
    if(kinds.length)return '已登记产出：'+kinds.slice(0,3).map(kind=>window.RWSResultsModel.semanticNames[kind]||kind).join('、');
    return prose(code.description||code.source?.description)||'实现说明尚未补充';
  }
  const inspectorSection=(title,body)=>`<section class="inspector-section"><h3>${esc(title)}</h3>${body}</section>`;
  const inspectorText=text=>`<p class="inspector-prose">${esc(prose(text))}</p>`;
  function inspectorRecords(title,records,type,empty){return inspectorSection(title,records.length?window.RPEvidence.batch(records,r=>button(type,r.id,r.title||r.displayId,'inspector-record'),'记录',5):`<p class="inspector-empty">${esc(empty)}</p>`);}
  function previewRecords(records){
    const previews=records.filter(row=>row.content||row.results?.length||row.observations).slice(0,3);
    return previews.map(row=>{const type=row.type||'artifact',content=row.content||row.results?.find(result=>['metric','series','image-set','table'].includes(result.kind));let display='';
      if(['unavailable','missing','unknown'].includes(row.availability))display='<p class="inspector-empty">材料位置尚不可用，来源记录保留。</p>';
      else if(content){const bounded=content.kind==='image-set'?{...content,items:(content.items||[]).slice(0,1)}:content.kind==='table'?{...content,rows:(content.rows||[]).slice(0,3)}:content;display=window.RPEvidence.typed(bounded);}
      else if(row.observations)display=inspectorText(row.observations);
      return `<article class="inspector-preview"><strong>${esc(row.title||row.displayId)}</strong>${display}${button(type,row.id,'查看详情')}</article>`;
    }).join('');
  }
  // Capture DOM-local interaction state before replacing a panel's contents.
  function rememberPanel(selector,viewport){
    const root=$(selector),vp=root?.querySelector(viewport),active=document.activeElement;
    let focus=null;
    if(root?.contains(active)){
      if(active.id)focus='#'+CSS.escape(active.id);
      else if(active.dataset.action)focus='[data-action="'+CSS.escape(active.dataset.action)+'"]'+['id','type','value','target','layoutView','kind','stage','view'].filter(k=>active.dataset[k]).map(k=>'[data-'+k.replace(/[A-Z]/g,c=>'-'+c.toLowerCase())+'="'+CSS.escape(active.dataset[k])+'"]').join('');
    }
    return {left:vp?.scrollLeft||0,top:vp?.scrollTop||0,focus};
  }
  function restorePanel(selector,viewport,saved){
    const root=$(selector),vp=root?.querySelector(viewport);
    if(vp){vp.scrollLeft=saved.left;vp.scrollTop=saved.top;}
    if(saved.focus)root?.querySelector(saved.focus)?.focus({preventScroll:true});
  }
  function executionCode(selection){
    if(!selection)return null;
    const kind={run:'runs',evaluation:'evaluations',analysis:'analyses',report:'reports'}[selection.type];
    const record=get(kind,selection.id);return record?.codeId||record?.generatorCodeId||null;
  }
  function getContext(){return {view:state.view,hypothesisId:state.hypothesisId,taskId:state.taskId,experimentId:currentExp().id,selectedCodeId:state.selectedCodeId,selectedExecution:state.selectedExecution?{...state.selectedExecution}:null};}
  function emitContext(){window.dispatchEvent(new CustomEvent('rp:context-change',{detail:getContext()}));}
  function selectCode(id){
    if(!get('codes',id))return;
    state.selectedCodeId=id;
    if(executionCode(state.selectedExecution)!==id){const linked=executions(get('codes',id))[0];state.selectedExecution=linked?{type:linked.type,id:linked.id}:null;}
    renderCode();status((get('codes',id).title||get('codes',id).displayId)+' 已选中');emitContext();
  }
  function selectExecution(type,id){
    const kind={run:'runs',evaluation:'evaluations',analysis:'analyses',report:'reports'}[type];
    if(!get(kind,id))return;
    state.selectedExecution={type,id};state.selectedCodeId=executionCode(state.selectedExecution);
    state.codeRelations='dependencies';renderCode();status((get(kind,id).title||get(kind,id).displayId)+' 的材料依赖已显示');emitContext();
  }
  const isExploration=()=>currentH().kind==='exploration';


  function researchEdges(){
    const edges=D.hypotheses.flatMap(h=>(h.parents||[]).map(id=>[id,h.id]));
    D.tasks.forEach(task=>edges.push([task.hypothesisId,task.id]));
    return edges;
  }
  const topologyPlan=window.RWSGraphLayout.topologyPlan;
  function researchNode(n){
    const selected=n.id===(state.taskId||state.hypothesisId),exploring=n.kind==='exploration',displayId=String(n.displayId||''),shortId=displayId.length>14?displayId.slice(0,8)+'…'+displayId.slice(-4):displayId;
    const evidenceCount=unique((n.experimentIds||[]).flatMap(id=>get('experiments',id)?.members||[]).flatMap(member=>member.artifactIds||[])).length;
    return `<button id="research-${n.id}" data-layout-key="research-${n.id}" class="research-node ${selected?'selected':''} ${exploring?'exploration-node':''}" data-action="select-hypothesis" data-id="${n.id}" aria-pressed="${selected}" aria-controls="research-inspector" aria-label="${esc(n.title)} · ${esc(n.displayId||'')} · ${esc(n.status)}" title="${esc(n.question||n.title)}"><span class="node-meta"><span title="${esc(n.status)}">${esc(n.status)}</span><small title="${esc(displayId)}">${esc(shortId)}${!n.isCurrent?' · r'+n.recordVersion:''}${n.isExternal?' · 外部':''}</small></span><strong>${esc(n.title)}</strong><span class="node-summary">${esc(researchSummary(n))}</span><span class="node-footnote">${n.experimentIds?.length||0} 实验 · ${evidenceCount} 材料<span>详情 ↗</span></span></button>`;
  }
  function regionHeader(name,count,target,view){
    const focused=layout[view].focus===target;
    return `<header class="region-header"><div><h2>${name}</h2>${count!==null?`<span class="region-count">${count}</span>`:''}${view==='research'&&target!=='foundation'?`<span class="project-stage-marker" ${projectStages.has(target)?'':'hidden'}>进行中</span>`:''}</div><button class="region-action ${focused?'active':''}" data-action="focus-region" data-layout-view="${view}" data-target="${target}" aria-pressed="${focused}" aria-label="${focused?'返回全局':'聚焦'}${name}">${focused?'返回全局':'聚焦'}</button></header>`;
  }
  function researchInspector(item,h,e,ev,an,rp){
    const parents=(h.parents||[]).map(id=>get('hypotheses',id)).filter(Boolean),judgment=typeof h.judgment==='string'?h.judgment:h.judgment?.label||h.status;
    const artifacts=artifactsForExp(e),previews=previewRecords([...artifacts.slice(0,2).map(a=>({...a,type:'artifact'})),...ev.slice(0,1).map(v=>({...v,type:'evaluation'}))]);
    return `<aside id="research-inspector" class="evidence-tray node-inspector has-selection" aria-label="当前研究详情"><header class="inspector-heading"><span class="inspector-eyebrow">当前研究</span><h2>${esc(item.title)}</h2><span class="inspector-status">${esc(judgment)}</span></header>${inspectorSection('研究问题',inspectorText(researchSummary(item)))}${item.hypothesis?inspectorSection('待检验假设',inspectorText(item.hypothesis)):''}${parents.length?inspectorRecords('承接的研究',parents,'hypothesis',''):''}${h.judgment?.summary?inspectorSection('判断依据',inspectorText(h.judgment.summary)):''}<div class="evidence-quicklinks">${item.id?button('hypothesis',item.id,'完整研究条目'):''}<button class="button small" data-studio="context">准备对话</button></div>${inspectorSection('当前实验',e.id?`<strong class="inspector-experiment">${esc(e.title)}</strong><span class="detail-experiment">${esc(e.status||'')}${e.researchVersion&&e.currentResearchVersion!==e.researchVersion?' · 基于研究 r'+e.researchVersion+'，当前 r'+e.currentResearchVersion:''}</span>${button('experiment',e.id,'实验详情')}`:'<p class="inspector-empty">尚未登记实验</p>')}<div class="evidence-tiles"><button class="evidence-tile" data-action="view" data-view="outputs"><span class="tile-label">材料</span><strong>${artifacts.length?artifacts.length+' 项产出':'尚无材料'}</strong></button><button class="evidence-tile" ${ev.length?`data-action="inspect" data-type="evaluation" data-id="${ev[0].id}"`:'data-action="inspect-context"'}><span class="tile-label">评估</span><strong>${ev.length?ev.length+' 份评估':'尚未评估'}</strong></button><button class="evidence-tile" ${an.length?`data-action="inspect" data-type="analysis" data-id="${an[0].id}"`:'data-action="inspect-context"'}><span class="tile-label">分析</span><strong>${an.length?an.length+' 份分析':'尚无分析'}</strong></button><button class="evidence-tile" ${rp.length?`data-action="inspect" data-type="report" data-id="${rp[0].id}"`:'data-action="inspect-context"'}><span class="tile-label">报告</span><strong>${rp.length?rp.length+' 份报告':'尚无报告'}</strong></button></div>${previews?inspectorSection('材料预览',previews+'<button class="button small" data-action="view" data-view="outputs">查看全部与对比</button>'):''}${inspectorRecords('分析',an,'analysis','尚无分析记录')}${an[0]?.observations?`<p class="inspector-observation">${esc(prose(an[0].observations))}</p>`:''}${inspectorRecords('报告与结论',rp,'report','尚无报告')}${item.plannedActivities?.length?inspectorSection('计划活动',inspectorText(item.plannedActivities)):''}</aside>`;
  }
  function renderResearch(){
    const saved=rememberPanel('#research-content','#research-viewport'),before=captureRects('research'),foundationScroll=$('#project-foundation')?.scrollTop||0,l=layout.research;
    const h=currentH(),item=get('tasks',state.taskId)||h,e=currentExp(),exploring=item.kind==='exploration',ev=evaluationsForExp(e),an=analysesForExp(e),rp=reportsForExp(e),nodes=[...D.hypotheses,...D.tasks],foundationFocus=l.focus==='foundation',foundationExpanded=!l.focus||foundationFocus;
    const judgment=h.judgment?.label||h.status;
    $('#research-content').innerHTML=`<div class="research-layout" data-focus="${l.focus||''}"><div id="research-viewport" class="research-main"><div id="research-board" class="research-board"><aside class="foundation-pane ${foundationFocus?'is-focus-target':''}" data-layout-key="foundation">${regionHeader('项目基础',null,'foundation','research')}<span class="foundation-version" data-foundation-revision></span><div class="foundation-compact-summary" ${foundationExpanded?'hidden':''}><p data-foundation-summary></p><button class="button small" data-studio="overview">项目说明</button></div><div id="project-foundation" class="foundation-column" aria-label="项目基础" ${foundationExpanded?'':'hidden'}></div></aside>${[['idea','研究探索'],['formal','正式实验'],['ablation','消融']].map(([stage,name])=>{
      const members=nodes.filter(n=>n.stage===stage),mode=l.focus?(l.focus===stage?'focus':'mini'):'global';
      return `<section class="research-group ${mode==='focus'?'is-focus-target':''} ${projectStages.has(stage)?'is-project-active':''}" data-stage="${stage}" data-scale="${mode}" data-empty="${!members.length}" id="research-region-${stage}">${regionHeader(name,members.length,stage,'research')}<div class="research-group-body"><div class="research-tree">${members.map(researchNode).join('')}</div></div></section>`;
    }).join('')}<svg id="research-edges" class="relation-svg" aria-label="研究推进关系"></svg></div></div>${researchInspector(item,h,e,ev,an,rp)}</div>`;
    window.dispatchEvent(new CustomEvent('rp:foundation-render'));if($('#project-foundation'))$('#project-foundation').scrollTop=foundationScroll;
    layoutResearch();restorePanel('#research-content','#research-viewport',saved);animateLayout('research',before);syncLayoutControls();
  }
  function layoutResearch(){
    const board=$('#research-board'),vp=$('#research-viewport');if(!board||!vp?.clientWidth)return;
    const l=layout.research,edges=researchEdges(),all=[...D.hypotheses,...D.tasks],plans=new Map(),slots=new Map(),stages=['idea','formal','ablation'];
    const dimensions={global:{w:184,h:124,gx:24,gy:18},focus:{w:204,h:144,gx:28,gy:22},mini:{w:152,h:112,gx:20,gy:16}},foundationWidth=l.focus==='foundation'?300:l.focus?142:228;
    board.style.setProperty('--foundation-width',foundationWidth+'px');board.classList.toggle('is-overview',!l.focus);
    const counts=stages.map(stage=>all.filter(n=>n.stage===stage).length),minimums=counts.map(count=>count?212:120),spare=Math.max(0,vp.clientWidth-foundationWidth-70-minimums.reduce((a,b)=>a+b,0)),weight=counts.reduce((a,b)=>a+Math.sqrt(b),0);
    stages.forEach(stage=>{
      const index=stages.indexOf(stage),group=$('#research-region-'+stage),mode=l.focus?(l.focus===stage?'focus':'mini'):'global',d=dimensions[mode],members=all.filter(n=>n.stage===stage),budget=minimums[index]+(weight?spare*Math.sqrt(counts[index])/weight:0)-28,plan=topologyPlan(members,edges,d.w,d.h,d.gx,d.gy,mode==='mini'?d.w:budget,'vertical');
      group.style.setProperty('--node-width',d.w+'px');group.style.setProperty('--node-height',d.h+'px');
      plan.positions.forEach(p=>slots.set(p.id,{...p,stage,height:d.h}));plans.set(stage,plan);
    });
    const widths=stages.map((stage,i)=>Math.max(counts[i]?180:120,plans.get(stage).width+28));
    stages.forEach((stage,i)=>$('#research-region-'+stage).style.width=widths[i]+'px');
    board.style.width=Math.max(vp.clientWidth,foundationWidth+70+widths.reduce((a,b)=>a+b,0))+'px';
    D.tasks.forEach(task=>{const parent=edges.find(([,to])=>to===task.id)?.[0],source=slots.get(parent),target=slots.get(task.id);if(source&&target){const sourceHeader=$('#research-region-'+source.stage+' .region-header').offsetHeight,targetHeader=$('#research-region-'+target.stage+' .region-header').offsetHeight;target.y=Math.max(0,source.y+source.height/2+sourceHeader-targetHeader-target.height/2);}});
    stages.forEach((stage,i)=>{
      const group=$('#research-region-'+stage),items=[...slots.values()].filter(p=>p.stage===stage),plan=plans.get(stage),height=Math.max(0,...items.map(p=>p.y+p.height)),body=group.querySelector('.research-group-body'),tree=group.querySelector('.research-tree');
      const scale=1;
      tree.style.width=plan.width+'px';tree.style.height=height+'px';tree.style.transform='scale('+scale+')';tree.dataset.scale=String(scale);tree.style.left=Math.max(14,(widths[i]-plan.width*scale)/2)+'px';tree.style.top='12px';
      items.forEach(p=>{const el=$('#research-'+p.id);el.style.left=p.x+'px';el.style.top=p.y+'px';el.dataset.rank=p.rank;el.dataset.component=p.component;});
      body.style.height=(height*scale+24)+'px';group.dataset.fit=scale<.99?'scaled':'natural';
    });
    const columnHeight=Math.max(vp.clientHeight-28,...stages.map(stage=>{const group=$('#research-region-'+stage);return group.querySelector('.region-header').offsetHeight+parseFloat(group.querySelector('.research-group-body').style.height)+2;}));
    board.style.height=(columnHeight+28)+'px';
    const svg=$('#research-edges');svg.setAttribute('width',board.scrollWidth);svg.setAttribute('height',board.scrollHeight);drawResearch();
  }
  const marker=(id,color)=>`<defs><marker id="${id}" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7" fill="${color}"/></marker></defs>`;
  function drawResearch(){
    const board=$('#research-board'),svg=$('#research-edges');if(!board||!svg||!board.getClientRects().length)return;
    const base=board.getBoundingClientRect();let html=marker('research-arrow','#a49bc2')+marker('research-membership-arrow','#b6bbcd');
    researchEdges().forEach(([from,to])=>{
      const a=$('#research-'+from),b=$('#research-'+to);if(!a?.getClientRects().length||!b?.getClientRects().length)return;
      const ar=a.getBoundingClientRect(),br=b.getBoundingClientRect(),sourceGroup=a.closest('.research-group'),targetGroup=b.closest('.research-group'),vertical=sourceGroup===targetGroup,x1=(vertical?ar.left+ar.width/2:ar.right)-base.left,y1=(vertical?ar.bottom:ar.top+ar.height/2)-base.top,x2=(vertical?br.left+br.width/2:br.left)-base.left,y2=(vertical?br.top:br.top+br.height/2)-base.top,rail=vertical?(x1+x2)/2:(sourceGroup.getBoundingClientRect().right+targetGroup.getBoundingClientRect().left)/2-base.left;
      const ownership=!!get('tasks',to),binding=get('hypotheses',to)?.parentBindings?.find(x=>x.from===from);
      let path=vertical?`M${x1} ${y1} L${x1} ${(y1+y2)/2} L${x2} ${(y1+y2)/2} L${x2} ${y2}`:Math.abs(y1-y2)<1?`M${x1} ${y1} L${x2} ${y2}`:`M${x1} ${y1} L${rail} ${y1} L${rail} ${y2} L${x2} ${y2}`;
      if(ownership&&!vertical){
        const obstacles=$$('#research-board .research-node').filter(el=>el!==a&&el!==b&&el.getClientRects().length).map(el=>{const r=el.getBoundingClientRect();return {left:r.left-base.left,right:r.right-base.left,top:r.top-base.top,bottom:r.bottom-base.top};}).filter(r=>r.left<x2&&r.right>x1&&r.top<Math.max(y1,y2)+3&&r.bottom>Math.min(y1,y2)-3);
        if(obstacles.length){const upper=Math.min(...obstacles.map(r=>r.top))-8,enter=(x1+Math.min(...obstacles.map(r=>r.left)))/2,leave=(x2+Math.max(...obstacles.map(r=>r.right)))/2;path=`M${x1} ${y1} L${enter} ${y1} L${enter} ${upper} L${leave} ${upper} L${leave} ${y2} L${x2} ${y2}`;}
      }
      html+=`<path data-from="${from}" data-to="${to}" data-relation="${ownership?'ownership':'derivation'}" class="${ownership?'research-membership ':''}${from===(state.taskId||state.hypothesisId)||to===(state.taskId||state.hypothesisId)?'selected':''}" d="${path}" marker-end="url(#${ownership?'research-membership-arrow':'research-arrow'})"><title>${ownership?'所属研究':binding?'研究派生 · 引用研究 '+esc(binding.ref.id)+' r'+binding.ref.version:'研究派生'}</title></path>`;
    });svg.setAttribute('width',board.scrollWidth);svg.setAttribute('height',board.scrollHeight);svg.innerHTML=html;
  }
  const typeKind={run:'inference',evaluation:'evaluation',analysis:'analysis',report:'report'};
  function executions(code){if(code.kind==='inference')return D.runs.filter(r=>r.codeId===code.id).map(r=>({...r,type:'run'}));if(code.kind==='evaluation')return D.evaluations.filter(r=>r.codeId===code.id).map(r=>({...r,type:'evaluation'}));if(code.kind==='analysis')return D.analyses.filter(r=>r.codeId===code.id).map(r=>({...r,type:'analysis'}));return D.reports.filter(r=>r.generatorCodeId===code.id).map(r=>({...r,type:'report'}));}
  function codeResults(code){if(code.kind==='inference'){const producers=new Set(executions(code).map(r=>r.id));return D.artifacts.filter(a=>producers.has(a.runId)).map(a=>({...a,type:'artifact'}));}return executions(code);}


  function codeCard(code){
    const ex=codeResults(code),sel=state.selectedCodeId===code.id;
    const related=code.kind==='inference'?D.runs.some(r=>r.codeId===code.id&&(r.experimentId===currentExp().id||currentExp().members.some(m=>m.runId===r.id))):code.kind==='evaluation'?evaluationsForExp(currentExp()).some(x=>x.codeId===code.id):code.kind==='analysis'?analysesForExp(currentExp()).some(x=>x.codeId===code.id):reportsForExp(currentExp()).some(x=>x.generatorCodeId===code.id);
    return `<button id="code-${code.id}" data-layout-key="code-${code.id}" class="code-node ${sel?'selected':''} ${related?'':'unrelated'}" data-kind="${code.kind}" data-action="select-code" data-id="${code.id}" aria-pressed="${sel}" aria-controls="code-inspector" title="${esc(code.title)}" aria-label="${esc(code.title)} · ${esc(code.version)} · ${ex.length} 项产出"><strong>${esc(code.title)}</strong><span class="node-summary">${esc(codeSummary(code))}</span><span class="code-meta"><span title="${esc(code.version)}">${esc(code.version)}</span><span>${ex.length} 项产出</span><small>详情 ↗</small></span></button>`;
  }
  function configLabel(c){return Object.keys(c||{}).length?JSON.stringify(c):'未登记配置';}
  function codeInspector(selected,selectedManual,results){
    if(!selected&&!selectedManual)return `<section class="code-selection-detail" aria-label="代码规范与产出"><header class="inspector-heading"><span class="inspector-eyebrow">实现详情</span><h2>选择一个代码块</h2></header><p class="inspector-prose">查看用途、代码来源、输入输出和已有产物。</p></section>`;
    const manual=selectedManual?get('analyses',state.selectedExecution.id):null,source=selected?window.RPEvidence.codeSource(selected):null,spec=get('specs',selected?.specId),previews=previewRecords(results),relatedResearch=selected?D.hypotheses.filter(h=>D.experiments.some(e=>e.hypothesisId===h.id&&executions(selected).some(r=>r.experimentId===e.id||(r.experimentIds||[]).includes(e.id)||(r.hypothesisIds||[]).includes(h.id)))):[];
    const sourceFacts=source?`<dl class="inspector-facts"><dt>${esc(source.commitLabel)}</dt><dd>${esc(source.commit||'尚未登记')}</dd><dt>模块 / 入口</dt><dd>${esc([source.modulePath,source.entrypoint].filter(Boolean).join(' · ')||'尚未登记可调用接口')}</dd></dl>${source.links.map(link=>`<a class="button small" href="${esc(link.url)}" target="_blank" rel="noopener">${esc(link.label)} ↗</a>`).join('')}`:'';
    const ports=spec?`<dl class="inspector-facts"><dt>输入</dt><dd>${esc((spec.inputs||[]).map(p=>p.name+' · '+(p.semantic||p.kind)).join('；')||'尚未登记')}</dd><dt>输出</dt><dd>${esc((spec.outputs||[]).map(p=>p.name+' · '+(p.semantic||p.kind)).join('；')||'尚未登记')}</dd></dl>${button('spec',spec.id,'完整代码块规范')}`:'';
    const purpose=selected?.purpose||spec?.purpose;
    const details=selected?inspectorSection(purpose?'实现用途':'登记说明',inspectorText(purpose||source.description||'实现说明尚未补充'))+inspectorSection('代码来源',sourceFacts)+ (spec?inspectorSection('输入与输出',ports):'')+(relatedResearch.length?inspectorRecords('关联研究',relatedResearch,'hypothesis',''):''):inspectorSection('观察',inspectorText(manual?.observations||'尚未登记观察'))+inspectorSection('解释',inspectorText(manual?.interpretation||'尚未登记解释'))+(manual?.limitations?inspectorSection('限制',inspectorText(manual.limitations)):'');
    return `<section class="code-selection-detail" aria-label="代码规范与产出"><header class="inspector-heading"><span class="inspector-eyebrow">${selected?'实现详情':'人工 / 对话分析'}</span><h2>${esc(selected?.title||manual?.title)}</h2>${selected?`<span class="inspector-status">${esc(selected.version)}${selected.isExternal?' · 来源：'+esc(selected.sourceProject):''}</span>`:''}</header>${details}<div class="inspector-actions">${selected?button('code',selected.id,'完整源码与检查'):button('analysis',manual.id,'完整分析')}</div>${previews?inspectorSection('产出预览',previews):''}${inspectorSection('全部产出 · '+results.length,`<div class="selected-executions">${window.RPEvidence.batch(results,x=>button(x.type,x.id,x.title||x.displayId,'inspector-record'),'产出',6)||'<span class="empty-evidence-label">尚无关联产出</span>'}</div>`)}${selected&&executions(selected).length?`<details class="inspector-credentials"><summary>执行来源凭据 · ${executions(selected).length}</summary>${window.RPEvidence.batch(executions(selected),x=>button(x.type,x.id,x.title||x.displayId,'inspector-record'),'凭据',6)}</details>`:''}</section>`;
  }
  function renderCode(){
    const saved=rememberPanel('#code-content','.code-scroll'),before=captureRects('code'),l=layout.code;
    const kinds=[['inference','推理'],['evaluation','评估'],['analysis','分析'],['report','报告生成']],selected=get('codes',state.selectedCodeId);
    const selectedManual=!selected&&state.selectedExecution?.type==='analysis'&&!get('analyses',state.selectedExecution.id)?.codeId;
    const selectedExecutions=selected?codeResults(selected):selectedManual?D.analyses.filter(a=>!a.codeId).map(a=>({...a,type:'analysis'})):[];
    $('#code-content').innerHTML=`<div class="code-layout"><div class="view-tools"><button class="text-button ${state.codeRelations==='inheritance'?'active':''}" data-action="code-relations" data-value="inheritance">版本继承</button><button class="text-button ${state.codeRelations==='dependencies'?'active':''}" data-action="code-relations" data-value="dependencies">材料依赖</button><span class="spacer"></span><div class="code-legend"><span>版本继承</span><span>产物输入</span></div></div><div class="code-workarea"><div class="code-scroll"><div class="lane-board">${kinds.map(([kind,name])=>{
      const cs=D.codes.filter(c=>c.kind===kind),mode=l.focus?(l.focus===kind?'focus':'mini'):'global',manual=kind==='analysis'?D.analyses.filter(a=>!a.codeId):[];
      return `<section class="lane ${mode==='focus'?'is-focus-target':''}" data-kind="${kind}" data-scale="${mode}">${regionHeader(name,cs.length+(manual.length?1:0),kind,'code')}<div class="lane-content">${cs.map(codeCard).join('')}${manual.length?`<button id="code-manual-analysis" data-layout-key="code-manual-analysis" class="code-node ${selectedManual?'selected':''}" data-kind="analysis" data-action="execution" data-type="analysis" data-id="${manual[0].id}" aria-controls="code-inspector" aria-pressed="${selectedManual}"><strong>人工 / 对话分析</strong><span class="node-summary">${esc(prose(manual[0].observations)||'查看已记录的观察与解释')}</span><span class="code-meta"><span>${manual.length} 项记录</span><small>详情 ↗</small></span></button>`:''}</div></section>`;
    }).join('')}<svg class="relation-svg" id="code-edges" aria-label="代码继承或所选运行的材料依赖"></svg></div><div class="dependency-note" id="dependency-note"></div></div><aside id="code-inspector" class="code-inspector node-inspector" aria-label="当前代码详情">${codeInspector(selected,selectedManual,selectedExecutions)}<section class="spec-library" aria-label="代码块规范"><div><strong>代码块规范</strong><button class="text-button" data-contract="new">＋ 定义</button></div><div class="spec-library-items">${(D.specs||[]).filter(s=>s.isCurrent&&!s.isExternal).map(s=>`<button class="spec-card" data-contract="detail" data-id="${s.id}"><span class="spec-kind" data-kind="${s.kind}">${esc({inference:'推理',evaluation:'评估',analysis:'分析',report:'报告'}[s.kind]||s.kind)}</span><strong>${esc(s.title)}</strong><small>r${s.recordVersion} · ${s.raw.status==='ready'?'可用于构建':'草案'}</small></button>`).join('')||'<span class="empty-evidence-label">尚未定义代码块规范。</span>'}</div></section></aside></div></div>`;
    layoutCode();restorePanel('#code-content','.code-scroll',saved);animateLayout('code',before);syncLayoutControls();
  }
  function layoutCode(){
    const board=$('.lane-board'),vp=$('.code-scroll');if(!board||!vp?.clientWidth)return;
    const edges=D.codes.flatMap(c=>(c.parentIds||[]).map(id=>[id,c.id]));let boardWidth=0;
    $$('.lane').forEach(lane=>{
      const kind=lane.dataset.kind,mode=layout.code.focus?(layout.code.focus===kind?'focus':'mini'):'global',dims={global:{w:208,h:96,gx:24,gy:14},focus:{w:228,h:108,gx:28,gy:18},mini:{w:184,h:90,gx:20,gy:12}}[mode],nodes=D.codes.filter(c=>c.kind===kind);
      if(kind==='analysis'&&D.analyses.some(a=>!a.codeId))nodes.push({id:'manual-analysis'});
      const plan=topologyPlan(nodes,edges,dims.w,dims.h,dims.gx,dims.gy,Math.max(dims.w,vp.clientWidth-52)),content=lane.querySelector('.lane-content');lane.style.setProperty('--code-width',dims.w+'px');lane.style.setProperty('--code-height',dims.h+'px');
      plan.positions.forEach(p=>{const el=$('#code-'+p.id);el.style.left=(p.x+14)+'px';el.style.top='5px';el.dataset.rank=p.rank;el.dataset.component=p.component;if(p.y)el.style.top=(p.y+5)+'px';});
      content.style.height=(plan.height+10)+'px';boardWidth=Math.max(boardWidth,plan.width+28);
    });
    board.style.width=Math.max(boardWidth,vp.clientWidth)+'px';const svg=$('#code-edges');svg.setAttribute('width',board.scrollWidth);svg.setAttribute('height',board.scrollHeight);drawCode();
  }
  function visibleCodeEndpoint(id){
    let el=document.getElementById(id);if(el?.getClientRects().length)return el;
    if(!id.startsWith('execution-'))return null;
    const executionId=id.slice(10),groups=[['runs','run'],['evaluations','evaluation'],['analyses','analysis'],['reports','report']];
    for(const [group,type] of groups){
      const record=get(group,executionId);if(!record)continue;
      const codeId=record.codeId||record.generatorCodeId;el=document.getElementById(codeId?'code-'+codeId:'code-manual-analysis');
      return el?.getClientRects().length?el:null;
    }
    return null;
  }
  function codePoint(id,side){
    const el=visibleCodeEndpoint(id),board=$('.lane-board');if(!el||!board)return null;
    const a=el.getBoundingClientRect(),b=board.getBoundingClientRect();
    return {key:el.id,x:a.left-b.left+(side==='right'?a.width:side==='left'?0:a.width/2),y:a.top-b.top+(side==='bottom'?a.height:side==='top'?0:a.height/2)};
  }
  function drawCode(){
    const svg=$('#code-edges'),board=$('.lane-board');if(!svg||!board?.getClientRects().length)return;
    let html=marker('code-arrow','#8fa5c1')+marker('consume-arrow','#158f95');
    for(const c of D.codes.flatMap(c=>(c.parentIds||[]).map(parentId=>({...c,parentId})))){
      const a=codePoint('code-'+c.parentId,'right'),b=codePoint('code-'+c.id,'left');if(!a||!b)continue;
      html+=`<path class="inherit" data-from="${a.key}" data-to="${b.key}" d="M${a.x} ${a.y} C${a.x+15} ${a.y},${b.x-15} ${b.y},${b.x} ${b.y}" marker-end="url(#code-arrow)"/>`;
    }
    const pairs=[],addEval=v=>{if(v)unique(v.inputArtifactIds.map(id=>get('artifacts',id)?.runId).filter(Boolean)).forEach(r=>pairs.push([r,v.id]));};
    const addAnalysis=a=>{if(!a)return;const covered=new Set();a.evaluationIds.forEach(id=>{pairs.push([id,a.id]);const v=get('evaluations',id);v?.inputArtifactIds.forEach(x=>covered.add(x));addEval(v);});unique(a.artifactIds.filter(id=>!covered.has(id)).map(id=>get('artifacts',id)?.runId).filter(Boolean)).forEach(id=>pairs.push([id,a.id]));};
    const sel=state.selectedExecution;
    if(sel?.type==='evaluation')addEval(get('evaluations',sel.id));
    else if(sel?.type==='analysis')addAnalysis(get('analyses',sel.id));
    else if(sel?.type==='report'){const r=get('reports',sel.id);r?.analysisIds.forEach(id=>{pairs.push([id,r.id]);addAnalysis(get('analyses',id));});}
    else if(sel?.type==='run')D.evaluations.filter(v=>v.inputArtifactIds.some(id=>get('artifacts',id)?.runId===sel.id)).forEach(addEval);
    const drawn=new Set();
    if(state.codeRelations==='dependencies')pairs.forEach(([from,to])=>{
      const a=codePoint('execution-'+from,'bottom'),b=codePoint('execution-'+to,'top');if(!a||!b||a.key===b.key)return;
      const key=a.key+'|'+b.key;if(drawn.has(key))return;drawn.add(key);
      html+=`<path class="consume" data-from="${a.key}" data-to="${b.key}" data-execution-from="${from}" data-execution-to="${to}" d="M${a.x} ${a.y} C${a.x} ${a.y+18},${b.x} ${b.y-18},${b.x} ${b.y}" marker-end="url(#consume-arrow)"/>`;
    });
    svg.setAttribute('height',board.scrollHeight);svg.innerHTML=html;
    const note=!currentExp().members.length?'项目代码库 · 当前研究尚未关联执行':'';
    if($('#dependency-note').innerHTML!==note)$('#dependency-note').innerHTML=note;
  }
  function renderOutputs(){
    const e=currentExp();
    window.RWSResults.render({experiment:e,artifacts:artifactsForExp(e),evaluations:evaluationsForExp(e),analyses:analysesForExp(e),reports:reportsForExp(e)});
  }
  function syncMode(){
    ['research','code','outputs'].forEach(view=>{const el=$('#stage-'+view),active=view===state.view;el.hidden=!active;el.inert=!active;el.classList.toggle('active',active);el.classList.remove('peek','bottom');});
    $$('.mode-button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===state.view)));syncLayoutControls();
  }
  function render(){syncMode();$('#research-context').innerHTML=D.hypotheses.map(h=>`<option value="${h.id}">${esc(h.title)} · ${esc(h.displayId)}${h.isCurrent?'':' · 历史 r'+h.recordVersion}</option>`).join('');const experiments=D.experiments.filter(e=>e.hypothesisId===state.hypothesisId&&e.isCurrent);$('#experiment-context').innerHTML=experiments.length?experiments.map(e=>`<option value="${e.id}">${esc(e.title)}</option>`).join(''):'<option value="">尚无实验</option>';$('#experiment-context').value=currentExp().id||'';renderResearch();renderCode();renderOutputs();$('#research-context').value=state.taskId||state.hypothesisId;$('#context-status').textContent=currentItem().judgment?.label||currentItem().status;requestAnimationFrame(()=>{layoutResearch();layoutCode();});}
  function setView(view){
    if(!['research','code','outputs'].includes(view))return;
    state.view=view;syncMode();requestAnimationFrame(()=>{if(view==='research')layoutResearch();else if(view==='code')layoutCode();});
    status(currentItem().title+' / '+({research:'研究关系',code:'代码与执行',outputs:'产出与对比'})[view]);emitContext();
  }
  function selectH(id){
    const task=get('tasks',id),hypothesis=task?get('hypotheses',task.hypothesisId):get('hypotheses',id);if(!hypothesis)return;
    layout.research.detailOpened=true;state.taskId=task?.id||null;state.hypothesisId=hypothesis.id;state.experimentId=hypothesis.experimentId;state.draftExperiment=currentExp().id;state.showExtra=false;state.sample='all';state.outputKind='all';state.outputCollection='experiment';state.outputPages={};state.browseProjectCodes=false;
    const es=evaluationsForExp(currentExp());state.selectedExecution=es.length?{type:'evaluation',id:es[es.length-1].id}:null;
    state.selectedCodeId=executionCode(state.selectedExecution);render();status(`${task?.title||hypothesis.title} 已选中 · 三个视图共享当前研究上下文`);emitContext();
  }
  function inspect(type,id,history=true){
    const dialog=$('#reader'),previous=state.readerHistory.at(-1),inherited=dialog.open?previous?.scope||null:null;
    if(history&&previous)previous.scrollTop=dialog.scrollTop;
    let scope=history?inherited:previous?.scope||null;
    const record=window.RPEvidence.resolve(id,scope);
    if(record?.ref.type==='report')scope=window.RPEvidence.scopeForReport(id,scope);
    if(history)state.readerHistory.push({type,id,scope,scrollTop:0});
    $('#reader-back').hidden=state.readerHistory.length<2;
    $('#reader-label').textContent=`${record?.ref.id||''} · ${({hypothesis:'研究条目',code:'代码版本',run:'运行记录',evaluation:'评估记录',analysis:'分析记录',report:'报告阅读',experiment:'实验',artifact:'产物来源',protocol:'评测协议',link:'材料引用',draft:'研究对话草案'})[type]||'材料详情'}${scope?' · 固定快照':''}`;
    $('.reader-body').innerHTML=window.RPEvidence.render(type,id,{hypothesisId:state.hypothesisId,experimentId:state.draftExperiment,scope});
    if(!dialog.open)dialog.showModal();dialog.scrollTop=history?0:previous?.scrollTop||0;
  }
  function openReports(reset=true){
    if(reset)state.readerHistory=[{type:'report-library',scope:null,scrollTop:0}];
    $('#reader-back').hidden=state.readerHistory.length<2;$('#reader-label').textContent='报告库 · 固定版本';
    $('.reader-body').innerHTML=`<div class="report-library">${window.RPEvidence.batch(D.reports,r=>`<button data-action="inspect" data-type="report" data-id="${r.id}"><small>${esc(r.displayId)} / ${esc(r.version)} · 固定输入快照</small><strong>${esc(r.title)}</strong><p>${esc(r.summary.length>220?r.summary.slice(0,220)+'…':r.summary)}</p></button>`,'报告版本',20)||'<p class="evidence-empty">当前项目尚无报告。</p>'}</div>`;
    if(!$('#reader').open)$('#reader').showModal();$('#reader').scrollTop=reset?0:state.readerHistory.at(-1)?.scrollTop||0;
  }
  function closeReader(){$('#reader').close();state.readerHistory=[];}
  function draft(expId){state.draftExperiment=expId||currentExp().id;inspect('draft',state.draftExperiment);}
  document.addEventListener('click',event=>{
    const b=event.target.closest('[data-action]');
    if(!b){
      if(event.target.closest('button,a,input,select,textarea'))return;
      const card=event.target.closest('[data-select-hypothesis],[data-select-code]');
      if(card){card.dataset.selectHypothesis?selectH(card.dataset.selectHypothesis):selectCode(card.dataset.selectCode);}
      return;
    }
    const action=b.dataset.action,id=b.dataset.id;
    if(action==='view')setView(b.dataset.view);
    else if(action==='navigate'){if(b.dataset.hypothesis)selectH(b.dataset.hypothesis);closeReader();setView(b.dataset.view);}
    else if(action==='select-hypothesis')selectH(id);
    else if(action==='select-code')selectCode(id);
    else if(action==='inspect-context')inspect('hypothesis',state.taskId||state.hypothesisId);
    else if(action==='inspect')inspect(b.dataset.type,id);
    else if(action==='close-reader')closeReader();
    else if(action==='reader-back'){state.readerHistory.pop();const previous=state.readerHistory.at(-1);if(previous){if(previous.type==='report-library')openReports(false);else inspect(previous.type,previous.id,false);}}
    else if(action==='layout-overview')overview();
    else if(action==='layout-return')exitFocus();
    else if(action==='focus-region')focusRegion(b.dataset.layoutView,b.dataset.target);
    else if(action==='output-page'){const p=state.outputPages[b.dataset.kind]||{run:0,sample:0};p[b.dataset.axis]+=Number(b.dataset.direction);state.outputPages[b.dataset.kind]=p;renderOutputs();}
    else if(action==='code-relations'){state.codeRelations=b.dataset.value;renderCode();}
    else if(action==='browse-project-codes'){state.browseProjectCodes=true;renderCode();}
    else if(action==='execution')selectExecution(b.dataset.type,id);
    
    else if(action==='reports')openReports();
    else if(action==='context-report'){const r=reportsForExp(currentExp())[0];r?inspect('report',r.id):openReports();}
    else if(action==='draft')draft(b.dataset.exp);
    else if(action==='export-draft'){const a=document.createElement('a'),url=URL.createObjectURL(new Blob([$('#draft-text').value],{type:'text/plain;charset=utf-8'}));a.href=url;a.download=`rp-${state.draftExperiment}-draft.txt`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notify('草案已导出，实际执行仍需对话确认。');}
  });
  document.addEventListener('keydown',event=>{
    if(!['Enter',' '].includes(event.key)||event.target.closest('button,a,input,select,textarea'))return;
    const card=event.target.closest('[data-select-hypothesis],[data-select-code]');if(!card)return;
    event.preventDefault();card.dataset.selectHypothesis?selectH(card.dataset.selectHypothesis):selectCode(card.dataset.selectCode);
  });
  document.addEventListener('change',event=>{const el=event.target;if(el.id==='research-context')selectH(el.value);else if(el.id==='experiment-context'){state.experimentId=el.value||null;state.draftExperiment=state.experimentId;state.selectedCodeId=null;state.selectedExecution=null;state.outputCollection='experiment';state.outputPages={};render();emitContext();}else if(el.id==='output-collection'){state.outputCollection=el.value;state.sample='all';state.outputKind='all';state.outputPages={};renderOutputs();}else if(el.id==='output-grouping'){state.outputGroupBy=el.value==='condition'?'condition':'run';state.outputPages={};renderOutputs();}else if(el.id==='kind-filter'){state.outputKind=el.value;state.outputPages={};renderOutputs();}else if(el.id==='sample-filter'){state.sample=el.value;state.outputPages={};renderOutputs();}else if(el.id==='extra-filter'){state.showExtra=el.checked;renderOutputs();}else if(el.dataset.repeat){state.repeat[el.dataset.repeat]=el.value;renderOutputs();}});
  $('#reader').addEventListener('click',e=>{if(e.target===$('#reader')){const r=$('#reader').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeReader();}});
  $('#reader').addEventListener('close',()=>{state.readerHistory=[];});
  let pan=null;document.addEventListener('pointerdown',e=>{const vp=e.target.closest('#research-viewport');if(!vp||e.target.closest('button,article,a,input,select,textarea,summary,details,.foundation-pane,.region-header')||e.button!==0)return;pan={vp,x:e.clientX,y:e.clientY,left:vp.scrollLeft,top:vp.scrollTop};vp.setPointerCapture(e.pointerId);vp.classList.add('dragging');});document.addEventListener('pointermove',e=>{if(pan){pan.vp.scrollLeft=pan.left-(e.clientX-pan.x);pan.vp.scrollTop=pan.top-(e.clientY-pan.y);}});const endPan=()=>{if(pan)pan.vp.classList.remove('dragging');pan=null;};document.addEventListener('pointerup',endPan);document.addEventListener('pointercancel',endPan);
  function refreshData(event){
    const previous=event.detail.previous,projectChanged=previous?.projectId!==D.projectId;
    if(projectChanged){state.hypothesisId=null;state.experimentId=null;state.selectedCodeId=null;state.selectedExecution=null;state.readerHistory=[];state.view='research';layout.research.focus=null;layout.research.returnState=null;layout.research.detailOpened=false;layout.code.focus=null;layout.code.returnState=null;state.sample='all';state.outputKind='all';state.outputCollection='experiment';state.outputPages={};state.outputGroupBy='run';closeReader();window.RPEvidence.clear();}
    const previousRef=id=>[...(previous?.records||[]),...(previous?.references||[])].find(e=>window.RWSAdapter.key(e.ref)===id)?.ref;
    if(!get('hypotheses',state.hypothesisId)){const ref=previousRef(state.hypothesisId);state.hypothesisId=(D.hypotheses.find(h=>h.isCurrent&&window.RWSAdapter.sameRecord(h.ref,ref))||D.hypotheses.find(h=>h.isCurrent&&!h.isExternal)||D.hypotheses[0])?.id||null;}
    if(!get('experiments',state.experimentId)){const ref=previousRef(state.experimentId);state.experimentId=(D.experiments.find(e=>e.isCurrent&&window.RWSAdapter.sameRecord(e.ref,ref))||get('experiments',currentH().experimentId))?.id||null;}
    if(state.experimentId&&currentExp().hypothesisId!==state.hypothesisId)state.experimentId=currentH().experimentId||null;
    if(!get('codes',state.selectedCodeId))state.selectedCodeId=null;
    if(state.selectedExecution&&!window.RWSAdapter.find(D,state.selectedExecution.id)){const ref=previousRef(state.selectedExecution.id),group={run:'runs',evaluation:'evaluations',analysis:'analyses',report:'reports'}[state.selectedExecution.type],updated=D[group]?.find(row=>window.RWSAdapter.sameRecord(row.ref,ref));state.selectedExecution=updated?{type:state.selectedExecution.type,id:updated.id}:null;}
    if(projectChanged)layout.research.detailOpened=!!state.hypothesisId;state.draftExperiment=currentExp().id;render();status(D.projectId?(currentItem().id?currentItem().title+' · 已载入共享记录':'项目已载入 · 尚无研究条目'):'共享后端项目列表');emitContext();
  }
  window.RPWorkbench={getContext,selectHypothesis:selectH,setView,inspect,draft,getLayoutState,overview,exitFocus,setProjectStages};
  window.addEventListener('rws:data',refreshData);
  render();let relayoutFrame;const relayout=()=>{cancelAnimationFrame(relayoutFrame);relayoutFrame=requestAnimationFrame(()=>{if(state.view==='research')layoutResearch();else if(state.view==='code')layoutCode();});};new ResizeObserver(relayout).observe($('#workspace'));window.addEventListener('resize',relayout);
  status('正在连接共享后端…');
})();
