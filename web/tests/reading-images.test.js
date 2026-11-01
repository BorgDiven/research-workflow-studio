'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const A=require('../live-model.js'),M=require('../results-model.js');
const ref=(type,id,version=1)=>({projectId:'p',type,id,version});
const env=(type,id,record,version=1)=>({ref:ref(type,id,version),record});
const preview=uri=>'/api/preview?uri='+encodeURIComponent(uri);
function reader(records=[],options={}){
  const D=A.project({projectId:'p',projects:[{id:'p',name:'Project'}],records}),listeners={};
  const context={URL,window:{RP_DATA:D,RWSAdapter:options.adapter||A,location:options.origin?{origin:options.origin}:undefined},document:{addEventListener:(name,fn,capture)=>{(listeners[name]??=[]).push({fn,capture});}}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../evidence.js'),'utf8'),context);
  return {R:context.window.RPEvidence,D,listeners};
}
function assertReadingOnly(html,original){
  const urls=[...html.matchAll(/(?:src|href)="([^"]+)"/g)].map(x=>x[1]);
  assert.ok(urls.includes(preview(original)),html);
  assert.ok(!urls.includes(original),html);
  assert.doesNotMatch(html,/查看原图|下载原件/);
}
test('gallery and click enlargement use the same reading endpoint without original links',()=>{
  const {R}=reader(),original='/materials/project/result 1.png';
  const html=R.typed({kind:'image-set',items:[{uri:original,caption:'Result'}]});
  assertReadingOnly(html,original);
  assert.equal((html.match(/\/api\/preview\?uri=/g)||[]).length,2);
  assert.match(html,/loading="lazy"/);assert.match(html,/放大阅读图/);
});
test('remote and file originals are not requested automatically; static illustrations stay available',()=>{
  const {R}=reader();
  for(const uri of ['https://files.example/image.png','file:///private/image.png','/unexpected/image.png']){
    const html=R.typed({kind:'image-set',items:[{uri}]});
    assert.doesNotMatch(html,/<img|<a[^>]*href=/);assert.match(html,/阅读图|网页无法直接读取/);
  }
  assert.equal(R.readingURL('/assets/showcase/result.svg'),'/assets/showcase/result.svg');
  assert.equal(R.readingURL('/assets/../materials/result.png'),null);
  assert.equal(R.readingURL('https://files.example/assets/result.png'),null);
  assert.equal(R.readingURL('javascript:alert(1)'),null);
  assert.equal(R.readingURL('data:image/svg+xml;base64,AAAA'),null);
  const staticAdapter={...A,safeURL:value=>/^assets\/showcase\/[a-z0-9-]+\.svg$/.test(value)?value:null};
  assert.match(reader([],{adapter:staticAdapter}).R.typed({kind:'image-set',items:[{uri:'assets/showcase/result.svg'}]}),/src="assets\/showcase\/result.svg"/);
});
test('top-level artifact projection retains exact identity and keeps original download in folded details only',()=>{
  const original='/materials/p/result.png',artifact=env('artifact','A',{kind:'image',title:'Image',uri:original}),{D,R}=reader([artifact]);
  assert.deepEqual(D.artifacts[0].content.items[0].artifactRef,artifact.ref);
  assertReadingOnly(R.typed(D.artifacts[0].content),original);
  const details=R.render('artifact',A.key(artifact.ref));
  assert.match(details,/<details class="original-materials"><summary>原始文件<\/summary>/);
  assert.match(details,/href="\/materials\/p\/result.png\?download=1" download/);
  assert.equal((details.match(/下载原件/g)||[]).length,1);
  assert.doesNotMatch(details,/src="\/materials\//);
});
test('only current-browser-origin absolute managed URLs normalize to the reading endpoint',()=>{
  const {R}=reader([],{origin:'https://studio.example:8443'}),path='/materials/p/image%201.png';
  assert.equal(R.readingURL('https://studio.example:8443'+path),preview(path));
  for(const uri of ['https://other.example:8443'+path,'https://studio.example'+path,'http://studio.example:8443'+path,'https://studio.example:8443/assets/image.png','https://studio.example:8443'+path+'?token=private','https://studio.example:8443'+path+'#source','https://user:secret@studio.example:8443'+path])assert.equal(R.readingURL(uri),null);
  assert.equal(reader().R.readingURL('https://studio.example:8443'+path),null);
});
test('frozen report image references resolve the old exact URI and never a newer artifact',()=>{
  const old=env('artifact','A',{title:'Frozen',kind:'image',uri:'/materials/p/frozen.png'},1),current=env('artifact','A',{title:'Latest',kind:'image',uri:'/materials/p/latest.png'},2);
  const collection=env('artifact','SET',{title:'Selected',kind:'image-set',content:{kind:'image-set',items:[{artifactRef:old.ref}]}});
  const report=env('report','REPORT',{markdown:'Fixed report',snapshot:{records:[old,collection]}});
  const {R}=reader([current,collection,report]),scope=R.scopeForReport(A.key(report.ref));
  const html=R.render('artifact',A.key(collection.ref),{scope});
  assertReadingOnly(html,'/materials/p/frozen.png');assert.doesNotMatch(html,/latest.png|Latest/);
});
test('missing exact referenced image cannot borrow a URI or latest version',()=>{
  const current=env('artifact','A',{kind:'image',uri:'/materials/p/latest.png'},2),{R}=reader([current]);
  const html=R.typed({kind:'image-set',items:[{artifactRef:ref('artifact','A',1),uri:'/materials/p/borrowed.png'}]});
  assert.match(html,/精确图像版本不在当前快照/);assert.doesNotMatch(html,/<img|\/api\/preview/);
});
test('nested exact image references remain bounded and honor unavailable descendants',()=>{
  const original=env('artifact','A',{kind:'image',uri:'/materials/p/a.png',availability:'unavailable'}),set=env('artifact','SET',{kind:'image-set',content:{kind:'image-set',items:[{artifactRef:original.ref}]}}),{R}=reader([original,set]);
  assert.doesNotMatch(R.typed({kind:'image-set',items:[{artifactRef:set.ref}]}),/<img/);
  const cycle=env('artifact','LOOP',{kind:'image-set',content:{kind:'image-set',items:[{artifactRef:ref('artifact','LOOP')}]}});
  assert.match(reader([cycle]).R.typed({kind:'image-set',items:[{artifactRef:cycle.ref}]}),/精确图像版本/);
});
test('image attachments and Markdown images or image links use reading renditions',()=>{
  const {R}=reader(),original='/materials/p/report.png';
  assertReadingOnly(R.typed({kind:'attachment',mimeType:'image/png',uri:original}),original);
  assertReadingOnly(R.markdown('![Selected evidence]('+original+')\n\n[Enlarge]('+original+')'),original);
  assertReadingOnly(R.markdown('[Diagram](/materials/p/diagram.svg)'),'/materials/p/diagram.svg');
  assert.doesNotMatch(R.markdown('![Remote](https://files.example/full.png)\n\n[Remote](https://files.example/full.png)'),/<img|href=/);
  assert.match(R.markdown('[Paper](https://example.org/paper)'),/href="https:\/\/example.org\/paper"/);
});
test('a failed reading image hides the broken link without retrying the original',()=>{
  const {listeners}=reader(),error=listeners.error[0],message={hidden:true},attributes={href:'/api/preview?uri=test'},link={hidden:false,removeAttribute:name=>delete attributes[name]},container={querySelector:()=>message};
  const img={src:'/api/preview?uri=test',matches:selector=>selector==='img[data-reading-image]',closest:selector=>selector==='.reading-image-link'?link:container};
  assert.equal(error.capture,true);error.fn({target:img});
  assert.equal(link.hidden,true);assert.equal(message.hidden,false);assert.equal(attributes.href,undefined);assert.equal(img.src,'/api/preview?uri=test');
});
test('PDF reading links use the rendition endpoint and originals remain explicit material downloads',()=>{
  const original='/materials/p/large-report.pdf',artifact=env('artifact','PDF',{title:'Report',kind:'attachment',uri:original,mimeType:'application/pdf'}),{R}=reader([artifact]);
  const html=R.typed({kind:'attachment',uri:original,mimeType:'application/pdf'});
  assertReadingOnly(html,original);assert.match(html,/阅读报告/);assert.doesNotMatch(html,/<iframe|<embed|<object/);
  assertReadingOnly(R.markdown('[Report]('+original+')'),original);
  const details=R.render('artifact',A.key(artifact.ref));assert.match(details,/href="\/materials\/p\/large-report.pdf\?download=1" download/);
  assert.doesNotMatch(R.typed({kind:'attachment',uri:'https://files.example/report.pdf',mimeType:'application/pdf'}),/href=/);
});
test('single-sample and multi-sample result matrices both reuse the shared reading resolver',()=>{
  const records=[env('code','C',{kind:'inference',version:'v1'}),env('run','R',{codeRef:ref('code','C'),status:'completed'}),...['a','b'].map(id=>env('artifact',id,{kind:'image',title:id,semantic:'final-output',sampleId:id,producerRef:ref('run','R'),uri:'/materials/p/'+id+'.png'}))];
  const {R,D}=reader(records),listeners={},host={innerHTML:'',querySelector:()=>({scrollTop:0})};
  const window={RP_DATA:D,RWSAdapter:A,RWSResultsModel:M,RPEvidence:R};
  vm.runInNewContext(fs.readFileSync(require.resolve('../results.js'),'utf8'),{window,document:{querySelector:()=>host,addEventListener:(name,fn)=>listeners[name]=fn}});
  window.RWSResults.render({experiment:{ref:ref('experiment','E')},artifacts:D.artifacts,evaluations:[],analyses:[],reports:[]});
  assertReadingOnly(host.innerHTML,'/materials/p/a.png');assert.doesNotMatch(host.innerHTML,/(?:src|href)="\/materials\//);
  listeners.click({target:{closest:()=>({dataset:{results:'mode',value:'single'}})}});
  assert.match(host.innerHTML,/single-case/);assertReadingOnly(host.innerHTML,'/materials/p/a.png');assert.doesNotMatch(host.innerHTML,/(?:src|href)="\/materials\//);
});
