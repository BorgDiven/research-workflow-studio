'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),I=require('../interaction-state.js');
const source=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
const implementation=(start,end)=>source.slice(source.indexOf('  function '+start+'('),source.indexOf('  function '+end+'('));
function harness(hasModal=false){
  const classes=new Set(),attributes={},styles={},calls=[],input={value:'Unsaved research statement'},trigger={isConnected:true,focus(){document.activeElement=this;calls.push('trigger-focus');}};
  const dialog={open:false,classList:{contains:x=>classes.has(x),toggle(x,value){value?classes.add(x):classes.delete(x);return value;},remove(...xs){xs.forEach(x=>classes.delete(x));}},style:{setProperty(k,v){styles[k]=v;}},setAttribute(k,v){attributes[k]=v;},contains(el){return el===body;},show(){this.open=true;calls.push('show');},showModal(){this.open=true;calls.push('showModal');},close(){this.open=false;calls.push('close');}};
  const body={focus(){document.activeElement=this;calls.push('body-focus');}},control={setAttribute(){},hidden:false},nodes={'#reader':dialog,'#workspace':{clientHeight:600},'#reader-resize':control,'#reader-maximize':control,'.reader-body':body};
  const document={activeElement:trigger,querySelector(){return hasModal?{input}:null;},getElementById(){return null;}};
  const state={selectedCodeId:'C1',selectedExecution:{type:'run',id:'R1'},hypothesisId:'H2',experimentId:'E2',readerHistory:[{type:'artifact',id:'A1'}]};
  const controller=vm.runInNewContext(`(()=>{let readerTrigger=null,readerHeight=320;${implementation('readerBounds','maximizeReader')}${implementation('closeReader','draft')}return {showReader,closeReader,setReaderHeight,getPreferredHeight:()=>readerHeight};})()`,{I,$:s=>nodes[s],document,state});
  return {controller,dialog,attributes,calls,document,trigger,input,state,classes,styles,workspace:nodes['#workspace']};
}
test('actual reader controller opens a dock and closes it without changing selected research or implementation',()=>{
  const h=harness();h.controller.showReader({newEntry:true});
  assert.equal(h.dialog.open,true);assert.deepEqual(h.calls,['show','body-focus']);assert.equal(h.attributes['aria-modal'],'false');
  h.controller.closeReader();
  assert.equal(h.dialog.open,false);assert.equal(h.state.selectedCodeId,'C1');assert.deepEqual(h.state.selectedExecution,{type:'run',id:'R1'});
  assert.equal(h.state.hypothesisId,'H2');assert.equal(h.state.experimentId,'E2');assert.equal(h.state.readerHistory.length,0);
  assert.equal(h.document.activeElement,h.trigger);
});
test('actual reader controller keeps a form reference on the modal layer and restores the unsaved form focus',()=>{
  const h=harness(true);h.controller.showReader({newEntry:true});
  assert.equal(h.classes.has('is-modal-reader'),true);assert.equal(h.attributes['aria-modal'],'true');assert.deepEqual(h.calls,['showModal','body-focus']);
  h.controller.closeReader();
  assert.equal(h.input.value,'Unsaved research statement');assert.equal(h.document.activeElement,h.trigger);assert.equal(h.classes.has('is-modal-reader'),false);
  assert.equal(h.attributes['aria-modal'],'false');
});

test('actual inspect click dispatcher cancels native form submission before opening a fixed reference',()=>{
  let handler,opened,prevented=false;
  const start=source.indexOf("  document.addEventListener('click',event=>{"),end=source.indexOf("  document.addEventListener('keydown',event=>{",start);
  vm.runInNewContext(source.slice(start,end),{document:{addEventListener(name,fn){handler=fn;}},inspect(...args){opened=args;}});
  const button={dataset:{action:'inspect',type:'analysis',id:'p:analysis:A1:1'},closest(){return null;}};
  handler({target:{closest(){return button;}},preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(opened[0],'analysis');assert.equal(opened[1],'p:analysis:A1:1');
});
test('rendered fixed-reference buttons are explicitly non-submit controls',()=>{
  const A=require('../live-model.js'),ref={projectId:'p',type:'analysis',id:'A1',version:1};
  const D=A.project({projectId:'p',projects:[],records:[{ref,record:{title:'Fixed evidence',observations:'Observation'}}]});
  const context={window:{RP_DATA:D,RWSAdapter:A}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../evidence.js'),'utf8'),context);
  const html=context.window.RPEvidence.refLink(ref);
  assert.match(html,/<button type="button"[^>]*data-action="inspect"/);
  assert.match(html,/r1/);
});

test('actual research navigation does not preselect an evaluation implementation',()=>{
  const state={selectedCodeId:'C-old',selectedExecution:{type:'evaluation',id:'EV-old'}},layout={research:{focus:'formal',summaryCollapsed:true}},h={id:'H2',title:'New question',experimentId:'E2'};
  const select=vm.runInNewContext(`(()=>{${implementation('selectH','readerMarkup')}return selectH;})()`,{I,state,layout,get:(kind,id)=>kind==='hypotheses'&&id==='H2'?h:null,closeReader(){},currentExp:()=>({id:'E2'}),render(){},status(){},emitContext(){},evaluationsForExp(){throw new Error('Research navigation must not choose an evaluation');}});
  select('H2');assert.equal(state.hypothesisId,'H2');assert.equal(state.experimentId,'E2');assert.equal(state.selectedCodeId,null);assert.equal(state.selectedExecution,null);assert.equal(layout.research.focus,'formal');
});

test('hidden or smaller workspaces never overwrite the manually chosen dock height',()=>{
  const h=harness();h.controller.showReader({newEntry:true});h.controller.setReaderHeight(352,{remember:true});
  assert.equal(h.styles['--reader-height'],'352px');
  h.workspace.clientHeight=0;h.controller.setReaderHeight(h.controller.getPreferredHeight());
  assert.equal(h.controller.getPreferredHeight(),352);assert.equal(h.styles['--reader-height'],'352px');
  h.workspace.clientHeight=260;h.controller.setReaderHeight(h.controller.getPreferredHeight());
  assert.equal(h.styles['--reader-height'],'213.2px');assert.equal(h.controller.getPreferredHeight(),352);
  h.controller.closeReader();h.workspace.clientHeight=600;h.controller.showReader({newEntry:true});
  assert.equal(h.styles['--reader-height'],'352px');
});
