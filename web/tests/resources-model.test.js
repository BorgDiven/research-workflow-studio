'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),M=require('../resources-model.js'),A=require('../live-model.js');
test('operation registration and human approval never display executed success',()=>{
  assert.equal(M.operationState({kind:'task.start',status:'proposed'}),'等待人工确认');assert.equal(M.operationState({kind:'git.inspect',status:'proposed'}),'等待执行器');assert.equal(M.operationState({kind:'task.start',status:'approved'}),'等待执行器');assert.equal(M.operationState({kind:'task.start',status:'unknown'}),'状态未知');assert.equal(M.reviewable({kind:'task.start',status:'proposed'}),true);assert.equal(M.reviewable({kind:'task.inspect',status:'proposed'}),false);assert.equal(M.reviewable({kind:'task.start',status:'approved'}),false);
});
test('request arguments retain explicit paths and argv, with no implicit git add or shell',()=>{
  assert.deepEqual(M.operationArguments('git.commit',{message:'Add experiment',paths:'src/method.py\ntests/test_method.py'}),{message:'Add experiment',paths:['src/method.py','tests/test_method.py']});
  assert.deepEqual(M.operationArguments('task.start',{argv:'["python3","train.py","--name","two words"]'}),{argv:['python3','train.py','--name','two words']});
  assert.throws(()=>M.operationArguments('git.push',{remoteName:'origin',refspec:''}),/要推送的引用/);assert.throws(()=>M.operationArguments('task.start',{argv:'python train.py'}),/JSON/);assert.throws(()=>M.operationArguments('task.start',{argv:'[]'}),/非空/);
});
test('copied executor commands bind the exact revision and quote literal project and operation IDs',()=>{
  const command=M.executorCommand('python launch.py operate --db /demo/db',{projectId:"p'$(echo x)",type:'operation',id:'O two',version:4});
  assert.equal(command,`python launch.py operate --db /demo/db --project-id 'p'"'"'$(echo x)' --operation-id 'O two' --version 4`);
  assert.equal(M.executorCommand('python launch.py operate',{projectId:'p',id:'O'}),null);
});
test('resource projection preserves exact references and shows latest operation state once',()=>{
  const ref=(type,id,version=1)=>({projectId:'p',type,id,version}),old={ref:ref('operation','O'),record:{title:'Launch',kind:'task.start',status:'proposed'}},latest={ref:ref('operation','O',2),record:{...old.record,status:'approved'}},server={ref:ref('server','S'),record:{title:'Synthetic server',transport:'ssh',sshAlias:'fictional-compute',workspaceRoot:'/workspace/demo'}},repo={ref:ref('repository','G'),record:{title:'Synthetic repo',serverRef:server.ref,path:'/workspace/demo/repo'}};
  const data=A.project({projectId:'p',projects:[],references:[old],records:[server,repo,latest]});assert.equal(data.operations.length,1);assert.equal(data.operations[0].raw.status,'approved');assert.deepEqual(data.repositories[0].raw.serverRef,server.ref);assert.deepEqual(data.envelopes[A.key(old.ref)].record,old.record);
});
