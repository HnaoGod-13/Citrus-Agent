import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../app/ui/industry_workspace/intake.js',import.meta.url),'utf8');
const {intakeNewDocument,intakeLinkMaterial,intakeAudit,intakePrintable,createIntakeController}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const schema={sides:{supplier:{title:'供应端信息收集',steps:[{title:'记录',groups:[{key:'base',fields:[{key:'variety',label:'品种',required:true,type:'text'}]},{key:'tests',repeat:true,required:true,fields:[{key:'result',label:'结果',type:'text',required:true}]}]}]}}};
test('the two intake sides never share mutable field or row objects',()=>{
  const a=intakeNewDocument('supplier'), b=intakeNewDocument('processor');
  a.fields['base.variety']='沃柑';a.rows.tests=[{result:'<0.01'}];
  assert.deepEqual(b.fields,{});assert.deepEqual(b.rows,{});
});
test('batch linking carries source facts without inventing receipt or acceptance',()=>{
  const doc=intakeNewDocument('supplier');doc.fields={'base.variety':'脐橙','harvest.batch':'B-1','harvest.quantity':'90'};
  const material=intakeLinkMaterial(doc);
  assert.equal(material.batch,'B-1');assert.equal(material.name,'脐橙');
  assert.equal(material.quantity,undefined);assert.equal(material.acceptance,undefined);
});
test('required repeated records cannot appear complete when empty',()=>{
  const d=intakeNewDocument('supplier');d.fields['base.variety']='沃柑';
  assert.equal(intakeAudit(d,schema).valid,false);
  d.rows.tests=[{result:'未检出'}];assert.equal(intakeAudit(d,schema).valid,true);
});
test('printable complete record preserves row results and escapes entered markup',()=>{
  const d=intakeNewDocument('supplier');d.fields['base.variety']='<script>danger</script>';d.rows.tests=[{result:'<0.01'}];
  const html=intakePrintable(d,schema);
  assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;0.01/);assert.match(html,/&lt;script&gt;/);
});
test('remounting cannot replay an acknowledged save over later field edits',()=>{
  const saved=intakeNewDocument('supplier');saved.fields['base.variety']='原保存品种';
  const model={};
  const data={intakeSchema:schema,intakeResult:{requestId:'request-1',ok:true,operation:'save',document:saved,message:'已保存'}};
  const props={root:{},model,data,setStateValue(){},render(){},flash(){},download(){},persist(){},changeView(){}};
  createIntakeController(props);
  model.collection.documents.supplier=structuredClone(saved);
  model.collection.documents.supplier.fields['base.variety']='继续编辑后的品种';
  const controller=createIntakeController({...props,root:{}});
  assert.equal(controller.refreshed,false);
  assert.equal(model.collection.documents.supplier.fields['base.variety'],'继续编辑后的品种');
});

test('returning to the intake entry clears the active side so either side can be selected again',()=>{
  const entrySchema={sides:{
    supplier:{title:'供应端信息收集',subtitle:'种植与采收资料',steps:[]},
    processor:{title:'生产端信息收集',subtitle:'加工与追溯资料',steps:[]},
  }};
  const model={collection:{side:'processor',panel:'form',steps:{supplier:0,processor:2},documents:{processor:intakeNewDocument('processor')},dirty:{processor:false}}};
  const props={root:{},model,data:{intakeSchema:entrySchema},setStateValue(){},render(){},flash(){},download(){},persist(){},changeView(){}};
  const controller=createIntakeController(props);

  controller.click({dataset:{action:'ic-home'}});

  assert.equal(model.collection.side,'');
  assert.equal(model.collection.panel,'form');
  const markup=controller.render();
  assert.match(markup,/data-action="ic-side-supplier"/);
  assert.match(markup,/data-action="ic-side-processor"/);
});
