/* Generated demo only: keep the real canvas and readers, hide write controls. */
(() => {
  'use strict';
  window.RWS_PUBLIC_DEMO = true;
  const mutations = {
    studio: ['new-project','new-research','edit-research','new-experiment','edit','stages','apply-draft','dismiss-draft','reuse-artifact','remove-usage','confirm-remove-usage','add-material','link-implementation','add-implementation-link','remove-implementation-link'],
    contract: ['new','edit','implement','add-port','remove-port'],
    amendment: ['apply','dismiss'], results: ['save','analysis','report'],
    resource: ['new','edit','propose','approve','dismiss','plan-run'],
    process: ['freeze'],
  };
  const selector = Object.entries(mutations).flatMap(([group, actions]) => actions.map(action => `[data-${group}="${action}"]`)).join(',');
  // Installed before production listeners, so even a scripted click cannot open
  // a misleading editable form. The adapter independently rejects every write.
  document.addEventListener('click', event => {
    if (event.target.closest(selector)) {
      event.preventDefault(); event.stopImmediatePropagation();
      window.RWSUI?.notify('虚构只读演示：安装本地版本后可登记与修改研究。');
    }
  }, true);
  document.addEventListener('submit', event => {
    event.preventDefault(); event.stopImmediatePropagation();
    window.RWSUI?.notify('虚构只读演示不保存或执行任务。');
  }, true);
  const params = new URLSearchParams(location.search);
  let updateURL = false;
  // The live application accepts these as direct entry points into write/review
  // forms. Remove them before studio.js reads its startup parameters.
  for (const name of ['stages', 'review']) {
    if (params.has(name)) { params.delete(name); updateURL = true; }
  }
  if (!params.has('projectId')) {
    params.set('projectId', 'showcase-shapes');
    updateURL = true;
  }
  if (updateURL) history.replaceState(null, '', location.pathname + '?' + params + location.hash);
  let ready = false, queued = null, running = false, sequence = 0, lastView = null, initial = true;
  const post = message => { if (window.parent !== window) window.parent.postMessage(message, location.origin); };
  function publishView() {
    if (!ready) return;
    const view = document.body.dataset.projectSurface === 'home' ? 'home' : window.RPWorkbench.getContext().view;
    if (view !== lastView) { lastView = view; post({type: 'rws-demo-view', view}); }
  }
  function labels() {
    document.querySelectorAll(selector).forEach(button => { button.hidden = true; button.disabled = true; });
    const phase = document.querySelector('#header-project-phase');
    if (phase) phase.title = '虚构项目中预设的推进阶段；演示不可修改';
    document.querySelectorAll('[data-studio="context"]').forEach(button => {
      if (['研究对话','准备对话','准备研究对话'].includes(button.textContent.trim())) button.textContent = '查看上下文';
      if (button.hasAttribute('aria-label')) button.setAttribute('aria-label', '查看演示上下文');
    });
    const context = document.querySelector('#context-text');
    if (context) context.readOnly = true;
  }
  function waitFor(predicate, message, action = () => {}) {
    // Observe real dialog/project changes, not network responses or guessed
    // delays. The bound also lets a failed context request release the queue.
    return new Promise((resolve, reject) => {
      let timer;
      const finish = error => { observer.disconnect(); clearTimeout(timer); error ? reject(error) : resolve(); };
      const check = () => { try { if (predicate()) finish(); } catch (error) { finish(error); } };
      const observer = new MutationObserver(check);
      observer.observe(document.body, {childList:true, subtree:true, attributes:true});
      timer = setTimeout(() => finish(new Error(message)), 5000);
      try { action(); check(); } catch (error) { finish(error); }
    });
  }
  function click(selector) {
    const button = document.querySelector(selector);
    if (!button || button.disabled) throw new Error('演示控件尚未准备好，请重试。');
    button.click();
  }
  function closeOverlays() {
    if (document.querySelector('#studio-dialog')?.open) click('[data-studio="close-dialog"]');
    if (document.querySelector('#guidance-dialog')?.open) click('[data-studio="close-guide"]');
    if (document.querySelector('#reader')?.open) click('[data-action="close-reader"]');
    document.querySelector('#project-context-popover')?.hidePopover();
  }
  function selectResearch() {
    const research = window.RP_DATA.hypotheses.find(row => row.ref.id === 'H5' && row.isCurrent);
    if (!research) throw new Error('演示研究条目未能载入，请重试。');
    window.RPWorkbench.selectHypothesis(research.id);
    if (window.RPWorkbench.getContext().hypothesisId !== research.id) throw new Error('演示研究尚未选中，请重试。');
    return research.id;
  }
  async function navigate(view, select = false) {
    if (window.RWSUI.isBusy()) await waitFor(() => !window.RWSUI.isBusy(), '项目仍在切换，请重试。');
    closeOverlays();
    if (view === 'home') {
      click('[data-studio="home"]');
      return;
    }
    if (document.body.dataset.projectSurface === 'home' || window.RP_DATA.projectId !== 'showcase-shapes') {
      await waitFor(() => document.body.dataset.projectSurface === 'workbench' && window.RP_DATA.projectId === 'showcase-shapes' && !window.RWSUI.isBusy(),
        '演示项目未能打开，请重试。', () => click('[data-studio="switch-project"][data-project="showcase-shapes"]'));
    }
    const wb = window.RPWorkbench;
    if (view === 'outputs') {
      selectResearch();
      window.RWSResults.reset();
      wb.setView('outputs');
      const comparison = window.RP_DATA.comparisons.find(row => row.ref.id === 'CMP-SHAPES');
      const scope = document.querySelector('[data-results-field="scope"]');
      if (!comparison || !scope) throw new Error('三方法对比未能打开，请重试。');
      scope.value = comparison.id;
      scope.dispatchEvent(new Event('change', {bubbles:true}));
      if (document.querySelector('[data-results-field="scope"]')?.value !== comparison.id) throw new Error('对比视图未能切换，请重试。');
    } else {
      wb.setView(view);
      if (select) { wb.overview?.(); selectResearch(); }
    }
    if (wb.getContext().view !== view) throw new Error('演示视图未能切换，请重试。');
    labels(); publishView();
  }
  async function runQueue() {
    if (!ready || running) return;
    running = true;
    try {
      while (queued) {
        const request = queued;
        queued = null;
        const reply = type => post({type, tour:request.tour, ...(Number.isSafeInteger(request.requestId) ? {requestId:request.requestId} : {})});
        try {
          await navigate(request.view, request.tour === 'trace' || request.tour === 'context');
          if (request.sequence !== sequence) continue;
          if (request.tour === 'context') {
            await waitFor(() => document.querySelector('#studio-dialog')?.open && !!document.querySelector('#context-text')?.value,
              '上下文未能打开，请重试。', () => click('.header-actions [data-studio="context"]'));
          }
          if (request.tour && request.sequence === sequence) reply('rws-demo-tour-ready');
        } catch (error) {
          if (request.sequence === sequence) {
            if (request.tour) reply('rws-demo-tour-error');
            window.RWSUI?.notify(error.message || '演示暂未打开，请重试。');
          }
        }
      }
    } finally { running = false; }
  }
  function enqueue(request) {
    queued = {...request, sequence:++sequence};
    runQueue();
  }
  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.origin !== location.origin || !event.data) return;
    const message = event.data;
    if (message.type === 'rws-demo-navigate' && ['home','research','code','outputs'].includes(message.view)) enqueue({view:message.view});
    if (message.type === 'rws-demo-tour' && ['trace','context','compare'].includes(message.tour)) enqueue({tour:message.tour, view:message.tour === 'compare' ? 'outputs' : 'research', requestId:message.requestId});
  });
  window.addEventListener('rp:context-change', () => queueMicrotask(() => { labels(); publishView(); }));
  window.addEventListener('rws:surface-change', () => queueMicrotask(() => { labels(); publishView(); }));
  window.addEventListener('rws:data', () => queueMicrotask(() => {
    if (initial) {
      initial = false;
      const research = window.RP_DATA.hypotheses.find(row => row.ref.id === 'H5' && row.isCurrent);
      if (research) window.RPWorkbench.selectHypothesis(research.id);
    }
    labels();
    if (!ready) { ready = true; post({type:'rws-demo-ready'}); }
    publishView();
    runQueue();
  }));
  document.addEventListener('DOMContentLoaded', () => {
    const bar = document.createElement('aside');
    bar.className = 'public-demo-notice';
    bar.setAttribute('aria-label', '演示边界');
    bar.innerHTML = '<strong>虚构 · 离线 · 只读</strong><span>图形与数值人为编排，未运行模型。可选择节点、聚焦视图、查看材料与报告。</span><a href="../index.html" target="_top">返回官网 ↗</a><button type="button" data-demo-reset>重置演示</button>';
    document.body.prepend(bar);
    bar.querySelector('[data-demo-reset]').addEventListener('click', () => location.replace('index.html?projectId=showcase-shapes'));
    const observer = new MutationObserver(labels);
    observer.observe(document.body, {childList:true, subtree:true});
    labels();
  });
})();
