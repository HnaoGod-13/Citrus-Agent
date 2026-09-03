import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';

const source=await readFile(new URL('../app/ui/industry_workspace/workspace.js',import.meta.url),'utf8');
const {esc,quantityRange,evaluateCandidate,bindWorkspaceEvents}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const request={material:'沃柑鲜果',region:'广西及周边',quantity:'15—25',brix:'12.0',delivery:'2026-09-10',report:true,preferences:['完整投入品记录','可寄样','稳定供货']};
const candidate={quantity:20,brix:12.8,arrival:'2026-09-08',report:true,preferences:['完整投入品记录','可寄样']};

test('quantity ranges accept common separators and reject malformed/inverted quantities',()=>{
  for(const input of ['15—25','15-25','15～25','15 至 25'])assert.deepEqual(quantityRange(input),[15,25]);
  assert.deepEqual(quantityRange('20'),[20,20]);
  for(const input of ['', '25—15','0','-1','15吨','15—25—30','abc'])assert.equal(quantityRange(input),null);
});
test('the approved example yields four satisfied hard requirements and score 92',()=>{
  const result=evaluateCandidate(candidate,request);
  assert.equal(result.fit,true); assert.equal(result.score,92); assert.deepEqual(result.checks,[true,true,true,true]);
});
test('missing evidence never enters eligible recommendations',()=>{
  const result=evaluateCandidate({...candidate,report:false},request);
  assert.equal(result.fit,false); assert.equal(result.missing,true); assert.equal(result.score,null);
});
test('each hard condition rejects failing candidates independently',()=>{
  for(const edit of [{brix:'13'},{quantity:'21—25'},{delivery:'2026-09-07'},{material:'柑橘果皮'},{region:'江西及周边'},{brix:''},{quantity:'invalid'}]){
    assert.equal(evaluateCandidate(candidate,{...request,...edit}).fit,false,JSON.stringify(edit));
  }
});
test('preferences only rank candidates, never override hard failures',()=>{
  assert.equal(evaluateCandidate({...candidate,brix:11},request).score,null);
  assert.equal(evaluateCandidate(candidate,{...request,preferences:[]}).fit,true);
});
test('user-provided text and file names are escaped before entering markup',()=>{
  assert.equal(esc('<img src=x onerror="alert(1)">'),'&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
  assert.equal(esc("'&"),'&#39;&amp;');
});
test('rerenders replace listeners so one submit saves one record',()=>{
  const root=new EventTarget();
  let saves=0;
  const first=bindWorkspaceEvents(root,{submit:()=>saves++});
  bindWorkspaceEvents(root,{submit:()=>saves++});
  first(); // Late cleanup from an older render must not remove current handlers.
  root.dispatchEvent(new Event('submit'));
  assert.equal(saves,1);
  root._cleanup();
  root.dispatchEvent(new Event('submit'));
  assert.equal(saves,1);
});
