/* Selection changes do not own research context, layout focus or reader scope. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.RWSInteraction=api;})(typeof window!=='undefined'?window:globalThis,()=>{
  'use strict';
  function clearSelection(state){state.selectedCodeId=null;state.selectedExecution=null;if('selectedSpecId' in state)state.selectedSpecId=null;if('selectedMissingId' in state)state.selectedMissingId=null;if('codeDetailHistory' in state)state.codeDetailHistory=[];return false;}
  function setAssociationHighlight(state,visible){state.associationHighlight=!!visible;return state.associationHighlight;}
  function selectDefinition(state,type,id,toggle=false){
    const field=type==='spec'?'selectedSpecId':'selectedMissingId';
    if(toggle&&state[field]===id)return clearSelection(state);
    clearSelection(state);state[field]=id;return true;
  }
  function selectCode(state,id,execution,toggle=false){
    if(toggle&&state.selectedCodeId===id)return clearSelection(state);
    clearSelection(state);
    state.selectedCodeId=id;state.selectedExecution=execution?{...execution}:null;return true;
  }
  function selectExecution(state,type,id,codeId,toggle=false){
    if(toggle&&state.selectedExecution?.type===type&&state.selectedExecution?.id===id)return clearSelection(state);
    clearSelection(state);
    state.selectedExecution={type,id};state.selectedCodeId=codeId||null;return true;
  }
  function escapeAction({modalOpen,editing,readerOpen,codeView,hasSelection}){
    if(modalOpen||editing)return null;
    if(readerOpen)return 'close-reader';
    return codeView&&hasSelection?'clear-selection':null;
  }
  function readerPresentation({hasModal,readerModal}){return hasModal||readerModal?'modal':'dock';}
  function readerScope(previous,{inside=false,history=true}={}){return !history||inside?previous?.scope||null:null;}
  return {clearSelection,selectCode,selectExecution,selectDefinition,setAssociationHighlight,escapeAction,readerScope,readerPresentation};
});
