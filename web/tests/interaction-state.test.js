'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),I=require('../interaction-state.js');

const context=()=>({hypothesisId:'H2',experimentId:'E2',taskId:'T2',selectedCodeId:null,selectedExecution:null,focus:'inference',scroll:{left:190,top:52},readerHistory:[]});
test('a second direct code click clears code and execution without changing research, focus or scroll',()=>{
  const state=context(),before=structuredClone(state);
  assert.equal(I.selectCode(state,'C1',{type:'run',id:'R1'},true),true);
  assert.equal(I.selectCode(state,'C1',{type:'run',id:'R1'},true),false);
  assert.deepEqual(state,before);
});
test('navigation to the selected implementation ensures selection instead of toggling it off',()=>{
  const state=context(),execution={type:'evaluation',id:'EV2'};
  I.selectCode(state,'C-evaluation',execution);
  I.selectCode(state,'C-evaluation',execution);
  assert.equal(state.selectedCodeId,'C-evaluation');
  assert.deepEqual(state.selectedExecution,execution);
  assert.notEqual(state.selectedExecution,execution);
});
test('choosing a different implementation replaces a stale dependency selection',()=>{
  const state=context();I.selectCode(state,'C1',{type:'run',id:'R1'},true);
  I.selectCode(state,'C2',{type:'run',id:'R2'},true);
  assert.deepEqual(state.selectedExecution,{type:'run',id:'R2'});
  I.selectCode(state,'C3',null,true);
  assert.equal(state.selectedExecution,null);assert.equal(state.selectedCodeId,'C3');
});
test('manual analysis toggles without a fake implementation and still supports navigation',()=>{
  const state=context();I.selectExecution(state,'analysis','A1',null,true);
  assert.equal(state.selectedCodeId,null);assert.deepEqual(state.selectedExecution,{type:'analysis',id:'A1'});
  assert.equal(I.selectExecution(state,'analysis','A1',null),true);
  assert.equal(I.selectExecution(state,'analysis','A1',null,true),false);
  assert.deepEqual(state,context());
});
test('Escape closes reading before cancelling selection, while forms retain native handling',()=>{
  const selected={modalOpen:false,editing:false,readerOpen:true,codeView:true,hasSelection:true};
  assert.equal(I.escapeAction(selected),'close-reader');
  assert.equal(I.escapeAction({...selected,readerOpen:false}),'clear-selection');
  assert.equal(I.escapeAction({...selected,readerOpen:false,codeView:false}),null);
  assert.equal(I.escapeAction({...selected,modalOpen:true}),null);
  assert.equal(I.escapeAction({...selected,editing:true}),null);
});
test('the reader close decision leaves selection and research context untouched',()=>{
  const state=context();I.selectExecution(state,'report','P1','C-report');
  const before=structuredClone(state);
  assert.equal(I.escapeAction({modalOpen:false,editing:false,readerOpen:true,codeView:true,hasSelection:true}),'close-reader');
  assert.deepEqual(state,before);
});
test('fixed report scope follows nested references and back, but never leaks into an outside click',()=>{
  const snapshot={records:[{ref:{projectId:'p',type:'code',id:'C1',version:1}}]},previous={type:'report',scope:snapshot};
  assert.equal(I.readerScope(previous,{inside:true}),snapshot);
  assert.equal(I.readerScope(previous,{history:false}),snapshot);
  assert.equal(I.readerScope(previous,{inside:false}),null);
  assert.equal(I.readerScope(null,{inside:true}),null);
});
test('references opened from a modal remain above the unsaved form, ordinary readers use the dock',()=>{
  assert.equal(I.readerPresentation({hasModal:false,readerModal:false}),'dock');
  assert.equal(I.readerPresentation({hasModal:true,readerModal:false}),'modal');
  assert.equal(I.readerPresentation({hasModal:true,readerModal:true}),'modal');
  assert.equal(I.readerPresentation({hasModal:false,readerModal:true}),'modal');
});
