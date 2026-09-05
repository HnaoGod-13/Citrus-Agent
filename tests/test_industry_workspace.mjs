import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';

const source=await readFile(new URL('../app/ui/industry_workspace/workspace.js',import.meta.url),'utf8');
const {esc,quantityRange,evaluateCandidate,bindWorkspaceEvents,cleanIntake,buildReportDocument}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
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
test('industry intake cleaning normalizes useful records and blocks unusable ones',()=>{
  const complete={organization:'示例企业',processingProduct:'NFC果汁',material:'沃柑鲜果',plannedQuantity:'20',batch:' b-0903-001 ',origin:'广西南宁',harvestDate:'2026-09-02',brix:'12.84',supplier:'示例果园',line:'榨汁线',sop:'SOP v2.1',operator:'操作员'};
  const valid=cleanIntake(complete);
  assert.equal(valid.valid,true);
  assert.equal(valid.standardized.batch,'B-0903-001');
  assert.equal(valid.standardized.brix,12.8);
  const kilograms=cleanIntake({...complete,plannedQuantity:'20000',unit:'千克'});
  assert.equal(kilograms.standardized.plannedQuantity,20);
  assert.equal(kilograms.standardized.unit,'吨');
  const invalid=cleanIntake({...complete,plannedQuantity:'无',brix:'52',origin:''});
  assert.equal(invalid.valid,false);
  assert.ok(invalid.missing.length>0);
  assert.ok(invalid.issues.length>=2);
});
test('generated report escapes organization text and keeps chart and review caveat',()=>{
  const report=buildReportDocument({agency:'<img onerror=alert(1)>',title:'产业报告',region:'广西',period:'2026'});
  assert.doesNotMatch(report,/<img onerror/);
  assert.match(report,/&lt;img onerror=alert\(1\)&gt;/);
  assert.match(report,/bars/);
  assert.match(report,/正式报送前须由主管单位复核/);
});
test('business report carries unit template metadata and completed work summary',()=>{
  const report=buildReportDocument({
    agency:'某县农业农村局',
    department:'产业发展科',
    preparedBy:'张三',
    title:'柑橘产业工作报告',
    reportType:'业务工作报告',
    templateFile:'单位模板.docx',
    period:'2026年9月',
    region:'重庆',
  },{
    batch:'B-0905-001',
    material:'脐橙 · 重庆奉节',
    quantity:'30 吨',
    processing:'NFC 柑橘汁 · 榨汁线 A · SOP v3.0',
    demand:'NFC 果汁原料采购',
    matches:'2 个',
    connections:'1 个',
    dataScore:'96/100',
    issues:['检测报告待复核']
  });
  assert.match(report,/单位模板：单位模板\.docx/);
  assert.match(report,/B-0905-001/);
  assert.match(report,/NFC 柑橘汁 · 榨汁线 A · SOP v3\.0/);
  assert.match(report,/检测报告待复核/);
});
