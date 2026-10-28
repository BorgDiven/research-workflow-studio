/* Private design preview only; canonical code/results remain in their readers. */
(() => {
  'use strict';
  const A = window.RWSAdapter;
  function experiment(row) {
    const config = row.config || {};
    if (!config.base_model) return '';
    const model = [config.base_model, config.model_version].filter(Boolean).join(' · ');
    const methods = (config.comparison_code_refs || []).map(ref =>
      `<button type="button" class="evidence-link" data-action="inspect" data-type="code" data-id="${A.esc(A.key(ref))}">${A.esc(A.label(window.RP_DATA, ref))} ↗</button>`).join('');
    return `<div class="preview-experiment-context"><small>使用模型</small><strong>${A.esc(model)}</strong>${config.comparison_role ? `<p>${A.esc(config.comparison_role)}</p>` : ''}${methods ? `<small>本实验比较的方法</small><div class="preview-method-links">${methods}</div>` : ''}</div>`;
  }
  window.RWSFoundationPreview = {experiment};
})();
