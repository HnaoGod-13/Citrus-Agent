import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';

const source=await readFile(new URL('../app/ui/industry_workspace/analytics.js',import.meta.url),'utf8');
const styles=await readFile(new URL('../app/ui/industry_workspace/workspace.css',import.meta.url),'utf8');
const {visualizationDataset,visualizationFilterOptions,visualizationCsv,renderIndustryVisuals}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

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

test('real record filters recalculate every dashboard aggregate and export',()=>{
  const raw={
    source:'当前账号产业数据采集记录',recordCount:3,updatedAt:'2026-09-30',
    records:[
      {side:'supplier',status:'submitted',date:'2026-08-03',origin:'重庆奉节',supplyTons:2,brix:12.2,quality:{qualified:1},updatedAt:'2026-08-03'},
      {side:'supplier',status:'draft',date:'2026-09-05',origin:'广西武鸣',supplyTons:4,brix:13,quality:{pending:1},updatedAt:'2026-09-05'},
      {side:'processor',status:'submitted',date:'2026-09-08',inputTons:3,outputTons:1.5,quality:{qualified:1},updatedAt:'2026-09-08'},
    ],
  };
  const options=visualizationFilterOptions(raw);
  assert.deepEqual(options.periods,['2026-09','2026-08']);
  assert.deepEqual(new Set(options.origins),new Set(['广西武鸣','重庆奉节']));
  const data=visualizationDataset(raw,{period:'2026-09'});
  assert.equal(data.recordCount,2);
  assert.equal(data.supplierCount,1);
  assert.equal(data.processorCount,1);
  assert.equal(data.supplyTons,4);
  assert.equal(data.inputTons,3);
  assert.equal(data.outputTons,1.5);
  assert.equal(data.averageBrix,13);
  assert.equal(data.submittedCount,1);
  assert.equal(data.draftCount,1);
  assert.deepEqual(data.origins,[{label:'广西武鸣',value:1}]);
  const csv=visualizationCsv(raw,{period:'2026-09'});
  assert.match(csv,/筛选条件：月份/);
  assert.match(csv,/2026-09/);
  assert.match(csv,/投入加工量/);
});

test('regional view renders readable flow cards and an explicit destination',()=>{
  const longOrigin='重庆市奉节县安坪镇三沱村标准化柑橘种植基地';
  const longDestination='山东省临沂市高新技术产业开发区柑橘精深加工与冷链集配中心';
  const html=renderIndustryVisuals({
    tab:2,
    raw:{recordCount:1,supplierCount:1,processorCount:0,supplyTons:6,outputTons:0,averageBrix:12.4,timeline:[],origins:[{label:longOrigin,value:6}],quality:{},source:'当前账号产业数据采集记录',updatedAt:'2026-09-07'},
    request:{destination:longDestination},
    header:()=>'',tabs:()=>'',button:()=>'',svg:()=>'',esc:value=>String(value),
  });
  assert.match(html,/viz-route-board/);
  assert.match(html,/viz-route-origin/);
  assert.ok(html.includes(longOrigin));
  assert.ok(html.includes(longDestination));
  assert.match(html,/待匹配汇入/);
  assert.match(html,/role="group"/);
  assert.doesNotMatch(html,/\bviz-route-flow\b/);
});

test('volume chart keeps axis labels outside its stable svg canvas',()=>{
  const html=renderIndustryVisuals({
    tab:1,
    raw:{
      recordCount:2,supplierCount:1,processorCount:1,supplyTons:12,outputTons:4,
      averageBrix:12.6,
      timeline:[{label:'2026-08',supply:8,output:2},{label:'2026-09',supply:12,output:4}],
      origins:[],quality:{},source:'当前账号产业数据采集记录',updatedAt:'2026-09-07',
    },
    request:{destination:'重庆加工园区'},
    header:()=>'',tabs:()=>'',button:()=>'',svg:()=>'',esc:value=>String(value),
  });
  assert.match(html,/viz-chart-shell/);
  assert.match(html,/viz-chart-plot/);
  assert.match(html,/viz-chart-y-axis/);
  assert.match(html,/viz-chart-x-axis/);
  assert.match(html,/2026-08/);
  assert.match(html,/2026-09/);
  const chart=html.match(/<svg\b[\s\S]*?<\/svg>/)?.[0];
  assert.ok(chart,'volume chart should include an SVG plotting canvas');
  assert.doesNotMatch(chart,/<text\b/);
});

test('visual dashboard keeps provenance fields without prototype explanation copy',()=>{
  const html=renderIndustryVisuals({
    tab:0,raw:{recordCount:0},request:{destination:'重庆加工园区'},
    header:()=>'',tabs:()=>'',button:()=>'',svg:()=>'',esc:value=>String(value),
  });
  assert.match(html,/数据状态/);
  assert.match(html,/数据来源/);
  assert.match(html,/演示数据/);
  for(const phrase of ['当前账号尚无已保存采集记录','仅用于展示图表结构','供应端采收量对比生产端成品净产量','图表所用的同一组数据']){
    assert.doesNotMatch(html,new RegExp(phrase));
  }
  assert.equal((html.match(/class="viz-kpi /g)||[]).length,4);
  assert.match(html,/平均糖度/);
  assert.match(html,/未收集经纬度或行政区编码/);
  assert.doesNotMatch(html,/viz-region-map/);
  assert.doesNotMatch(html,/VISUAL INTELLIGENCE/);
});

test('industry charts use one restrained publication palette and no decorative card gradients',()=>{
  for(const token of ['--viz-ink:#17191c','--viz-supply:#44566c','--viz-output:#1c9b87','--viz-warning:#d59b43']){
    assert.ok(styles.includes(token),`missing palette token ${token}`);
  }
  assert.match(styles,/\.iw \.viz-line\.output \{ stroke:var\(--viz-output\); \}/);
  assert.match(styles,/\.iw \.viz-kpis \{ display:grid; grid-template-columns:repeat\(4,minmax\(0,1fr\)\)/);
  assert.match(styles,/\.iw \.viz-top-grid \{ display:grid; min-width:0; grid-template-columns:minmax\(0,3fr\) minmax\(0,2fr\)/);
  assert.doesNotMatch(styles,/\.iw \.ic-entry-(?:supplier|processor)[^\n]*linear-gradient/);
  assert.doesNotMatch(styles,/\.iw \.viz-route-target[^\n]*box-shadow:(?!none)/);
});
