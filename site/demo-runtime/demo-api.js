/* Read only data adapter for the generated, fictional public showcase. */
(() => {
  'use strict';
  let snapshot = null, loading = null;
  const clone = value => JSON.parse(JSON.stringify(value));
  const key = ref => JSON.stringify([ref.projectId, ref.type, ref.id, ref.version]);
  const error = (code, message) => Object.assign(new Error(message), {code});
  const readonly = () => error('demo_readonly', '这是虚构只读演示，不能登记、修改或执行。请安装本地版本开展自己的研究。');
  async function data() {
    if (!loading) loading = fetch('showcase.json', {credentials: 'omit'}).then(async response => {
      if (!response.ok) throw error('demo_unavailable', '演示数据未能载入，请重新打开页面。');
      const value = await response.json();
      if (value.schemaVersion !== 1 || value.mode !== 'offline-fictional-readonly') throw error('demo_invalid', '演示数据格式不匹配。');
      return value;
    }).catch(failure => { loading = null; throw failure; });
    return loading;
  }
  function resolve(db, ref) {
    if (!ref || typeof ref !== 'object') throw error('demo_not_found', '未指定演示记录。');
    const found = ref.version == null ? Object.values(db.records).filter(e => ['projectId','type','id'].every(field => e.ref[field] === ref[field])).sort((a,b) => b.ref.version-a.ref.version)[0] : Object.hasOwn(db.records, key(ref)) ? db.records[key(ref)] : null;
    if (!found) throw error('demo_not_found', '该记录不在虚构演示中。');
    return found;
  }
  async function read(projectId) {
    const db = await data(), next = projectId ? Object.hasOwn(db.snapshots, projectId) ? db.snapshots[projectId] : null : db.home;
    if (!next) throw error('demo_not_found', '该项目不在虚构演示中。');
    return clone(next);
  }
  async function call(name, args = {}) {
    const db = await data();
    if (db.mutationNames.includes(name)) throw readonly();
    let result;
    if (name === 'rws_project_list') result = db.home.projects;
    else if (name === 'rws_record_get') result = resolve(db, args.ref);
    else if (name === 'rws_get_context') {
      if (Object.keys(args).some(k => !['projectId','researchRef','experimentRef','selectionRefs'].includes(k))) throw error('demo_unsupported', '演示不支持这些上下文参数。');
      const experiment = args.experimentRef ? resolve(db, args.experimentRef) : null;
      const research = args.researchRef ? resolve(db, args.researchRef) : experiment ? resolve(db, experiment.record.researchRef) : null;
      if (experiment && (experiment.ref.type !== 'experiment' || experiment.ref.projectId !== args.projectId) || research && (research.ref.type !== 'research' || research.ref.projectId !== args.projectId)) throw error('demo_not_found', '研究与实验必须属于当前演示项目。');
      if (experiment && ['projectId','type','id'].some(field => experiment.record.researchRef[field] !== research.ref[field])) throw error('demo_unsupported', '所选研究与实验不匹配。');
      const context = db.contexts[JSON.stringify([args.projectId, research ? key(research.ref) : null, experiment ? key(experiment.ref) : null])];
      if (!Array.isArray(args.selectionRefs || [])) throw error('demo_unsupported', '演示选择必须为记录列表。');
      const selected = (args.selectionRefs || []).map(ref => key(resolve(db, ref).ref));
      const variant = context?.variants[JSON.stringify(selected)];
      if (!variant) throw error('demo_unsupported', '该上下文组合未包含在演示快照中；请选择界面中的研究或代码。');
      result = {...context.base, objectCount: variant.objectCount, objectsTruncated: variant.objectsTruncated, objects: variant.objectIndexes.map(index => db.contextObjects[index])};
    } else if (name === 'rws_metrics_query') {
      const saved=db.metrics?.[args.projectId],refs=args.runRefs||[];
      if(!saved||!refs.length||refs.length>20)throw error('demo_unsupported','请选择演示中的过程记录。');
      const chosen=new Map(refs.map(ref=>{const resolved=resolve(db,ref);if(ref.type!=='run'||ref.projectId!==args.projectId)throw error('demo_unsupported','运行必须属于当前项目。');return [ref.id,resolved.ref];}));
      const through=args.throughSequence??saved.throughSequence,limit=args.limit??1000,offset=args.offset??0;
      if(!Number.isInteger(through)||through<0||through>saved.throughSequence||!Number.isInteger(limit)||limit<1||limit>5000||!Number.isInteger(offset)||offset<0)throw error('demo_unsupported','过程查询范围无效。');
      const all=saved.series.filter(s=>chosen.has(s.runRef.id)&&(!args.metricIds?.length||args.metricIds.includes(s.metricId))).flatMap((s,index)=>s.points.filter(p=>p.sequence<=through&&(args.fromX===undefined||p.x>=args.fromX)&&(args.toX===undefined||p.x<=args.toX)).map(p=>({s,index,p}))).sort((a,b)=>a.p.sequence-b.p.sequence);
      const selected=new Map();all.slice(offset,offset+limit).forEach(({s,index,p})=>{if(!selected.has(index))selected.set(index,{...s,runRef:chosen.get(s.runRef.id),points:[]});selected.get(index).points.push(p);});
      const series=[...selected.values()].map(s=>({...s,points:s.points.sort((a,b)=>a.x-b.x)}));
      const aligned=saved.aligned.flatMap(group=>{const matches=series.filter(s=>group.columns.some(c=>c.runRef.id===s.runRef.id)&&s.metricId===group.metricId&&s.split===group.split&&s.sampleId===group.sampleId);if(!matches.length)return [];const xs=[...new Set(matches.flatMap(s=>s.points.map(p=>p.x)))].sort((a,b)=>a-b);return [{...group,xs,columns:matches.map(s=>({runRef:s.runRef,values:xs.map(x=>s.points.find(p=>p.x===x)?.value??null)}))}];});
      result={series,aligned,total:all.length,offset,limit,truncated:offset+limit<all.length,throughSequence:through};
    } else throw error('demo_unsupported', '此接口不在只读演示中提供。');
    return clone({ok: true, operation: name, result});
  }
  async function mutate() { throw readonly(); }
  async function session() { throw readonly(); }
  function apply(next) {
    const previous = snapshot;
    snapshot = clone(next);
    const projected = window.RWSAdapter.project(snapshot);
    Object.keys(window.RP_DATA).forEach(k => delete window.RP_DATA[k]);
    Object.assign(window.RP_DATA, projected);
    window.dispatchEvent(new CustomEvent('rws:data', {detail: {snapshot, previous}}));
  }
  window.RWSLive = {read, apply, call, mutate, session, getSnapshot: () => snapshot && clone(snapshot)};
})();
