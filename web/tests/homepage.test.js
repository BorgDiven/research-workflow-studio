const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function homepage(lang = 'zh-CN') {
  function element(dataset = {}) {
    return {dataset, hidden: true, textContent: '', attributes: {}, listeners: {},
      addEventListener(type, fn) { this.listeners[type] = fn; },
      setAttribute(name, value) { this.attributes[name] = value; },
      focus() { this.focused = true; },
      scrollIntoView(options) { this.scroll = options; }};
  }
  const views = ['home', 'research', 'code', 'outputs'].map(demoView => element({demoView}));
  const entries = ['trace', 'context', 'compare'].map(demoTour => element({demoTour}));
  const ids = Object.fromEntries(['workbench-demo', 'demo', 'demo-guide', 'demo-guide-title', 'demo-guide-text'].map(id => [id, element()]));
  const close = element(), messages = [], listeners = {};
  ids['workbench-demo'].contentWindow = {postMessage(message, origin) { messages.push({message, origin}); }};
  const window = {location: {origin: 'https://example.test', hash: ''},
    matchMedia: () => ({matches: true}), addEventListener(type, fn) { listeners[type] = fn; }};
  const document = {documentElement: {lang}, getElementById: id => ids[id],
    querySelector: selector => selector === '[data-demo-guide-close]' ? close : null,
    querySelectorAll: selector => selector === '[data-demo-view]' ? views : selector === '[data-demo-tour]' ? entries : []};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../site/homepage.js'), 'utf8'), {window, document, setTimeout, clearTimeout});
  return {ids, views, messages, close,
    click(tour) { entries.find(e => e.dataset.demoTour === tour).listeners.click(); },
    load() { ids['workbench-demo'].listeners.load(); },
    receive(data, overrides = {}) { listeners.message({data, origin: window.location.origin, source: ids['workbench-demo'].contentWindow, ...overrides}); }};
}

test('homepage keeps a pending tour across iframe readiness and only confirms its acknowledged request', () => {
  const app = homepage();
  app.click('context');
  const request = app.messages.at(-1).message;
  assert.equal(request.type, 'rws-demo-tour');
  assert.equal(request.tour, 'context');
  assert.equal(app.ids['demo-guide'].dataset.state, 'loading');
  assert.equal(app.ids.demo.scroll.behavior, 'auto');
  app.load();
  app.receive({type: 'rws-demo-ready'});
  assert.deepEqual(app.messages.at(-1).message, request);
  app.receive({type: 'rws-demo-tour-ready', tour: 'context', requestId: request.requestId + 1});
  assert.equal(app.ids['demo-guide'].dataset.state, 'loading');
  app.receive({...request, type: 'rws-demo-tour-ready'});
  assert.equal(app.ids['demo-guide'].dataset.state, 'ready');
  assert.match(app.ids['demo-guide-text'].textContent, /仅展示准备好的内容/);
});

test('stale acknowledgements and messages from unrelated frames cannot change the current guide', () => {
  const app = homepage();
  app.click('trace');
  const trace = app.messages.at(-1).message;
  app.click('compare');
  const compare = app.messages.at(-1).message;
  app.receive({...trace, type: 'rws-demo-tour-ready'});
  app.receive({...compare, type: 'rws-demo-tour-ready'}, {origin: 'https://other.test'});
  app.receive({...compare, type: 'rws-demo-tour-ready'}, {source: {}});
  assert.equal(app.ids['demo-guide'].dataset.state, 'loading');
  app.receive({...compare, type: 'rws-demo-tour-ready'});
  assert.match(app.ids['demo-guide-text'].textContent, /留空表示尚未产出/);
  app.receive({type: 'rws-demo-view', view: 'code'});
  assert.equal(app.ids['demo-guide'].hidden, true);
  assert.equal(app.views.find(v => v.dataset.demoView === 'code').attributes['aria-pressed'], 'true');
});

test('manual view navigation cancels a pending guide; explicit close ignores late completion', () => {
  const app = homepage();
  app.click('context');
  const context = app.messages.at(-1).message;
  app.views.find(v => v.dataset.demoView === 'home').listeners.click();
  assert.equal(app.messages.at(-1).message.view, 'home');
  app.receive({...context, type: 'rws-demo-tour-ready'});
  assert.equal(app.ids['demo-guide'].hidden, true);
  app.click('trace');
  const trace = app.messages.at(-1).message;
  app.close.listeners.click();
  app.receive({...trace, type: 'rws-demo-tour-ready'});
  assert.equal(app.ids['demo-guide'].hidden, true);
});

test('English guidance and navigation failure stay readable without implying a completed action', () => {
  const app = homepage('en');
  app.click('context');
  const request = app.messages.at(-1).message;
  app.receive({...request, type: 'rws-demo-tour-error'});
  assert.equal(app.ids['demo-guide'].dataset.state, 'error');
  assert.match(app.ids['demo-guide-text'].textContent, /did not open/);
  app.click('context');
  app.receive({...app.messages.at(-1).message, type: 'rws-demo-tour-ready'});
  assert.match(app.ids['demo-guide-text'].textContent, /This demo only shows the prepared context/);
});
