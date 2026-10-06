import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';

const source=await readFile(new URL('../app/ui/industry_workspace/workspace.js',import.meta.url),'utf8');
const {esc,quantityRange,evaluateCandidate,bindWorkspaceEvents,cleanIntake,renderReportMarkdown}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
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
test('report center only exposes the server generated editable Word flow',()=>{
  assert.match(source,/整理公开产业资料并形成项目报告/);
  assert.match(source,/result\.docx_base64/);
  assert.match(source,/accept="\.docx"/);
  assert.match(source,/\['项目报告'\]/);
  assert.doesNotMatch(source,/downloadFile\(`\$\{fileName\}\.html`/);
  assert.doesNotMatch(source,/export function buildReportDocument/);
});
test('generated project report preview safely renders headings, lists and tables',()=>{
  const html=renderReportMarkdown('## 项目摘要\n\n**重点** <script>alert(1)</script> [1]\n\n| 项目 | 内容 |\n|---|---|\n| 批次 | B-01 [2] |\n\n- 待复核');
  assert.match(html,/<h3>项目摘要<\/h3>/);
  assert.match(html,/<strong>重点<\/strong>/);
  assert.match(html,/<table>/);
  assert.match(html,/<sup>\[1\]<\/sup>/);
  assert.match(html,/<sup>\[2\]<\/sup>/);
  assert.match(html,/<ul><li>待复核<\/li><\/ul>/);
  assert.doesNotMatch(html,/<script>/);
});
test('report table captions precede their table and do not turn prose mentions into captions',()=>{
  for(const caption of ['表1 原料数据','表 1 原料数据 <script>attack()</script> [1]']){
    const html=renderReportMarkdown(`${caption}\n\n| 项目 | 内容 |\n|---|---|\n| 批次 | B-01 |`);
    assert.match(html,/<p class="report-table-caption">.*<\/p><table>/);
    assert.doesNotMatch(html,/<script>/);
  }
  assert.equal(renderReportMarkdown('详见表1 原料数据。'),'<p>详见表1 原料数据。</p>');
  assert.equal(renderReportMarkdown('表1 显示了原料数据。\n这是分析正文。'),'<p>表1 显示了原料数据。</p><p>这是分析正文。</p>');
});
test('only the contents heading receives centered contents styling',()=>{
  assert.equal(renderReportMarkdown('## 目 录\n## 产业分析'),'<h3 class="report-toc-heading">目 录</h3><h3>产业分析</h3>');
});

const reportPng='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1sAAAAASUVORK5CYII=';
test('report figures render only matching PNG assets with captions and superscript source notes',()=>{
  const figures=[{id:'export-volume',caption:'图1 武鸣沃柑出口量',note:'来源：新华社 [11]',image_base64:reportPng,mime_type:'image/png'}];
  const markdown='## 产业分析\n\n![出口量](report-figure:export-volume)\n\n产业基础稳步提升。';
  const html=renderReportMarkdown(markdown,figures);
  assert.match(html,/<figure class="report-figure"><img src="data:image\/png;base64,/);
  assert.ok(html.includes(`src="data:image/png;base64,${reportPng}"`));
  assert.match(html,/<figcaption>图1 武鸣沃柑出口量<\/figcaption>/);
  assert.match(html,/来源：新华社 <sup>\[11\]<\/sup>/);
  assert.doesNotMatch(html,/report-figure:export-volume/);
  const restored=JSON.parse(JSON.stringify({markdown,figures}));
  assert.equal(renderReportMarkdown(restored.markdown,restored.figures),html);
});
test('report figure preview rejects external images and malformed assets while escaping all figure text',()=>{
  const figures=[
    {id:'trusted',caption:'图1 <script>alert("caption")</script>',note:'<img src=x onerror="attack()"> [11]',image_base64:reportPng,mime_type:'image/png'},
    {id:'unsafe-type',caption:'非PNG图',image_base64:reportPng,mime_type:'image/svg+xml'},
    {id:'unsafe-data',caption:'无效图',image_base64:'https://example.com/chart.png',mime_type:'image/png'},
    {id:'unsafe-attribute',caption:'无效属性图',image_base64:`${reportPng}" onerror="attack()`,mime_type:'image/png'},
  ];
  const markdown=[
    '![图](report-figure:trusted)',
    '![外部图](https://example.com/private.png)',
    '![脚本图](javascript:attack())',
    '![本地图](file:///private.png)',
    '![缺失 <script>attack()</script> [2]](report-figure:missing)',
    '![图](report-figure:unsafe-type)',
    '![图](report-figure:unsafe-data)',
    '![图](report-figure:unsafe-attribute)',
  ].join('\n');
  const html=renderReportMarkdown(markdown,figures);
  assert.equal((html.match(/<img /g)||[]).length,1);
  assert.match(html,/&lt;script&gt;alert\(&quot;caption&quot;\)&lt;\/script&gt;/);
  assert.match(html,/&lt;img src=x onerror=&quot;attack\(\)&quot;&gt; <sup>\[11\]<\/sup>/);
  assert.match(html,/缺失 &lt;script&gt;attack\(\)&lt;\/script&gt; <sup>\[2\]<\/sup>/);
  assert.doesNotMatch(html,/<script|https:\/\/example\.com|javascript:|file:\/\/|report-figure:|image\/svg\+xml/);
  assert.equal(renderReportMarkdown('![缺失](report-figure:missing)'),'<p class="report-figure-caption">缺失</p>');
});

test('operational workspace omits prototype boundary and session explanation strips',()=>{
  for(const phrase of ['业务数据边界','供应、采购、匹配与对接在一个流程内完成','当前供应批次和候选企业为界面演示数据','class="session-note"','class="evidence-note"']){
    assert.doesNotMatch(source,new RegExp(phrase));
  }
});
