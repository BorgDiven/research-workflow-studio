/* Generated demo only: keep the real canvas and readers, hide write controls. */
(() => {
  'use strict';
  const mutations = {
    studio: ['new-project','new-research','edit-research','new-experiment','edit','stages','apply-draft','dismiss-draft','reuse-artifact','remove-usage','confirm-remove-usage','add-material'],
    contract: ['new','edit','implement','add-port','remove-port'],
    amendment: ['apply','dismiss'], results: ['save','analysis','report'],
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
  let ready = false, queued = null, lastView = null, initial = true;
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
  function waitForData(projectId) {
    return new Promise(resolve => {
      const loaded = event => {
        if (event.detail.snapshot.projectId === projectId) {
          window.removeEventListener('rws:data', loaded);
          queueMicrotask(resolve);
        }
      };
      window.addEventListener('rws:data', loaded);
    });
  }
  async function navigate(view) {
    if (!ready) { queued = view; return; }
    if (view === 'home') {
      document.querySelector('[data-studio="home"]').click();
      return;
    }
    if (document.body.dataset.projectSurface === 'home' || window.RP_DATA.projectId !== 'showcase-shapes') {
      const button = document.querySelector('[data-studio="switch-project"][data-project="showcase-shapes"]');
      if (!button || window.RWSUI.isBusy()) return;
      const loaded = waitForData('showcase-shapes');
      button.click();
      await loaded;
    }
    const wb = window.RPWorkbench;
    if (view === 'outputs') {
      const research = window.RP_DATA.hypotheses.find(row => row.ref.id === 'H5' && row.isCurrent);
      if (research) wb.selectHypothesis(research.id);
      window.RWSResults.reset();
      wb.setView('outputs');
      const comparison = window.RP_DATA.comparisons.find(row => row.ref.id === 'CMP-SHAPES');
      const scope = document.querySelector('[data-results-field="scope"]');
      if (comparison && scope) { scope.value = comparison.id; scope.dispatchEvent(new Event('change', {bubbles:true})); }
    } else wb.setView(view);
    labels(); publishView();
  }
  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.origin !== location.origin || !event.data || event.data.type !== 'rws-demo-navigate' || !['home','research','code','outputs'].includes(event.data.view)) return;
    navigate(event.data.view);
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
    if (queued) { const next = queued; queued = null; navigate(next); }
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
