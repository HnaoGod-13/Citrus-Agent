const icons = {
  plus:'<path d="M5 12h14M12 5v14"/>',
  upload:'<path d="M4 15v5h16v-5M12 16V3m-5 5 5-5 5 5"/>',
  search:'<circle cx="10" cy="10" r="7"/><path d="m16 16 5 5"/>',
  factory:'<path d="M3 21V10l6 3V9l6 3V3h4v18H3M7 17h1m4 0h1"/>',
  clipboard:'<rect x="5" y="4" width="15" height="18" rx="2"/><path d="M9 2h7v4H9zM9 11h7M9 16h4"/>',
  shield:'<path d="m12 2 8 3v7c0 5-4 8-8 10-4-2-8-5-8-10V5zM8 12l3 3 5-6"/>',
  chart:'<path d="M3 21h18M5 20V12h3v8m4 0V7h3v13m4 0V2h3v18"/>',
  conveyor:'<rect x="2" y="15" width="20" height="6" rx="3"/><circle cx="7" cy="18" r=".6"/><circle cx="17" cy="18" r=".6"/><path d="M6 5h8v7H6zM9 8h2"/>',
  juice:'<path d="M7 2h10v3H7zM9 5v4l-4 5v7h14v-7l-4-5V5M9 14h6v4H9z"/>',
  dryer:'<rect x="3" y="3" width="18" height="18" rx="1"/><rect x="6" y="6" width="12" height="10"/><path d="M8 19h1m6 0h1M12 8v5"/>',
  box:'<path d="m12 2 9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10M7 4l9 5"/>',
  file:'<path d="M4 2h10l6 6v14H4zM14 2v6h6M8 12h8M8 16h6"/>',
  chat:'<path d="M3 3h18v14H9l-6 5zM7 9h.1M12 9h.1M17 9h.1"/>',
  clock:'<circle cx="12" cy="12" r="10"/><path d="M12 5v8h5"/>',
  list:'<path d="M8 5h13M8 12h13M8 19h13M3 5h.1M3 12h.1M3 19h.1"/>',
  grid:'<rect x="3" y="3" width="6" height="6" rx="1"/><rect x="15" y="3" width="6" height="6" rx="1"/><rect x="3" y="15" width="6" height="6" rx="1"/><rect x="15" y="15" width="6" height="6" rx="1"/>',
  check:'<circle cx="12" cy="12" r="10" fill="currentColor" stroke="none"/><path d="m7 12 3 3 7-7" stroke="white"/>',
  tick:'<path d="m5 12 5 5L20 7"/>',
  info:'<circle cx="12" cy="12" r="10"/><path d="M12 10v7M12 6h.1"/>',
  alert:'<path d="m12 2 11 19H1zM12 9v5m0 3h.1"/>',
  lock:'<rect x="4" y="10" width="16" height="12" rx="1"/><path d="M7 10V6a5 5 0 0 1 10 0v4M12 14v4"/>',
  star:'<path d="m12 2 3 6 7 1-5 5 1 8-6-4-6 4 1-8-5-5 7-1z"/>',
  arrow:'<path d="M3 12h18m-6-6 6 6-6 6"/>'
  ,database:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/>'
  ,filter:'<path d="M3 4h18l-7 8v7l-4 2v-9z"/>'
  ,map:'<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3zM9 3v15m6-12v15"/>'
  ,download:'<path d="M12 3v12m-5-5 5 5 5-5M4 21h16"/>'
  ,link:'<path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"/>'
};
const svg=(name,size=18)=>`<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]||icons.file}</svg>`;
export const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Streamlit reruns the renderer on data changes but calls its returned cleanup
// only on unmount. Replace previous listeners explicitly to avoid double saves.
export function bindWorkspaceEvents(root, handlers) {
  root._cleanup?.();
  const entries=Object.entries(handlers);
  entries.forEach(([type,handler])=>root.addEventListener(type,handler));
  const cleanup=()=>{
    entries.forEach(([type,handler])=>root.removeEventListener(type,handler));
    if(root._cleanup===cleanup)root._cleanup=null;
  };
  root._cleanup=cleanup;
  return cleanup;
}
const defaultRequest={name:'NFC 果汁加工原料采购',material:'沃柑鲜果',use:'榨汁加工',region:'广西及周边',quantity:'15—25',brix:'12.0',delivery:'2026-09-10',destination:'南宁 · 示例工厂',budget:'面议',report:true,checklist:'',preferences:['完整投入品记录','可寄样','稳定供货'],published:false};
const requiredIntake=['organization','processingProduct','material','plannedQuantity','batch','origin','harvestDate','brix','supplier','line','sop','operator'];
const defaultIntake={organization:'广西示例果汁企业',license:'SC45••••••••',processingProduct:'NFC 柑橘汁',material:'沃柑鲜果',plannedQuantity:'20',unit:'吨',arrivalDate:'2026-09-10',batch:'B-0903-001',origin:'广西南宁武鸣',harvestDate:'2026-09-02',brix:'12.8',supplier:'武鸣示例果园',inspectionReport:'农残检测报告待上传',fertilizerSupplier:'示例农资公司',fertilizerBrand:'柑橘专用肥 A',line:'榨汁线 B',sop:'企业 SOP v2.1',processStart:'2026-09-10T08:30',washWater:'生产用水检测合格',temperature:'4',additive:'未使用',operator:'生产员 D'};
const defaultReport={agency:'广西某农业农村局',department:'产业发展科',preparedBy:'业务经办人',title:'柑橘产业业务工作报告',region:'广西',period:'2026 年度',reportType:'业务工作报告',template:'通用业务工作报告模板',templateFile:'',purpose:'汇总本次 Agent 辅助完成的业务工作，形成可复核、可流转的工作成果。',generated:false,generatedAt:''};
const tradeCandidates=[
  {id:'SD-01',seller:'山东临沂示例合作社',origin:'山东临沂',material:'柑橘鲜果',quantity:90,brix:12.4,arrival:'11.12',docs:'完整',score:91,label:'优先推荐'},
  {id:'JX-02',seller:'江西赣州示例果业',origin:'江西赣州',material:'脐橙鲜果',quantity:120,brix:12.2,arrival:'11.14',docs:'完整',score:88,label:'备选'},
  {id:'GX-03',seller:'广西武鸣示例果园',origin:'广西南宁',material:'沃柑鲜果',quantity:70,brix:12.8,arrival:'11.10',docs:'完整',score:null,label:'数量不足'}
];
export function cleanIntake(value) {
  const data={...defaultIntake,...value};
  const missing=requiredIntake.filter(key=>String(data[key]??'').trim()==='');
  const issues=[];
  const rawQuantity=Number(String(data.plannedQuantity).replace(/,/g,'').trim());
  const normalizedBatch=String(data.batch??'').trim().toUpperCase();
  const brix=Number(String(data.brix).trim());
  if(!Number.isFinite(rawQuantity)||rawQuantity<=0)issues.push('计划用量不是有效正数');
  if(!Number.isFinite(brix)||brix<0||brix>40)issues.push('糖度超出 0—40 °Brix 合理范围');
  if(normalizedBatch&&!/^[A-Z0-9-]{5,30}$/.test(normalizedBatch))issues.push('批次编号格式不统一');
  if(data.harvestDate&&!/^\d{4}-\d{2}-\d{2}$/.test(data.harvestDate))issues.push('采收日期格式不统一');
  const quantityInTons=Number.isFinite(rawQuantity)?Number((data.unit==='千克'?rawQuantity/1000:rawQuantity).toFixed(3)):null;
  const standardized={...data,batch:normalizedBatch,plannedQuantity:quantityInTons,unit:'吨',brix:Number.isFinite(brix)?Number(brix.toFixed(1)):null};
  return {missing,issues,standardized,valid:missing.length===0&&issues.length===0,score:Math.max(0,Math.round(100-missing.length*7-issues.length*10))};
}
export function buildReportDocument(value, work={}) {
  const report={...defaultReport,...value};
  const summary={batch:'待补充',material:'待补充',quantity:'待补充',quality:'待核验',processing:'待补充',demand:'待补充',matches:'0 个',connections:'0 个',dataScore:'待评估',issues:['正式使用前请复核事实、检测原件、审批意见与责任人。'],...work};
  const template=report.templateFile?`单位模板：${report.templateFile}`:report.template;
  const issues=(summary.issues?.length?summary.issues:['当前未识别到待补事项。']).map(item=>`<li>${esc(item)}</li>`).join('');
  const generatedAt=report.generatedAt||new Date().toLocaleString('zh-CN');
  return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+esc(report.title)+'</title><style>@page{margin:24mm}body{font:16px/1.85 "Microsoft YaHei",sans-serif;max-width:900px;margin:48px auto;color:#161616}h1{text-align:center;font-size:30px;margin:72px 0 18px}h2{margin-top:32px;padding-bottom:8px;border-bottom:1px solid #bbb;font-size:20px}h3{font-size:17px;margin:22px 0 8px}p{margin:8px 0}.meta{text-align:center;color:#555}.summary{width:100%;border-collapse:collapse;margin:16px 0}.summary th,.summary td{padding:10px 12px;border:1px solid #bbb;text-align:left}.summary th{width:22%;background:#f4f4f4}.sign{margin-top:48px;text-align:right}.note{color:#555;font-size:13px}.workflow{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}.workflow span{padding:12px;border:1px solid #bbb;text-align:center;background:#fafafa}.bars{display:flex;align-items:end;height:180px;gap:24px;border-bottom:1px solid #999;margin:16px 0}.bar{width:76px;background:#333;color:#fff;text-align:center;padding-top:8px}</style><body><h1>'+esc(report.title)+'</h1><p class="meta">'+esc(report.agency)+' · '+esc(report.department)+'<br>'+esc(report.period)+' · '+esc(report.region)+'</p><h2>一、报告说明</h2><table class="summary"><tr><th>报告类型</th><td>'+esc(report.reportType)+'</td></tr><tr><th>采用模板</th><td>'+esc(template)+'</td></tr><tr><th>经办人员</th><td>'+esc(report.preparedBy)+'</td></tr><tr><th>工作目的</th><td>'+esc(report.purpose)+'</td></tr></table><p class="note">本报告由系统依据本次工作过程形成初稿。事实数据、检测结论、合同条件和审批意见须由使用单位复核后定稿。</p><h2>二、本次工作完成情况</h2><div class="workflow"><span>数据采集与清洗</span><span>加工过程记录</span><span>供需匹配分析</span><span>成果汇总成文</span></div><table class="summary"><tr><th>原料批次</th><td>'+esc(summary.batch)+'</td></tr><tr><th>原料与数量</th><td>'+esc(summary.material)+' · '+esc(summary.quantity)+'</td></tr><tr><th>质量信息</th><td>'+esc(summary.quality)+'</td></tr><tr><th>加工任务</th><td>'+esc(summary.processing)+'</td></tr><tr><th>采购需求</th><td>'+esc(summary.demand)+'</td></tr><tr><th>数据质量</th><td>'+esc(summary.dataScore)+'</td></tr></table><h2>三、业务分析结果</h2><h3>（一）原料与批次情况</h3><p>本次工作围绕批次 '+esc(summary.batch)+' 开展，原料信息为 '+esc(summary.material)+'，计划处理数量为 '+esc(summary.quantity)+'。现有质量信息：'+esc(summary.quality)+'。</p><h3>（二）加工与过程管理</h3><p>'+esc(summary.processing)+'。生产参数、SOP 版本及放行结论应以单位批准记录为准。</p><h3>（三）供需匹配与对接</h3><p>当前需求为“'+esc(summary.demand)+'”，系统筛得 '+esc(summary.matches)+' 候选，已形成 '+esc(summary.connections)+' 对接申请或草稿。匹配结果仅用于业务筛选，价格、运费、验收及合同条款须由双方确认。</p><h2>四、图表与业务趋势</h2><div class="bars"><div class="bar" style="height:45%">采集<br>16</div><div class="bar" style="height:58%">加工<br>3</div><div class="bar" style="height:72%">匹配<br>'+esc(summary.matches)+'</div><div class="bar" style="height:86%">报告<br>1</div></div><p class="note">图表用于说明本次工作成果结构；正式报送前须由主管单位复核统计口径。</p><h2>五、风险与待补事项</h2><ul>'+issues+'</ul><h2>六、工作成效</h2><ol><li>形成一套可追溯的原料批次与加工任务底稿。</li><li>将供应、需求和匹配条件统一到可核验字段。</li><li>形成可供内部流转、会议汇报或后续报送使用的业务报告初稿。</li></ol><h2>七、下一步工作计划</h2><ol><li>补齐缺失字段、检测原件、审批意见和责任人签字。</li><li>由业务部门复核关键结论，必要时调整单位自有模板和章节。</li><li>经审核后形成正式版本，并将行动项纳入后续跟踪。</li></ol><p class="sign">经办人：'+esc(report.preparedBy)+'<br>生成时间：'+esc(generatedAt)+'</p></body></html>';
}
const candidates=[
  {id:'A',place:'广西南宁',batch:'B-0903-001',quantity:20,brix:12.8,arrival:'2026-09-08',report:true,preferences:['完整投入品记录','可寄样']},
  {id:'B',place:'广西来宾',batch:'B-0902-007',quantity:18,brix:12.5,arrival:'2026-09-09',report:false,preferences:['可寄样']},
  {id:'C',place:'广西崇左',batch:'B-0902-011',quantity:22,brix:11.2,arrival:'2026-09-08',report:true,preferences:['稳定供货']}
];
const supplies=[
  {id:'B-0903-001',name:'武鸣沃柑',origin:'广西 · 南宁',type:'沃柑',quantity:'20.0 吨',brix:'12.8 °Brix',period:'09.05—09.15',pending:false,buyers:5,source:'企业自报 · 检测报告已上传',x:275},
  {id:'B-0902-008',name:'赣南脐橙',origin:'江西 · 赣州',type:'脐橙',quantity:'35.0 吨',brix:'12.3 °Brix',period:'11.01—11.20',pending:false,buyers:3,source:'企业自报 · 待人工核验',x:699},
  {id:'B-0901-015',name:'柑橘果皮',origin:'示例加工企业',type:'果皮',quantity:'3.0 吨',brix:'加工原料',period:'待确认',pending:true,buyers:0,source:'缺少水分指标与检测资料',x:1122}
];
export function quantityRange(value) {
  const parts=String(value).trim().split(/\s*[-—–~～至]\s*/);
  if(parts.length<1||parts.length>2||parts.some(p=>!/^\d+(\.\d+)?$/.test(p)))return null;
  const min=Number(parts[0]),max=Number(parts[1]??parts[0]);
  return min>0&&max>=min?[min,max]:null;
}
export function evaluateCandidate(c,r) {
  const range=quantityRange(r.quantity),brix=Number(r.brix);
  const checks=[String(r.brix).trim()!==''&&Number.isFinite(brix)&&brix>=0&&c.brix>=brix,!!range&&c.quantity>=range[0]&&c.quantity<=range[1],/^\d{4}-\d{2}-\d{2}$/.test(r.delivery)&&c.arrival<=r.delivery,!r.report||c.report];
  const compatible=r.material==='沃柑鲜果'&&['广西及周边','全国'].includes(r.region);
  const fit=compatible&&checks.every(Boolean),missing=compatible&&!c.report&&r.report&&checks.slice(0,3).every(Boolean);
  const prefs=r.preferences.filter(p=>c.preferences.includes(p)).length;
  return {checks,fit,missing,prefs,score:fit?Math.min(100,80+prefs*6):null,label:fit?'可推荐':missing?'待补资料':'不符合',tone:fit?'black':missing?'orange':'red',compatible};
}
const button=(label,action,primary=false,icon='',extra='')=>`<button type="button" class="btn${primary?' primary':''}" data-action="${action}" ${extra}>${icon?svg(icon):''}${esc(label)}</button>`;
const pill=(text,tone='')=>`<span class="pill ${tone}">${esc(text)}</span>`;
const field=(name,value,label,type='text',extra='')=>`<input name="${name}" aria-label="${esc(label)}" type="${type}" value="${esc(value)}" ${extra}>`;
const select=(name,value,label,options)=>`<select name="${name}" aria-label="${esc(label)}">${options.map(o=>`<option${value===o?' selected':''}>${esc(o)}</option>`).join('')}</select>`;
const header=(code,title,desc)=>`<header class="page-head"><div class="eyebrow">CITRUS AI · ${code}</div><h1>${title}</h1><p class="subtitle">${desc}</p></header>`;
const notice=(title,text)=>`<aside class="notice">${svg('info',19)}<div><strong>${title}</strong>${text?`<p>${text}</p>`:''}</div></aside>`;
const tabs=(items,current)=>`<div class="tabs" role="tablist">${items.map((t,i)=>`<button type="button" role="tab" class="tab${current===i?' active':''}" aria-selected="${current===i}" data-tab="${i}">${t}</button>`).join('')}</div>`;
const stats=items=>`<div class="stats">${items.map(([icon,label,value])=>`<div class="stat">${svg(icon,34)}<div><span>${label}</span><strong>${value}</strong></div></div>`).join('')}</div>`;
const equipment=(drafts=[],showAll=true)=>`<div class="equipment">${[['conveyor','清洗分选线 A','可用',''],['juice','榨汁线 B','占用中','orange'],['dryer','果皮干燥线 C','可预约','blue']].map(([i,n,s,c])=>`<div class="equipment-row">${svg(i,28)}<span>${n}</span><span class="availability"><i class="dot ${c}"></i>${s}</span></div>`).join('')}${drafts.map(d=>`<div class="equipment-row"><span>${esc(d.equipment)}</span>${pill('登记草稿')}</div>`).join('')}${showAll?'<button type="button" class="btn flat" data-action="equipment">查看全部设备 '+svg('arrow')+'</button>':''}</div>`;

export default function(component) {
  const {parentElement,data,setStateValue}=component;
  const root=parentElement.querySelector('.iw');
  const model=root._model||structuredClone(data.model||{});
  model.request={...defaultRequest,...model.request};
  model.connections=model.connections||[];
  model.tradeConnections=model.tradeConnections||[];
  model.production=model.production||[];
  model.supplies=model.supplies||[];
  model.intake={...defaultIntake,...model.intake};
  model.report={...defaultReport,...model.report};
  model.intakeAudit=model.intakeAudit||null;
  root._model=model;
  const view=data.view;
  const initialTab=view==='production'||view==='demand'?1:view==='match'?(model.matchOpenTab??1):0;
  if(root._view!==view&&view==='match')delete model.matchOpenTab;
  let tab=root._view===view?(root._tab??initialTab):initialTab;
  let selected=root._selected||'A';
  let listMode=root._listMode||false;
  let feedback='';
  const persist=()=>setStateValue('snapshot',structuredClone(model));
  const flash=message=>{feedback=message;render();};
  const downloadFile=(name,text,type='text/plain;charset=utf-8')=>{const url=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};

  function intakeProgress() {
    const audit=cleanIntake(model.intake);
    const completed=requiredIntake.length-audit.missing.length;
    return `<div class="collection-score"><span>必填字段完整度</span><strong>${completed}/${requiredIntake.length}</strong><div class="meter"><i style="width:${completed/requiredIntake.length*100}%"></i></div></div><h3>数据使用规则</h3><ul class="rule-list"><li>${svg('check',16)} 完整且格式正确：进入匹配与报告数据池</li><li>${svg('info',16)} 缺少必填项：标记待补，不参与推荐</li><li>${svg('alert',16)} 数值异常或无来源：进入人工复核</li></ul><div class="field-legend"><span><i class="required-dot"></i>必填 ${completed}/${requiredIntake.length}</span><span><i></i>选填项用于追溯与排序</span></div>`;
  }
  function dataCollection() {
    const r=model.intake,audit=model.intakeAudit||cleanIntake(r);
    const label=(text,input,required=true)=>`<label class="data-field"><span>${esc(text)} ${required?'<b>必填</b>':'<em>选填</em>'}</span>${input}</label>`;
    const collection=`<div class="intake-layout"><form id="intake-form" class="data-form"><section class="panel intake-section"><div class="section-heading"><h2>01 加工任务与原料需求</h2><small>明确要加工什么、需要什么原料和数量</small></div><div class="data-grid">${label('企业/机构名称',field('organization',r.organization,'企业或机构名称'))}${label('食品生产许可证',field('license',r.license,'食品生产许可证'),false)}${label('目标产品',field('processingProduct',r.processingProduct,'目标产品'))}${label('原料类型',select('material',r.material,'原料类型',['沃柑鲜果','脐橙鲜果','柑橘果皮','柑橘鲜果']))}${label('计划用量',`<div class="unit-input">${field('plannedQuantity',r.plannedQuantity,'计划用量','number','min="0" step="0.1"')}${select('unit',r.unit,'数量单位',['吨','千克'])}</div>`)}${label('期望到厂日期',field('arrivalDate',r.arrivalDate,'期望到厂日期','date'),false)}</div></section><section class="panel intake-section"><div class="section-heading"><h2>02 原料批次与验收</h2><small>批次、产地、质量指标和证据</small></div><div class="data-grid">${label('原料批次号',field('batch',r.batch,'原料批次号'))}${label('产地',field('origin',r.origin,'产地'))}${label('采收日期',field('harvestDate',r.harvestDate,'采收日期','date'))}${label('糖度',`<div class="value-input">${field('brix',r.brix,'糖度','number','min="0" max="40" step="0.1"')}<span>°Brix</span></div>`)}${label('供应主体',field('supplier',r.supplier,'供应主体'))}${label('检测报告',field('inspectionReport',r.inspectionReport,'检测报告'),false)}${label('肥料供应商',field('fertilizerSupplier',r.fertilizerSupplier,'肥料供应商'),false)}${label('肥料品牌/产品',field('fertilizerBrand',r.fertilizerBrand,'肥料品牌或产品'),false)}</div></section><section class="panel intake-section"><div class="section-heading"><h2>03 加工过程追溯</h2><small>记录设备、工艺版本、参数来源和人员</small></div><div class="data-grid">${label('加工产线',field('line',r.line,'加工产线'))}${label('SOP 版本',field('sop',r.sop,'SOP 版本'))}${label('开始时间',field('processStart',r.processStart,'加工开始时间','datetime-local'),false)}${label('清洗用水状态',field('washWater',r.washWater,'清洗用水状态'),false)}${label('冷藏温度',`<div class="value-input">${field('temperature',r.temperature,'冷藏温度','number','step="0.1"')}<span>°C</span></div>`,false)}${label('食品添加剂/辅料',field('additive',r.additive,'食品添加剂或辅料'),false)}${label('操作负责人',field('operator',r.operator,'操作负责人'))}</div></section></form><aside class="panel collection-summary"><h2>采集状态</h2><div id="intake-progress">${intakeProgress()}</div><div class="evidence-note">${svg('shield',17)}<span>字段依据生产追溯、进货查验和加工过程控制需要设计；具体限量值必须按产品类别核对现行标准。</span></div></aside></div>`;
    const cleaning=`<div class="cleaning-layout"><section class="panel cleaning-main"><div class="section-heading"><h2>数据清洗结果</h2><small>只有有效数据进入匹配、可视化与报告</small></div><div class="clean-flow"><div><span>原始记录</span><b>18</b></div><i>→</i><div><span>格式标准化</span><b>16</b></div><i>→</i><div><span>有效数据</span><b>${audit.valid?'16':'12'}</b></div></div><div class="table-wrap"><table><thead><tr><th>规则</th><th>处理前</th><th>处理后</th><th>状态</th></tr></thead><tbody><tr><td>数量与单位</td><td>${esc(r.plannedQuantity)} ${esc(r.unit)}</td><td>${esc(audit.standardized.plannedQuantity)} 吨</td><td>${pill('已统一')}</td></tr><tr><td>批次编号</td><td>${esc(r.batch)}</td><td>${esc(audit.standardized.batch)}</td><td>${pill('已规范')}</td></tr><tr><td>糖度格式</td><td>${esc(r.brix)}</td><td>${esc(audit.standardized.brix)} °Brix</td><td>${pill(audit.issues.length?'需复核':'有效',audit.issues.length?'orange':'')}</td></tr><tr><td>重复记录</td><td>2 条相似记录</td><td>合并为 1 条，保留来源</td><td>${pill('已去重')}</td></tr></tbody></table></div></section><aside class="panel cleaning-side"><h2>质量门禁</h2><div class="quality-ring"><b>${audit.score}</b><span>数据质量分</span></div><h3>待处理项</h3>${audit.missing.length||audit.issues.length?`<ul>${audit.missing.map(k=>`<li>缺少必填字段：${esc(k)}</li>`).join('')}${audit.issues.map(i=>`<li>${esc(i)}</li>`).join('')}</ul>`:'<p class="ok-line">'+svg('check',17)+' 当前示例记录可进入有效数据池</p>'}<div class="evidence-note">不完整、不可信或用途不明确的数据不会进入推荐结果。</div></aside></div>`;
    const standards=`<div class="standards-layout"><section class="panel standard-intro"><h2>加工采集依据</h2><p>以下依据用于决定“采什么数据、在哪个环节采”。系统不自动给出合规结论，企业仍需按产品类别、工艺和属地要求核对现行文本。</p><div class="standard-map"><span>原料进货查验</span><i>→</i><span>过程卫生控制</span><i>→</i><span>添加剂与限量</span><i>→</i><span>检验与追溯</span></div></section><section class="standard-list"><a class="panel standard-card" target="_blank" rel="noopener" href="https://www.samr.gov.cn/spxts/gzdt/art/2023/art_a54cbedacfd44ff5bd2b40504ea98649.html"><b>中华人民共和国食品安全法</b><span>法律 · 生产经营、进货查验、过程控制与追溯</span><em>查看官方来源 →</em></a><a class="panel standard-card" target="_blank" rel="noopener" href="https://www.nhc.gov.cn/sps/c100088/201306/998283ee924740e98d630ac660e887f3.shtml"><b>GB 14881—2013 食品生产通用卫生规范</b><span>加工场所、设备、原料、过程控制、检验与记录</span><em>查看官方来源 →</em></a><a class="panel standard-card" target="_blank" rel="noopener" href="https://www.nhc.gov.cn/sps/c100088/202403/bda120e678df4a49a8beb90852559d7c.shtml"><b>GB 2760—2024 食品添加剂使用标准</b><span>食品添加剂使用原则、品种和使用规定</span><em>查看官方来源 →</em></a><a class="panel standard-card" target="_blank" rel="noopener" href="https://www.nhc.gov.cn/sps/c100088/202509/5dc5e1e2b26d4d27a7913b9e71bbe931.shtml"><b>GB 2762—2025 食品中污染物限量</b><span>污染物限量 · 应按原料和产品类别核对</span><em>查看官方来源 →</em></a><a class="panel standard-card" target="_blank" rel="noopener" href="https://jgs.moa.gov.cn/nybz/202103/t20210318_6364007.htm"><b>GB 2763—2021 食品中农药最大残留限量</b><span>鲜果验收和农残报告核验基础</span><em>查看官方来源 →</em></a><a class="panel standard-card" target="_blank" rel="noopener" href="https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_f5a0c2c6c3724a6aad91645043b012ce.html"><b>中华人民共和国农产品质量安全法</b><span>产地、生产记录、承诺达标与质量追溯</span><em>查看官方来源 →</em></a></section></div>`;
    const actions=tab===1?button('导出有效数据','download-data',false,'download')+button('重新清洗','clean-data',true,'filter'):tab===2?'':button('保存采集草稿','save-intake')+button('清洗并入库','clean-data',true,'filter');
    return header('DATA','产业数据采集','把原料、需求与加工过程转成可匹配、可追溯、可报告的数据')+`<div class="toolbar">${tabs(['数据采集','数据清洗','标准依据'],tab)}<div class="actions">${actions}</div></div>`+(tab===0?collection:tab===1?cleaning:standards);
  }

  function production() {
    const extra=model.production.map(p=>`<tr><td>${esc(p.batch)}</td><td>${esc(p.material)}</td><td>${esc(p.line)}</td><td>${pill('进行中','blue')}</td></tr>`).join('');
    const records=`<section class="panel"><h2 class="panel-title">加工批次</h2><div class="table-wrap"><table><thead><tr><th>批次</th><th>原料与投入</th><th>当前工序</th><th>状态</th></tr></thead><tbody>${extra}<tr><td>P-0903-01</td><td>沃柑 · 20.0 t</td><td>清洗分选</td><td>${pill('进行中','blue')}</td></tr><tr><td>P-0902-02</td><td>脐橙 · 15.0 t</td><td>榨汁</td><td>${pill('待复核','orange')}</td></tr><tr><td>P-0901-03</td><td>果皮 · 3.0 t</td><td>干燥</td><td>${pill('已归档')}</td></tr></tbody></table></div></section>`;
    const process=`<section class="panel batch-panel"><div class="process-box"><h2>当前批次：P-0903-01</h2><div class="process">${['原料接收','清洗分选','榨汁','后续处理','成品检验'].map((s,i)=>`<div class="step${i<2?' done':''}"><i>${i<2?svg('tick',19):i+1}</i><span>${s}</span></div>`).join('')}</div><div class="batch-meta"><div><span>原料批次</span>B-0903-001</div><div><span>生产负责人</span>生产员 D</div><div><span>记录来源</span>企业填报</div></div></div></section>`;
    const audit=`<section class="panel audit"><h2>参数与审核</h2><dl><div><dt>参数来源</dt><dd>企业 SOP v2.1</dd></div><div><dt>参数可见性</dt><dd>企业私有</dd></div><div><dt>审核状态</dt><dd class="orange-text">待质控复核</dd></div></dl><div class="notice">${svg('info',16)}<span>具体工艺参数以经批准的 SOP 为准；AI 建议不可直接作为生产放行依据。</span></div>${button('查看参数版本','sop',false,'','style="width:100%"')}</section>`;
    let body=`<div class="production-grid">${records}<section class="panel"><h2 class="panel-title">设备与档期</h2>${equipment(model.equipment||[])}</section>${process}${audit}</div>`;
    if(tab===0)body=`<div class="production-grid"><section class="panel"><h2 class="panel-title">加工能力与设备</h2>${equipment(model.equipment||[])}</section><section class="panel audit"><h2>可用档期</h2><dl><div><dt>清洗分选线 A</dt><dd>09.05 起 · 可用</dd></div><div><dt>榨汁线 B</dt><dd>09.10 起 · 需确认</dd></div><div><dt>果皮干燥线 C</dt><dd>09.06 起 · 可预约</dd></div></dl>${notice('演示档期','实际排产需由生产负责人确认。')}</section></div>`;
    if(tab===2)body=`<div class="production-grid">${audit}<section class="panel audit"><h2>参数版本记录</h2><p style="margin-top:16px">企业 SOP v2.1 · 当前待质控复核</p><p style="margin-top:16px">企业 SOP v2.0 · 历史归档</p>${notice('审核边界','此处展示参数版本，不提供未经批准的生产参数。')}</section></div>`;
    return header('PRODUCTION','加工能力与生产记录','管理设备、加工批次与参数版本，让生产过程可追溯')+`<div class="toolbar">${tabs(['加工能力','生产记录','参数模板'],tab)}<div class="actions">${button('登记设备','register-equipment')}${button('新建加工批次','new-production',true,'plus')}</div></div>`+stats([['factory','可用产线','3'],['clipboard','在制批次',2+model.production.length],['shield','待复核记录','4'],['chart','本月已完成','18']])+body;
  }

  function supplyCard(s) {
    return `<article class="panel supply-card"><div class="photo"><img src="${esc(data.photo)}" alt="${esc(s.name)}示例照片" style="--crop-left:${-(s.x/389)*100}%"></div><div class="supply-body"><div class="supply-title"><h2>${esc(s.name)}</h2><span class="live${s.pending?' pending':''}"><i class="dot${s.pending?' orange':''}"></i>${s.pending?'待补资料':'上架中'}</span></div><p class="supply-origin">${esc(s.origin)} ｜ ${esc(s.id)}</p><dl class="supply-details"><div><dt>可供数量</dt><dd>${esc(s.quantity)}</dd></div><div><dt>${s.type==='果皮'?'用途':'糖度'}</dt><dd>${esc(s.brix)}</dd></div><div><dt>供应时间</dt><dd>${esc(s.period)}</dd></div><div><dt>价格</dt><dd>面议</dd></div></dl><div class="source-note${s.pending?' warning':''}">${svg(s.pending?'alert':'shield',15)}<span>${esc(s.source)}</span></div><div class="supply-actions">${button(s.pending?'补全资料':`查看匹配买家 ${s.buyers}`,s.pending?'complete-supply':`buyers-${s.id}`,s.pending)}${button(s.pending?'暂不可发布':'管理',`manage-${s.id}`,false,'',s.pending?'disabled':'')}</div></div></article>`;
  }
  function filteredSupplies() {
    const q=(root.querySelector('[name=supply-search]')?.value||'').trim().toLowerCase();
    const type=root.querySelector('[name=supply-type]')?.value||'全部品类';
    const status=root.querySelector('[name=supply-status]')?.value||'全部状态';
    return supplies.filter(s=>(!q||[s.name,s.origin,s.id].join(' ').toLowerCase().includes(q))&&(type==='全部品类'||type===s.type)&&(status==='全部状态'||(status==='待补资料')===s.pending));
  }
  function supplyResults() {
    const records=filteredSupplies();
    if(!records.length)return '<div class="panel empty">没有符合当前筛选条件的供应批次。</div>';
    if(listMode)return `<div class="panel table-wrap"><table><thead><tr><th>供应批次</th><th>产地</th><th>可供数量</th><th>状态</th><th>操作</th></tr></thead><tbody>${records.map(s=>`<tr><td>${esc(s.name)} · ${s.id}</td><td>${s.origin}</td><td>${s.quantity}</td><td>${pill(s.pending?'待补资料':'上架中',s.pending?'orange':'')}</td><td>${button('查看',`manage-${s.id}`)}</td></tr>`).join('')}</tbody></table></div>`;
    return `<div class="supply-grid">${records.map(supplyCard).join('')}</div>`;
  }
  function supply() {
    let body=`<div class="supply-filters"><label class="search-field">${svg('search')}${field('supply-search','','搜索供应','search','placeholder="搜索品种、产区、批次号"')}</label>${select('supply-type','全部品类','供应品类',['全部品类','沃柑','脐橙','果皮'])}${select('supply-status','全部状态','供应状态',['全部状态','上架中','待补资料'])}<div class="switcher">${button('列表','list',listMode,'list')}${button('卡片','cards',!listMode,'grid')}</div></div><div id="supply-results">${supplyResults()}</div>`;
    if(tab===1)body=`<section class="panel audit"><h2>匹配买家</h2><div class="equipment-row"><span>NFC 果汁加工原料采购</span><span>15—25 吨 · 糖度 ≥ 12.0 °Brix</span>${button('查看匹配','show-matches')}</div>${notice('演示匹配','以上为示例采购需求，不代表真实买家询盘。')}</section>`;
    if(tab===2)body=`<section class="panel audit"><h2>发布记录</h2>${model.supplies.length?model.supplies.map(s=>`<div class="equipment-row">${esc(s.name)} · ${esc(s.batch)} ${pill('会话草稿')}</div>`).join(''):'<p class="empty">本次会话尚无新建供应草稿。</p>'}</section>`;
    return header('SUPPLY','供应中心','将真实批次发布为供应单，找到合适的采购方')+`<div class="toolbar">${tabs(['我的供应','匹配买家','发布记录'],tab)}<div class="actions">${button('导入批次','import-supply',false,'upload')}${button('发布供应','new-supply',true,'plus')}</div></div>`+stats([['box','上架中','8'],['file','待补资料','2'],['chat','新增询盘','6'],['clock','即将到期','1']])+body+notice('发布与隐私','公开页仅展示授权信息；联系人与检测原件在双方同意后开放。供应单不是质量合格证明。');
  }

  function preview() {
    const r=model.request;
    const valid=[r.brix.trim()!==''&&Number.isFinite(Number(r.brix))&&Number(r.brix)>=0,!!quantityRange(r.quantity),!!r.delivery,r.report].filter(Boolean).length;
    return `<div class="preview-head"><h2>需求预览</h2>${pill(r.published?'会话演示 · 已发布':'草稿 · 未发布')}</div><h3>${esc(r.name||'未命名需求')}</h3><dl><div><dt>原料</dt><dd>${esc(r.material)}</dd></div><div><dt>数量</dt><dd>${esc(r.quantity||'待填写')} 吨</dd></div><div><dt>糖度</dt><dd>≥ ${esc(r.brix||'待填写')} °Brix</dd></div><div><dt>到厂</dt><dd>${esc(r.delivery.replaceAll('-','.'))} 前</dd></div><div><dt>目的地</dt><dd>${esc(r.destination)}</dd></div></dl><div class="preflight"><h3>发布前检查</h3><p>${svg('check',18)} ${valid} 项必须条件已填写</p><p class="${r.checklist?'':'warn'}">${svg(r.checklist?'check':'info',18)} ${r.checklist?`已选择清单：${esc(r.checklist)}`:'验收清单待上传'}</p></div><p class="preview-note">发布后系统将按硬条件筛选供应批次。<br>信息缺失会标为待补充，不会默认合格。</p>`;
  }
  function demand() {
    const r=model.request;
    const basic=`<section class="panel form-section"><div class="section-heading"><h2>01 基础信息</h2></div><div class="basic-fields"><label class="inline-field">需求名称${field('name',r.name,'需求名称')}</label><label class="inline-field">原料类型${select('material',r.material,'原料类型',['沃柑鲜果','脐橙鲜果','柑橘果皮'])}</label><label class="inline-field">用途${field('use',r.use,'用途')}</label><label class="inline-field">采购地区${select('region',r.region,'采购地区',['广西及周边','江西及周边','全国'])}</label></div></section>`;
    const hard=`<section class="panel form-section"><div class="section-heading"><h2>02 必须满足的条件</h2><small>未满足或缺少证据的候选，不进入合格推荐</small></div><div class="must-rows"><div class="must-row"><span class="field-name">糖度</span><label class="value-input"><span>≥</span>${field('brix',r.brix,'糖度下限','number','min="0" max="40" step="0.1"')}<span>°Brix</span></label><label class="check"><input type="checkbox" checked disabled>必须</label></div><div class="must-row"><span class="field-name">采购数量</span><label class="value-input">${field('quantity',r.quantity,'采购数量')}<span>吨</span></label><label class="check"><input type="checkbox" checked disabled>必须</label></div><div class="must-row"><span class="field-name">到厂日期</span>${field('delivery',r.delivery,'到厂日期','date')}<label class="check"><input type="checkbox" checked disabled>必须</label></div><div class="must-row report-row"><span class="field-name">有效检测报告</span><label class="check"><input name="report" type="checkbox" ${r.report?'checked':''}>按企业验收清单提供</label><label class="file-label">上传验收清单<input name="checklist" type="file" accept=".pdf,.png,.jpg,.xlsx,.docx"></label></div></div></section>`;
    const prefs=`<section class="panel form-section"><div class="section-heading"><h2>03 偏好条件</h2><small>用于排序，不代替必须条件</small></div><div class="chips">${defaultRequest.preferences.map(p=>`<button type="button" class="chip${r.preferences.includes(p)?' selected':''}" aria-pressed="${r.preferences.includes(p)}" data-pref="${p}">${p} ${r.preferences.includes(p)?'×':'＋'}</button>`).join('')}</div></section>`;
    const delivery=`<section class="panel form-section"><div class="section-heading"><h2>04 交付与预算</h2></div><div class="delivery-fields"><label>交货地点${field('destination',r.destination,'交货地点')}</label><label>预算范围${field('budget',r.budget,'预算范围')}</label><label>联系方式<input value="双方同意后开放" aria-label="联系方式" readonly></label></div></section>`;
    let body=`<div class="demand-layout"><form id="demand-form" class="form-sections">${basic}${hard}${prefs}${delivery}</form><aside id="preview" class="panel preview">${preview()}</aside></div>`;
    if(tab===0)body=`<section class="panel audit"><h2>我的需求</h2><div class="equipment-row"><span>${esc(r.name)}</span>${pill(r.published?'会话演示 · 已发布':'草稿')}${button('继续编辑','edit-demand')}${button('查看匹配','show-matches')}</div></section>`;
    if(tab===2)body=`<section class="panel audit"><h2>历史模板</h2><div class="equipment-row"><span>NFC 果汁加工原料采购 · 示例模板</span>${button('使用模板','use-template')}</div><p>使用模板会替换当前草稿，使用前可确认。</p></section>`;
    return header('DEMAND','需求中心','把采购标准写清楚，让合适的原料主动找到你')+`<div class="toolbar">${tabs(['我的需求','新建采购需求','历史模板'],tab)}<div class="actions">${button('保存草稿','save-demand')}${button('发布需求','publish-demand',true)}</div></div>`+body;
  }
  function matchDetails(c) {
    const r=model.request,e=evaluateCandidate(c,r),requested=model.connections.includes(c.id);
    const rows=[['糖度',`≥ ${r.brix} °Brix`,`${c.brix.toFixed(1)} °Brix`],['数量',`${r.quantity} 吨`,`${c.quantity.toFixed(1)} 吨`],['到厂日期',`${r.delivery.slice(5).replace('-','.')} 前`,`可于 ${c.arrival.slice(5).replace('-','.')} 到厂`],['检测资料',r.report?'验收清单要求':'未设为必须',c.report?'对应报告已核验':'检测报告缺失']];
    return `<div class="detail-head"><div><h2>供应主体 ${c.id}</h2><p>批次 ${c.batch} · ${c.report?'资料已核验':'资料待补充'}</p></div>${button(requested?'已生成申请':'申请对接','connect',true,'',!e.fit||requested?'disabled':'')}</div><div class="match-stats">${[['lock','必须条件',`${e.checks.filter(Boolean).length}/4`],['file','资料完整度',c.report?'100%':'75%'],['star','偏好满足',`${e.prefs}/${r.preferences.length}`]].map(([i,l,v])=>`<div class="match-stat">${svg(i,28)}<div><span>${l}</span><b>${v}</b></div></div>`).join('')}</div><h3>逐项条件对比</h3><div class="compare table-wrap"><table><thead><tr><th>必须条件</th><th>采购要求</th><th>批次情况</th><th>结果</th></tr></thead><tbody>${rows.map(([l,a,b],i)=>`<tr><td>${l}</td><td>${esc(a)}</td><td>${esc(b)}</td><td><span class="result${e.checks[i]?'':' bad'}">${svg(e.checks[i]?'check':'info',14)}${e.checks[i]?'满足':i===3?'待补':'不符合'}</span></td></tr>`).join('')}</tbody></table></div><section class="reasons"><h3>${e.fit?'推荐理由':'暂不推荐原因'}</h3>${e.fit?'<ul><li>数量与交期符合本次采购条件</li><li>支持寄样，投入品记录可申请查看</li></ul>':`<ul>${!e.compatible?'<li>原料类型或采购地区与候选不符</li>':''}${rows.filter((_,i)=>!e.checks[i]).map(([l])=>`<li>${l}未满足或缺少相应证据</li>`).join('')}</ul>`}<p>价格仍需双方协商</p></section>`;
  }
  function matching() {
    const r=model.request;
    const list=candidates.map(c=>{const e=evaluateCandidate(c,r);return `<button type="button" class="candidate${selected===c.id?' active':''}" data-candidate="${c.id}" aria-pressed="${selected===c.id}"><div class="candidate-title"><span>供应主体 ${c.id} <small>· ${c.place}</small></span>${pill(e.label,e.tone)}</div><p>批次 ${c.batch}</p>${e.fit?`<div class="score">适配度 <b>${e.score}</b></div>`:''}<span class="facts">${c.quantity.toFixed(1)} 吨 · ${c.brix.toFixed(1)} °Brix</span><small class="reason">${e.fit?'4 项必须条件满足':e.missing?'检测报告缺失 · 暂不进入推荐':!e.compatible?'原料或地区不符 · 已排除':!e.checks[0]?'糖度低于要求 · 已排除':'硬条件未满足 · 已排除'}</small></button>`;}).join('');
    const current=`<div class="match-actions">${button('调整需求','edit-demand')}${button('重新匹配','rematch')}</div><div class="panel query"><strong>采购需求： ${esc(r.name)}</strong>${[r.material,`${r.quantity} 吨`,`糖度 ≥ ${r.brix} °Brix`,`${r.delivery.slice(5).replace('-','.')} 前到厂`].map(v=>`<span class="tag">${esc(v)}</span>`).join('')}</div><div class="match-layout"><aside class="panel candidates"><h2>候选供应&nbsp; 3</h2>${list}</aside><section id="match-detail" class="panel match-detail">${matchDetails(candidates.find(c=>c.id===selected)||candidates[0])}</section></div>`;
    const trade=`<section class="panel trade-demand"><div><span class="eyebrow">采购方 · 重庆北碚示例加工厂</span><h2>NFC 果汁加工原料跨区域采购</h2><p>柑橘鲜果 · 80—120 吨 · 糖度 ≥ 11.8 °Brix · 11.15 前到厂</p></div><div class="trade-route">山东 / 江西 / 广西 <b>→</b> 重庆</div></section><div class="trade-grid">${tradeCandidates.map((c,i)=>`<article class="panel trade-card"><div class="trade-title"><h2>${esc(c.seller)}</h2>${pill(c.label,c.score?i===0?'black':'':'red')}</div><p>${esc(c.origin)} · ${esc(c.material)}</p><div class="trade-score">${c.score?`<b>${c.score}</b><span>商业适配度</span>`:'<b>—</b><span>暂不推荐</span>'}</div><dl><div><dt>可供数量</dt><dd>${c.quantity} 吨</dd></div><div><dt>糖度</dt><dd>${c.brix} °Brix</dd></div><div><dt>预计到厂</dt><dd>${c.arrival}</dd></div><div><dt>资料</dt><dd>${c.docs}</dd></div></dl>${button(c.score?'申请商业对接':'数量不满足',`trade-${c.id}`,i===0,'link',c.score?'':'disabled')}</article>`).join('')}</div>${notice('商业边界','匹配只用于筛选候选。采购价、运费、发票、原料验收和合同条款须由双方确认。')}`;
    const records=`<section class="panel audit"><h2>对接记录</h2>${model.tradeConnections?.length?model.tradeConnections.map(id=>`<div class="equipment-row"><span>${esc(id)} · 重庆采购场景</span>${pill('申请草稿')}</div>`).join(''):'<p class="empty">本次会话尚无商业对接申请。</p>'}${notice('联系人保护','双方确认前不开放手机号、地址、检测原件等敏感信息。')}</section>`;
    return header('CONNECTIONS','商业对接','连接跨区域原料供应与加工需求，先筛条件再谈交易')+`<div class="toolbar">${tabs(['当前需求匹配','跨区域商机','对接记录'],tab)}</div>`+(tab===0?current:tab===1?trade:records)+(tab===0?notice('匹配建议不等于检测放行；原件与联系人需双方授权后查看。',''):'')+'<p class="footnote">规则版本 v1.1 · 演示数据 · 2026.09</p>';
  }

  function reportWorkSummary() {
    const intake=model.intake||defaultIntake;
    const audit=model.intakeAudit||cleanIntake(intake);
    const request=model.request||defaultRequest;
    const fitCount=candidates.filter(c=>evaluateCandidate(c,request).fit).length;
    const tradeCount=tradeCandidates.filter(c=>c.score).length;
    const issues=[...audit.missing.map(key=>`缺少必填字段：${key}`),...audit.issues];
    if(!String(intake.inspectionReport||'').trim()||String(intake.inspectionReport).includes('待上传'))issues.push('检测报告尚未完成原件核验。');
    return {
      batch:intake.batch||'待补充',
      material:`${intake.material||'待补充'} · ${intake.origin||'产地待补充'}`,
      quantity:intake.plannedQuantity?`${intake.plannedQuantity} ${intake.unit||'吨'}`:'待补充',
      quality:intake.brix?`${intake.brix} °Brix · ${intake.inspectionReport||'检测待补充'}`:'待补充',
      processing:intake.processingProduct?`${intake.processingProduct} · ${intake.line||'产线待补充'} · ${intake.sop||'SOP 待补充'}`:'待补充',
      demand:request.name||'尚未填写采购需求',
      matches:`${fitCount+tradeCount} 个`,
      connections:`${(model.connections||[]).length+(model.tradeConnections||[]).length} 个`,
      dataScore:`${audit.score}/100`,
      issues
    };
  }

  function reportPreview() {
    const r=model.report;
    const s=reportWorkSummary();
    return `<div class="report-paper"><div class="report-cover"><span>${esc(r.agency)} · ${esc(r.department||'')}</span><h2>${esc(r.title)}</h2><p>${esc(r.period)} · ${esc(r.region)} · ${esc(r.reportType||'业务工作报告')}</p>${r.generated?'<b class="report-generated-mark">已生成工作报告初稿</b>':''}</div><div class="report-body"><h3>报告摘要</h3><p>本报告汇总本次 Agent 工作过程中形成的原料批次、加工过程、供需需求、匹配结果及图表成果，供单位内部复核、会议汇报和后续流转使用。</p><h3>本次工作完成情况</h3><div class="report-summary-list"><div><span>批次</span><b>${esc(s.batch)}</b></div><div><span>原料与数量</span><b>${esc(s.material)} · ${esc(s.quantity)}</b></div><div><span>加工任务</span><b>${esc(s.processing)}</b></div><div><span>供需匹配</span><b>${esc(s.matches)} · 对接草稿 ${esc(s.connections)}</b></div></div><h3>报告结构</h3><ol><li>报告说明与工作范围</li><li>本次工作完成情况与数据底稿</li><li>业务分析结果与图表</li><li>风险待办、行动计划与附录</li></ol><small>正式定稿前须由使用单位复核事实、检测原件、统计口径和审批意见。</small></div></div>`;
  }
  function reports() {
    const r=model.report;
    const s=reportWorkSummary();
    const editor=`<div class="report-layout"><form id="report-form" class="panel report-editor"><div class="section-heading"><h2>报告配置</h2><small>完成工作后，按单位要求生成正式业务报告</small></div><div class="report-form-grid"><label>使用单位${field('agency',r.agency,'使用单位')}</label><label>承办部门${field('department',r.department||'','承办部门')}</label><label>经办人员${field('preparedBy',r.preparedBy||'','经办人员')}</label><label>报告类型${select('reportType',r.reportType||'业务工作报告','报告类型',['业务工作报告','政策分析报告','企业规范报告','项目复盘报告'])}</label><label>报告标题${field('title',r.title,'报告标题')}</label><label>统计区域${field('region',r.region,'统计区域')}</label><label>报告周期${field('period',r.period,'报告周期')}</label><label>工作目的${field('purpose',r.purpose||'','工作目的')}</label></div><div class="template-config"><div class="section-heading"><h3>报告模板</h3><small>可先使用通用模板，也可上传单位自有模板作为编排依据</small></div><label>当前模板${select('template',r.template||'通用业务工作报告模板','当前模板',['通用业务工作报告模板','单位自定义模板'])}</label><label class="file-field">单位模板文件<input name="templateFile" aria-label="单位模板文件" type="file" accept=".doc,.docx,.pdf,.md,.html">${r.templateFile?`<small>已选择：${esc(r.templateFile)}</small>`:'<small>支持 Word、PDF、Markdown 或 HTML 模板；第一版保存文件名，后续可接入模板解析。</small>'}</label></div><h3>本次将纳入报告的有效工作成果</h3><div class="source-checks"><span>${svg('check',16)} 原料批次：${esc(s.batch)}</span><span>${svg('check',16)} 加工记录：${esc(s.processing)}</span><span>${svg('check',16)} 供需需求：${esc(s.demand)}</span><span>${svg('check',16)} 匹配结果：${esc(s.matches)}</span><span>${svg('check',16)} 数据质量：${esc(s.dataScore)}</span><span>${svg('check',16)} 图表与区域流向</span></div><div class="evidence-note">报告会把事实、分析、风险待办和行动建议分层呈现；缺少来源或未完成核验的数据会明确标注，不会被写成确定结论。</div></form><aside id="report-preview" class="panel report-preview">${reportPreview()}</aside></div>`;
    const archive=`<div class="report-grid"><article class="panel report-item"><div>${svg('file',28)}<h2>${esc(r.title)}</h2><p>${esc(r.agency)} · ${esc(r.period)}</p></div>${pill(r.generated?'已生成初稿':'待生成',r.generated?'black':'')}${button(r.generated?'查看报告':'继续配置','view-report')}</article><article class="panel report-item"><div>${svg('clipboard',28)}<h2>单位自定义模板</h2><p>${r.templateFile?esc(r.templateFile):'尚未上传单位模板'}</p></div>${pill(r.templateFile?'已选择':'可配置')}${button('配置模板','use-enterprise-report')}</article></div>`;
    const templateLibrary=`<div class="report-grid"><article class="panel report-item template-item"><div>${svg('file',28)}<h2>通用业务工作报告模板</h2><p>适合农业农村局、产业协会和园区运营部门；包含工作概况、数据底稿、业务结果、风险待办和行动计划。</p></div>${pill('系统模板','black')}${button('使用通用模板','view-report')}</article><article class="panel report-item template-item"><div>${svg('clipboard',28)}<h2>单位自定义模板</h2><p>由单位提供 Word、PDF、Markdown 或 HTML 模板，后续可按章节映射 Agent 的工作结果。</p></div>${pill(r.templateFile?'已上传':'待上传')}${button('上传并配置','use-enterprise-report')}</article></div>`;
    return header('REPORTS','报告中心','将用户完成的 Agent 工作汇总为可复核、可流转、可导出的正式业务报告')+`<div class="toolbar">${tabs(['生成报告','报告记录','模板库'],tab)}<div class="actions">${button('导出业务报告','download-report',false,'download')}${button(r.generated?'重新生成初稿':'生成业务报告','generate-report',true,'file')}</div></div>`+(tab===0?editor:tab===1?archive:templateLibrary);
  }

  function visuals() {
    const bars=[['2022',86],['2023',101],['2024',110],['2025',122],['2026',131]];
    const trend=`<div class="visual-layout"><section class="panel chart-panel"><div class="section-heading"><h2>柑橘产量趋势</h2><small>示例数据 · 单位：万吨</small></div><div class="production-bars" role="img" aria-label="2022年至2026年柑橘示例产量柱状图">${bars.map(([year,value])=>`<div><b>${value}</b><i style="height:${value/1.5}px"></i><span>${year}</span></div>`).join('')}</div></section><section class="panel chart-panel"><div class="section-heading"><h2>区域供需流向</h2><small>跨区域商机示意</small></div><svg class="flow-chart" viewBox="0 0 560 260" role="img" aria-label="山东、江西和广西的柑橘原料流向重庆加工厂"><title>柑橘跨区域供需流向</title><path d="M115 55 C270 55 290 130 420 130"/><path d="M115 130 C270 130 290 130 420 130"/><path d="M115 205 C270 205 290 130 420 130"/><circle cx="92" cy="55" r="32"/><circle cx="92" cy="130" r="32"/><circle cx="92" cy="205" r="32"/><rect x="420" y="92" width="112" height="76" rx="8"/><text x="92" y="60">山东</text><text x="92" y="135">江西</text><text x="92" y="210">广西</text><text x="476" y="123">重庆加工</text><text x="476" y="145">需求 80—120t</text></svg></section></div>`;
    const types=`<section class="visual-types"><div class="section-heading"><h2>可生成的产业图片</h2><small>选择与报告目的匹配的图，不堆砌无关图表</small></div><div class="type-grid">${[['chart','产量与加工量柱形图','年度、地区、品种对比'],['map','区域供需流向图','原料从产区到加工地'],['factory','产业链流程图','种植、采收、加工、销售'],['shield','质量指标对比图','糖度、酸度、合格率'],['database','批次产地分布图','批次、产区与可追溯状态'],['clock','季节供应日历','上市期、采购期和产线档期']].map(([i,t,d])=>`<article class="panel type-card">${svg(i,25)}<div><h3>${t}</h3><p>${d}</p></div></article>`).join('')}</div></section>`;
    return header('VISUALS','产业可视化','把产量、加工、质量和区域供需关系变成可直接用于报告的图片')+`<div class="toolbar">${tabs(['综合看板','产量与加工','区域供需','图表库'],tab)}<div class="actions">${button('下载示例图表','download-chart',false,'download')}</div></div>`+stats([['chart','年度产量','131 万吨'],['factory','加工转化率','32%'],['map','重点产区','6'],['link','跨区域商机','12']])+trend+types+notice('数据说明','当前图表使用演示数据；接入真实统计或企业数据后，应显示数据来源、时间范围和口径。');
  }
  function render() {
    root._view=view;root._tab=tab;root._selected=selected;root._listMode=listMode;
    root.innerHTML=`<div class="page" data-view="${view}">${feedback?`<div class="feedback" role="status">${esc(feedback)}</div>`:''}${({data:dataCollection,production,supply,demand,match:matching,visuals,reports})[view]()}<p class="session-note">当前工作台数据仅保留在本次会话中；正式发布前请完成单位复核。</p></div><dialog aria-label="业务操作"></dialog>`;
  }
  function modal(title,body,submit='',kind='') {
    const dialog=root.querySelector('dialog');
    dialog.innerHTML=`<form id="dialog-form" data-kind="${kind}"><div class="dialog-head"><h2>${esc(title)}</h2><button type="button" data-action="close-dialog" aria-label="关闭">×</button></div>${body}<div class="actions">${button('关闭','close-dialog')}${submit?`<button type="submit" class="btn primary">${esc(submit)}</button>`:''}</div></form>`;
    dialog.showModal();
  }
  function changeLocalView(next) {
    // Use the existing Streamlit rail button; never navigate to a new session.
    persist();
    const nav=document.querySelector(`[class*="st-key-industry_nav_${next}"] button`);
    if(nav)nav.click();
  }
  function onClick(event) {
    const el=event.target.closest('button');if(!el||el.disabled)return;
    if(el.dataset.tab!==undefined){tab=Number(el.dataset.tab);feedback='';render();return;}
    if(el.dataset.candidate){selected=el.dataset.candidate;render();return;}
    if(el.dataset.pref){const p=el.dataset.pref;model.request.preferences=model.request.preferences.includes(p)?model.request.preferences.filter(x=>x!==p):[...model.request.preferences,p];render();persist();return;}
    const action=el.dataset.action;
    if(action==='close-dialog'){root.querySelector('dialog').close();return;}
    if(action==='list'||action==='cards'){listMode=action==='list';root._listMode=listMode;root.querySelector('#supply-results').innerHTML=supplyResults();root.querySelectorAll('.switcher .btn').forEach(b=>b.classList.toggle('primary',b.dataset.action===action));return;}
    if(action==='save-intake'){persist();flash('数据采集草稿已保存到本次会话。');return;}
    if(action==='clean-data'){model.intakeAudit=cleanIntake(model.intake);tab=1;persist();flash(model.intakeAudit.valid?'数据已完成标准化，可进入有效数据池。':'数据已清洗，缺失或异常项已进入待补与复核队列。');return;}
    if(action==='download-data'){
      const a=cleanIntake(model.intake),rows=Object.entries(a.standardized).map(([k,v])=>`"${String(k).replaceAll('"','""')}","${String(v??'').replaceAll('"','""')}"`);
      downloadFile('citrus-clean-data.csv','field,value\r\n'+rows.join('\r\n'),'text/csv;charset=utf-8');return;
    }
    if(action?.startsWith('trade-')){const id=action.slice(6),candidate=tradeCandidates.find(c=>c.id===id);if(!candidate?.score)return;model.pendingTrade=id;modal('申请商业对接',`<p>${esc(candidate.seller)} · ${esc(candidate.origin)} → 重庆</p><p style="margin-top:12px">对接申请仅保存为会话草稿。提交前还需确认报价、运费、到厂验收和合同条款。</p>`,'保存对接申请','trade');return;}
    if(action==='generate-report'){model.report.generated=true;model.report.generatedAt=new Date().toLocaleString('zh-CN');persist();flash('业务报告初稿已生成，可在右侧预览并导出。');return;}
    if(action==='download-report'){if(!model.report.generated){flash('请先生成业务报告初稿，再执行导出。');return;}const fileName=(model.report.title||'柑橘产业业务工作报告').replace(/[\\/:*?"<>|]/g,'_');downloadFile(`${fileName}.html`,buildReportDocument(model.report,reportWorkSummary()),'text/html;charset=utf-8');return;}
    if(action==='download-chart'){downloadFile('柑橘产量示例数据.csv','年份,产量（万吨）\r\n2022,86\r\n2023,101\r\n2024,110\r\n2025,122\r\n2026,131','text/csv;charset=utf-8');return;}
    if(action==='view-report'){tab=0;render();return;}
    if(action==='use-enterprise-report'){model.report.title='柑橘加工企业原料验收规范';model.report.agency='本单位';model.report.reportType='企业规范报告';model.report.template='单位自定义模板';model.report.generated=false;tab=0;persist();render();return;}
    if(action==='save-demand'){persist();flash('需求草稿已保存到本次会话，可继续修改或查看匹配。');return;}
    if(action==='publish-demand') {
      const r=model.request;
      if(!r.name.trim()||!r.destination.trim()||!quantityRange(r.quantity)||!r.brix.trim()||!Number.isFinite(Number(r.brix))||Number(r.brix)<0||Number(r.brix)>40||!r.delivery){flash('请补齐需求名称、交货地点、有效的数量范围、糖度和到厂日期。');return;}
      if(r.report&&!r.checklist){flash('发布前请先上传企业验收清单。演示版仅保存文件名，不上传原件。');return;}
      r.published=true;persist();flash('需求已在本次会话模拟发布；未公开到真实供需市场。');return;
    }
    if(action==='edit-demand'){if(view==='demand'){tab=1;render();}else changeLocalView('demand');return;}
    if(action==='show-matches'||action?.startsWith('buyers-')){model.matchOpenTab=0;changeLocalView('match');return;}
    if(action==='rematch'){selected=candidates.find(c=>evaluateCandidate(c,model.request).fit)?.id||'A';flash('已按当前需求重新核对三个演示候选批次。');return;}
    if(action==='connect') {
      const c=candidates.find(c=>c.id===selected);if(!evaluateCandidate(c,model.request).fit)return;
      modal('申请对接',`<p>供应主体 ${c.id} · 批次 ${c.batch}</p><p style="margin-top:12px">这将保存本次会话的对接申请草稿。不会向真实企业发送消息，也不会开放联系人与检测原件。</p>`,'生成申请草稿','connection');return;
    }
    if(action==='use-template'){modal('使用历史模板','<p>使用示例模板会替换当前采购草稿，是否继续？</p>','使用模板','template');return;}
    if(action==='equipment'){modal('设备与档期',equipment(model.equipment||[],false)+`<p>设备和档期为演示记录，实际可用时间需人工确认。</p>`);return;}
    if(action==='sop'){modal('参数版本 · 企业 SOP v2.1','<p>当前版本：v2.1 · 企业私有 · 待质控复核</p><p style="margin-top:14px">这里不预置真实生产参数。请以企业已批准的 SOP 和质控放行为准。</p>');return;}
    if(action==='register-equipment'){modal('登记设备',`<label>设备名称${field('equipment','','设备名称','text','required')}</label><label>负责人${field('owner','','设备负责人','text','required')}</label><p>仅保存为本次会话的设备登记草稿。</p>`,'保存设备草稿','equipment');return;}
    if(action==='new-production'){modal('新建加工批次',`<label>加工批次${field('batch','','加工批次','text','required placeholder="P-0904-01"')}</label><label>原料与投入${field('material','','原料与投入','text','required placeholder="沃柑 · 20.0 t"')}</label><label>当前工序${select('line','清洗分选','当前工序',['清洗分选','榨汁','干燥'])}</label>`,'保存生产记录','production');return;}
    if(action==='new-supply'||action==='import-supply'){modal(action==='new-supply'?'发布供应':'导入供应批次',`<label>供应名称${field('name','','供应名称','text','required')}</label><label>批次编号${field('batch','','供应批次编号','text','required')}</label><label>产地${field('origin','','供应产地','text','required')}</label><p>先创建会话草稿，再补齐指标与证据。不自动公开到市场。</p>`,'保存供应草稿','supply');return;}
    if(action==='complete-supply'){modal('补全柑橘果皮资料','<p>该演示批次缺少水分指标、供货日期与检测资料，当前不可发布。</p><p style="margin-top:12px">资料审核与真实文件存储尚未接入，不能仅凭填写数值把批次标成已核验。</p>');return;}
    if(action?.startsWith('manage-')){const s=supplies.find(s=>action===`manage-${s.id}`);if(s)modal('管理供应批次',`<p>${esc(s.name)} · ${s.id}</p><p style="margin-top:12px">${esc(s.origin)} · ${esc(s.quantity)} · ${esc(s.brix)}</p><p style="margin-top:12px">${esc(s.source)}。原件与联系方式在双方授权后开放。</p>`);}
  }
  function onInput(event) {
    const el=event.target;
    if(el.name==='supply-search'){root.querySelector('#supply-results').innerHTML=supplyResults();return;}
    if(el.closest('#intake-form')&&el.name){model.intake[el.name]=el.value;model.intakeAudit=null;const progress=root.querySelector('#intake-progress');if(progress)progress.innerHTML=intakeProgress();return;}
    if(el.closest('#report-form')&&el.name){if(el.type==='file')return;model.report[el.name]=el.value;model.report.generated=false;const preview=root.querySelector('#report-preview');if(preview)preview.innerHTML=reportPreview();return;}
    if(!el.closest('#demand-form')||!el.name||el.type==='file')return;
    model.request[el.name]=el.type==='checkbox'?el.checked:el.value;
    model.request.published=false;
    root.querySelector('#preview').innerHTML=preview();
  }
  function onChange(event) {
    const el=event.target;
    if(['supply-type','supply-status'].includes(el.name)){root.querySelector('#supply-results').innerHTML=supplyResults();return;}
    if(el.closest('#intake-form')){onInput(event);persist();return;}
    if(el.closest('#report-form')){if(el.name==='templateFile'){model.report.templateFile=el.files?.[0]?.name||'';model.report.generated=false;}else onInput(event);persist();const preview=root.querySelector('#report-preview');if(preview)preview.innerHTML=reportPreview();return;}
    if(el.closest('#demand-form')){
      if(el.name==='checklist'){model.request.published=false;model.request.checklist=el.files[0]?.name||'';root.querySelector('#preview').innerHTML=preview();}
      else onInput(event);
      persist();
    }
  }
  function onSubmit(event) {
    event.preventDefault();
    if(event.target.id!=='dialog-form')return;
    const values=Object.fromEntries(new FormData(event.target));
    const kind=event.target.dataset.kind;
    if(kind==='connection'&&!model.connections.includes(selected))model.connections.push(selected);
    if(kind==='trade'){
      const id=model.pendingTrade||'SD-01';
      if(!model.tradeConnections.includes(id))model.tradeConnections.push(id);
      delete model.pendingTrade;
    }
    if(kind==='production')model.production.push(values);
    if(kind==='supply')model.supplies.push(values);
    if(kind==='equipment'){model.equipment=model.equipment||[];model.equipment.push(values);}
    if(kind==='template'){model.request=structuredClone(defaultRequest);tab=1;}
    root.querySelector('dialog').close();persist();
    flash(kind==='connection'||kind==='trade'?'对接申请草稿已保存；未发送给真实企业。':kind==='template'?'已载入示例需求模板。':'记录已保存到本次会话。');
  }
  if(root._view!==view||!root.querySelector('.page'))render();
  return bindWorkspaceEvents(root,{click:onClick,input:onInput,change:onChange,submit:onSubmit});
}
