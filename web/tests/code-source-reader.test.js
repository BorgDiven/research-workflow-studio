'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),A=require('../live-model.js');
const ref=(type,id)=>({projectId:'p',type,id,version:1});
function setup(records){const D=A.project({projectId:'p',projects:[{id:'p',name:'Project'}],records}),c={window:{RP_DATA:D,RWSAdapter:A}};vm.runInNewContext(fs.readFileSync(require.resolve('../evidence.js'),'utf8'),c);return c.window.RPEvidence;}
test('historical source fields are readable without claiming a registered runnable interface',()=>{
  const code={ref:ref('code','C'),record:{title:'Method',kind:'inference',version:'old',description:'Registered method explanation',source:{commit:'historical-commit',locatedGitRepositories:['/opt/private/repo'],sourceFiles:'infer.py',manifestUri:'/materials/project/manifest.json',receiptUri:'/materials/project/receipt.json',repository:'/opt/private/repo'}}},R=setup([code]),html=R.render('code',A.key(code.ref));
  assert.match(html,/Registered method explanation/);assert.match(html,/历史来源 commit/);assert.match(html,/historical-commit/);assert.match(html,/\/opt\/private\/repo/);assert.match(html,/infer.py/);assert.match(html,/href="\/materials\/project\/manifest.json"/);assert.match(html,/href="\/materials\/project\/receipt.json"/);assert.match(html,/尚未登记/);assert.doesNotMatch(html,/href="\/opt/);
});
test('source links reject local and unsafe addresses while displaying original locations as text',()=>{
  const R=setup([]),s=R.codeSource({source:{uri:'file:///work/method.py',url:'javascript:alert(1)',repository:'/srv/private/repo',locatedGitRepositories:'/srv/private/repo',sourceFiles:{module:'/srv/method.py'},manifestUri:'/materials/p/manifest.json',receiptUri:'https://example.org/receipt'}});
  assert.equal(s.locations.length,3);assert.equal(s.links.length,2);assert.ok(s.links.every(x=>x.url.startsWith('/materials/')||x.url.startsWith('https://')));
  assert.equal(R.codeSource({source:{manifestUri:'/materials/../../private/source.py'}}).links.length,0);
});
test('code provenance includes effective bindings and report generators',()=>{
  const code={ref:ref('code','C'),record:{title:'Renderer',kind:'report',version:'1',commit:'registered',source:{commit:'historic'}}},report={ref:ref('report','RP'),record:{title:'Rendered report',markdown:'Report',generatorCodeRef:code.ref}},run={ref:ref('run','R'),record:{title:'Legacy run',codeRef:ref('code','OTHER')},effectiveRecord:{title:'Corrected producer',codeRef:code.ref}},R=setup([code,report,run]),html=R.render('code',A.key(code.ref));
  assert.match(html,/Git commit/);assert.match(html,/registered/);assert.match(html,/Rendered report/);assert.match(html,/Corrected producer/);assert.match(html,/来源凭据 · 2 项/);
});
