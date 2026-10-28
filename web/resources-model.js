/* Resource registration and executor requests are distinct from execution facts. */
(function(root){
  'use strict';
  const kinds={'git.inspect':'查看仓库状态','git.branch':'创建分支','git.commit':'提交指定文件','git.tag':'创建标签','git.push':'推送指定引用','environment.inspect':'检查运行环境','task.start':'启动任务','task.inspect':'查询任务状态','task.logs':'读取任务日志','task.stop':'停止任务'};
  const states={proposed:'等待人工确认',approved:'等待执行器',dismissed:'已拒绝',claimed:'执行器已领取',running:'运行中',completed:'已完成',failed:'执行失败',unknown:'状态未知'};
  const readonly=new Set(['git.inspect','environment.inspect','task.inspect','task.logs']);
  function operationState(record){return record.status==='proposed'&&readonly.has(record.kind)?'等待执行器':states[record.status]||'尚未执行';}
  function reviewable(record){return record.status==='proposed'&&!readonly.has(record.kind);}
  function executable(record){return record.status==='approved'||record.status==='proposed'&&readonly.has(record.kind);}
  const shellQuote=value=>"'"+String(value).replace(/'/g,"'\"'\"'")+"'";
  function executorCommand(prefix,ref){if(!prefix||!ref?.projectId||!ref?.id||!Number.isSafeInteger(ref.version)||ref.version<1)return null;return prefix+' --project-id '+shellQuote(ref.projectId)+' --operation-id '+shellQuote(ref.id)+' --version '+ref.version;}
  function required(value,label){if(!String(value??'').trim())throw new Error('请填写'+label+'。');return String(value).trim();}
  function operationArguments(kind,values){
    if(kind==='git.branch')return {name:required(values.name,'分支名称'),...(values.startPoint?{startPoint:values.startPoint.trim()}:{})};
    if(kind==='git.commit')return {message:required(values.message,'提交说明'),paths:required(values.paths,'明确的文件路径').split('\n').map(v=>v.trim()).filter(Boolean)};
    if(kind==='git.tag')return {name:required(values.name,'标签名称'),...(values.revision?{revision:values.revision.trim()}:{}),...(values.message?{message:values.message.trim()}:{})};
    if(kind==='git.push')return {remoteName:required(values.remoteName,'远端名称'),refspec:required(values.refspec,'要推送的引用')};
    if(kind==='task.start'){let argv;try{argv=JSON.parse(values.argv);}catch{throw new Error('启动命令需为 JSON 字符串数组。');}if(!Array.isArray(argv)||!argv.length||argv.some(v=>typeof v!=='string'||!v))throw new Error('启动命令需为非空 JSON 字符串数组。');return {argv,...(values.timeoutSeconds?{timeoutSeconds:Number(values.timeoutSeconds)}:{})};}
    if(kind==='task.logs')return {stream:values.stream||'stdout',tailLines:Number(values.tailLines||100)};
    return {};
  }
  const api={kinds,states,readonly,operationState,reviewable,executable,operationArguments,executorCommand};root.RWSResourcesModel=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
