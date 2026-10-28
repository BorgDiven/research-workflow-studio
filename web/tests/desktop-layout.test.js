'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),G=require('../graph-layout.js');
const source=fs.readFileSync(require.resolve('../app.js'),'utf8'),implementation=source.slice(source.indexOf('  function layoutCode('),source.indexOf('  function visibleCodeEndpoint('));
function arrange(height,focus=null,training=false){
  const codes=[{id:'C0',kind:'inference',parentIds:[]},{id:'C1',kind:'inference',parentIds:['C0']},{id:'CP',kind:'inference',parentIds:['C0']},{id:'C2',kind:'inference',parentIds:['C1','CP']},...['evaluation','analysis','report'].map(kind=>({id:kind,kind,parentIds:[]}))];
  if(training)codes.unshift({id:'T0',kind:'training',parentIds:[]});
  const style=()=>({setProperty(k,v){this[k]=v;}}),nodes=Object.fromEntries(codes.map(c=>['#code-'+c.id,{style:style(),dataset:{}}]));
  const lanes=[...(training?['training']:[]),'inference','evaluation','analysis','report'].map(kind=>({dataset:{kind},style:style(),content:{style:style()},querySelector(){return this.content;}}));
  const board={style:style(),dataset:{},scrollWidth:1120,get scrollHeight(){return lanes.reduce((sum,lane)=>sum+parseFloat(lane.content.style.height)+(this.dataset.density==='compact'?31:35),4);}};
  const vp={clientHeight:height,clientWidth:1120},svg={setAttribute(){}},selectors={'.lane-board':board,'.code-scroll':vp,'#code-edges':svg,...nodes};
  const run=vm.runInNewContext(`(()=>{${implementation}return layoutCode;})()`,{D:{codes,analyses:[]},layout:{code:{focus}},$:selector=>selectors[selector],$$:()=>lanes,topologyPlan:G.topologyPlan,drawCode(){}});
  run();return {board,lanes,nodes};
}
test('actual compact code layout keeps a fork/merge and all four roles within the 800px desktop work area',()=>{
  const {board,lanes,nodes}=arrange(590);
  assert.equal(board.dataset.density,'compact');assert.ok(board.scrollHeight<=590);
  assert.ok(lanes.every(lane=>lane.style['--code-height']==='80px'));
  assert.equal(nodes['#code-C1'].style.left,nodes['#code-CP'].style.left);
  assert.notEqual(nodes['#code-C1'].style.top,nodes['#code-CP'].style.top);
  assert.ok(Math.abs(parseFloat(nodes['#code-C1'].style.top)-parseFloat(nodes['#code-CP'].style.top))>=90);
  assert.ok(parseFloat(nodes['#code-C2'].style.left)>parseFloat(nodes['#code-C1'].style.left));
});
test('smaller work areas retain genuine overflow instead of scaling the same topology to pretend it fits',()=>{
  const normal=arrange(590),short=arrange(510);
  assert.equal(short.board.scrollHeight,normal.board.scrollHeight);assert.ok(short.board.scrollHeight>510);
  assert.equal(short.lanes[0].style['--code-width'],'208px');assert.equal(short.lanes[0].style['--code-height'],'80px');
});
test('tall desktops and explicit focus retain their larger card detail',()=>{
  const tall=arrange(710),focused=arrange(590,'inference');
  assert.equal(tall.board.dataset.density,'comfortable');assert.equal(tall.lanes[0].style['--code-height'],'96px');
  assert.equal(focused.board.dataset.density,'comfortable');assert.equal(focused.lanes[0].style['--code-height'],'108px');
});
test('a fifth training lane preserves legible geometry and real vertical scrolling, and can focus independently',()=>{
  const normal=arrange(510,null,true),focused=arrange(510,'training',true);assert.equal(normal.lanes.length,5);assert.equal(normal.lanes[0].dataset.kind,'training');assert.ok(normal.board.scrollHeight>510);assert.ok(normal.lanes.every(lane=>lane.style['--code-width']==='208px'&&lane.style['--code-height']==='80px'));assert.equal(focused.lanes[0].style['--code-height'],'108px');assert.equal(focused.lanes[1].style['--code-width'],'184px');assert.equal(focused.nodes['#code-C1'].style.left,focused.nodes['#code-CP'].style.left);assert.notEqual(focused.nodes['#code-C1'].style.top,focused.nodes['#code-CP'].style.top);
});
