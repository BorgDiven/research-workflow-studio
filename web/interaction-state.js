/* Selection changes do not own research context, layout focus or reader scope. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.RWSInteraction=api;})(typeof window!=='undefined'?window:globalThis,()=>{
  'use strict';
  function clearSelection(state){state.selectedCodeId=null;state.selectedExecution=null;return false;}
  function selectCode(state,id,execution,toggle=false){
    if(toggle&&state.selectedCodeId===id)return clearSelection(state);
    state.selectedCodeId=id;state.selectedExecution=execution?{...execution}:null;return true;
  }
  function selectExecution(state,type,id,codeId,toggle=false){
    if(toggle&&state.selectedExecution?.type===type&&state.selectedExecution?.id===id)return clearSelection(state);
    state.selectedExecution={type,id};state.selectedCodeId=codeId||null;return true;
  }
  function escapeAction({modalOpen,editing,readerOpen,codeView,hasSelection}){
    if(modalOpen||editing)return null;
    if(readerOpen)return 'close-reader';
    return codeView&&hasSelection?'clear-selection':null;
  }
  function readerPresentation({hasModal,readerModal}){return hasModal||readerModal?'modal':'dock';}
  function readerScope(previous,{inside=false,history=true}={}){return !history||inside?previous?.scope||null:null;}
  return {clearSelection,selectCode,selectExecution,escapeAction,readerScope,readerPresentation};
});
