"use strict";

(() => {
  const frame = document.getElementById("workbench-demo");
  const viewButtons = Array.from(document.querySelectorAll("[data-demo-view]"));
  const allowedViews = new Set(viewButtons.map((button) => button.dataset.demoView));
  let requestedView = "research";

  function reflectView(view) {
    if (!allowedViews.has(view)) return;
    viewButtons.forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.demoView === view));
    });
  }

  function navigateDemo(view) {
    if (!allowedViews.has(view) || !frame?.contentWindow) return;
    requestedView = view;
    frame.contentWindow.postMessage({ type: "rws-demo-navigate", view }, window.location.origin);
  }

  viewButtons.forEach((button, index) => {
    button.addEventListener("click", () => navigateDemo(button.dataset.demoView));
    button.addEventListener("keydown", (event) => {
      let nextIndex;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % viewButtons.length;
      if (event.key === "ArrowLeft") nextIndex = (index - 1 + viewButtons.length) % viewButtons.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = viewButtons.length - 1;
      if (nextIndex === undefined) return;
      event.preventDefault();
      viewButtons[nextIndex].focus();
    });
  });

  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin || event.source !== frame?.contentWindow) return;
    const message = event.data;
    if (!message || typeof message !== "object") return;
    if (message.type === "rws-demo-ready") navigateDemo(requestedView);
    if (message.type === "rws-demo-view" && allowedViews.has(message.view)) {
      requestedView = message.view;
      reflectView(message.view);
    }
  });

  frame?.addEventListener("load", () => navigateDemo(requestedView));

  const quickstart = document.getElementById("start");
  function openQuickstart() {
    if (quickstart) quickstart.open = true;
  }
  document.querySelectorAll('a[href="#start"]').forEach((link) => {
    link.addEventListener("click", openQuickstart);
  });
  if (window.location.hash === "#start") openQuickstart();
  window.addEventListener("hashchange", () => {
    if (window.location.hash === "#start") openQuickstart();
  });

  document.querySelectorAll("[data-copy-target]").forEach((button) => {
    const originalLabel = button.textContent;
    let restoreLabel;
    button.addEventListener("click", async () => {
      const code = document.getElementById(button.dataset.copyTarget);
      if (!code) return;
      clearTimeout(restoreLabel);
      let label;
      try {
        await navigator.clipboard.writeText(code.textContent.trim());
        label = button.dataset.copied;
      } catch {
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(code);
        selection?.removeAllRanges();
        selection?.addRange(range);
        code.focus();
        label = button.dataset.copyFailed;
      }
      button.textContent = label;
      const status = document.getElementById("copy-status");
      if (status) status.textContent = label;
      restoreLabel = setTimeout(() => { button.textContent = originalLabel; }, 2400);
    });
  });
})();
