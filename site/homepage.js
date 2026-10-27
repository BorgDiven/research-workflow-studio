"use strict";

(() => {
  const frame = document.getElementById("workbench-demo");
  const viewButtons = Array.from(document.querySelectorAll("[data-demo-view]"));
  const allowedViews = new Set(viewButtons.map((button) => button.dataset.demoView));
  const tourButtons = Array.from(document.querySelectorAll("[data-demo-tour]"));
  const guide = document.getElementById("demo-guide");
  const guideTitle = document.getElementById("demo-guide-title");
  const guideText = document.getElementById("demo-guide-text");
  const english = document.documentElement.lang === "en";
  const tours = english ? {
    trace: {view: "research", title: "Follow a question to its evidence", text: "Start with the project foundation, then select a research node. Its summary connects the question to experiments, materials, evaluations and reports."},
    context: {view: "research", title: "See what AI can pick up", text: "The dialog contains the project goal, current research, recorded evidence and suggested next steps. A connected AI client can read this context in your installed workspace. This demo only shows the prepared context."},
    compare: {view: "outputs", title: "Compare methods on the same samples", text: "Each row is one sample; each column is a method. Empty cells mean no output exists. Use 来源 (Source) to inspect code and settings, or 阅读报告 (Read report) to see the pinned evidence."},
  } : {
    trace: {view: "research", title: "沿着研究问题，找到实验依据", text: "先看项目基础，再点一个研究节点。右侧的实验、材料、评估和报告，能让你沿着证据回看这次研究。"},
    context: {view: "research", title: "看看 AI 接手时能拿到什么", text: "弹窗包含项目目标、当前研究、已登记证据和下一步建议。安装并接入 AI 后，它可以读取这些上下文；这里仅展示准备好的内容。"},
    compare: {view: "outputs", title: "把不同方法，放到同一批样本上比较", text: "同一行是同一样本，每列是不同方法。留空表示尚未产出；点“来源”查看代码与配置，点“阅读报告”查看当时采用的证据。"},
  };
  let requestedView = "research";
  let requestId = 0, pendingTour = null, activeTour = null;

  function dismissGuide() {
    pendingTour = null;
    activeTour = null;
    if (guide) { guide.hidden = true; guide.setAttribute("aria-busy", "false"); }
  }

  function showGuide(tour, state) {
    if (!guide || !Object.hasOwn(tours, tour)) return;
    guide.hidden = false;
    guide.dataset.state = state;
    guide.setAttribute("aria-busy", String(state === "loading"));
    guideTitle.textContent = tours[tour].title;
    guideText.textContent = state === "loading" ? (english ? "Opening the example…" : "正在打开对应示例…")
      : state === "error" ? (english ? "The example did not open. Try again, or use Open demo to explore it directly." : "示例未能打开，请重试，或通过“独立打开”进入工作台。")
      : tours[tour].text;
  }

  function sendRequested() {
    if (!frame?.contentWindow) return;
    frame.contentWindow.postMessage(pendingTour
      ? {type: "rws-demo-tour", ...pendingTour}
      : {type: "rws-demo-navigate", view: requestedView}, window.location.origin);
  }

  function reflectView(view) {
    if (!allowedViews.has(view)) return;
    viewButtons.forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.demoView === view));
    });
  }

  function navigateDemo(view) {
    if (!allowedViews.has(view) || !frame?.contentWindow) return;
    dismissGuide();
    requestedView = view;
    sendRequested();
  }

  tourButtons.forEach((button) => button.addEventListener("click", () => {
    const tour = button.dataset.demoTour;
    if (!Object.hasOwn(tours, tour)) return;
    pendingTour = {tour, requestId: ++requestId};
    activeTour = null;
    requestedView = tours[tour].view;
    showGuide(tour, "loading");
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    document.getElementById("demo")?.scrollIntoView({behavior: reducedMotion ? "auto" : "smooth", block: "start"});
    guide?.focus({preventScroll: true});
    sendRequested();
  }));
  document.querySelector("[data-demo-guide-close]")?.addEventListener("click", dismissGuide);

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
    if (message.type === "rws-demo-ready") sendRequested();
    if (message.type === "rws-demo-view" && allowedViews.has(message.view)) {
      requestedView = message.view;
      reflectView(message.view);
      if (activeTour && tours[activeTour].view !== message.view) dismissGuide();
    }
    if (["rws-demo-tour-ready", "rws-demo-tour-error"].includes(message.type)
      && pendingTour?.tour === message.tour && pendingTour.requestId === message.requestId) {
      const tour = pendingTour.tour;
      pendingTour = null;
      activeTour = message.type === "rws-demo-tour-ready" ? tour : null;
      showGuide(tour, activeTour ? "ready" : "error");
    }
  });

  frame?.addEventListener("load", () => {
    if (!pendingTour) dismissGuide();
    sendRequested();
  });

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
