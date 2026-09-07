import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';

const source=await readFile(new URL('../app/ui/industry_workspace/analytics.js',import.meta.url),'utf8');
const {visualizationDataset,visualizationCsv}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

test('empty accounts receive clearly labelled preview data',()=>{
  const data=visualizationDataset({recordCount:0});
  assert.equal(data.mode,'preview');
  assert.match(data.source,/结构预览数据/);
  assert.ok(data.timeline.length>0);
});

test('real scoped aggregates are never mixed with preview values',()=>{
  const data=visualizationDataset({
    source:'当前账号产业数据采集记录',recordCount:2,supplierCount:1,processorCount:1,
    supplyTons:2,outputTons:0.5,averageBrix:null,timeline:[],origins:[],quality:{},updatedAt:'2026-09-07',
  });
  assert.equal(data.mode,'recorded');
  assert.equal(data.supplyTons,2);
  assert.equal(data.outputTons,.5);
  assert.equal(data.averageBrix,null);
  assert.deepEqual(data.timeline,[]);
  assert.deepEqual(data.origins,[]);
});

test('downloaded chart data carries source and preview status',()=>{
  const csv=visualizationCsv({recordCount:0});
  assert.match(csv,/结构预览数据/);
  assert.match(csv,/非政府统计、非企业实报/);
});
