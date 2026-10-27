'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),G=require('../graph-layout.js');
test('independent implementations use the available lane width without changing node size',()=>{
  const nodes=Array.from({length:15},(_,i)=>({id:'C'+String(i).padStart(2,'0')})),p=G.topologyPlan(nodes,[],208,118,24,18,940);
  assert.equal(p.positions.length,15);assert.equal(new Set(p.positions.map(p=>p.x)).size,4);assert.equal(new Set(p.positions.map(p=>p.y)).size,4);
  assert.equal(p.width,904);assert.equal(p.height,526);assert.ok(p.positions.every(p=>p.x>=0&&p.x+208<=940));
});
test('packing preserves a complete branched component even when it exceeds the viewport',()=>{
  const nodes=['A','B','C','D','E'].map(id=>({id})),edges=[['A','B'],['A','C'],['B','D'],['C','D']],p=G.topologyPlan(nodes,edges,180,100,24,16,300),by=Object.fromEntries(p.positions.map(x=>[x.id,x]));
  assert.equal(by.A.component,by.D.component);assert.equal(by.A.x,0);assert.equal(by.D.x,408);assert.equal(p.width,588);assert.ok(by.E.y>=216);
  assert.ok(by.B.y+100<=by.C.y);assert.notEqual(by.E.component,by.A.component);
});
test('research branches use vertical ranks and retain fork and merge relationships',()=>{
  const nodes=['H1','H2','H3','H4'].map(id=>({id})),edges=[['H1','H2'],['H1','H3'],['H2','H4'],['H3','H4']],p=G.topologyPlan(nodes,edges,184,124,24,18,600,'vertical'),by=Object.fromEntries(p.positions.map(x=>[x.id,x]));
  assert.equal(p.width,392);assert.equal(p.height,408);assert.equal(by.H1.y,0);assert.equal(by.H2.y,142);assert.equal(by.H3.y,142);assert.equal(by.H4.y,284);assert.equal(by.H1.x,by.H4.x);assert.ok(by.H2.x+184<=by.H3.x);
});
test('empty stages take no node area and cyclic graphs fail explicitly',()=>{
  assert.deepEqual(G.topologyPlan([],[],180,100,24,16,800),{width:0,height:0,positions:[]});
  assert.throws(()=>G.topologyPlan([{id:'a'},{id:'b'}],[['a','b'],['b','a']],180,100,24,16,800),/cycle/);
});
