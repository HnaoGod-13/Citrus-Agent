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
const header=(code,title,desc)=>`<header class="page-head"><div class="eyebrow">CITRUS AI · ${code}</div><h1>${title}</h1><p class="subtitle">${desc}</p><span class="demo-badge">设计示例 · 演示数据</span></header>`;
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
  model.production=model.production||[];
  model.supplies=model.supplies||[];
  root._model=model;
  const view=data.view;
  let tab=root._view===view?(root._tab??(view==='production'||view==='demand'?1:0)):(view==='production'||view==='demand'?1:0);
  let selected=root._selected||'A';
  let listMode=root._listMode||false;
  let feedback='';
  const persist=()=>setStateValue('snapshot',structuredClone(model));
  const flash=message=>{feedback=message;render();};

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
    return header('MATCHING','匹配结果','先验证必须条件，再比较适配程度')+`<div class="match-actions">${button('调整需求','edit-demand')}${button('重新匹配','rematch')}</div><div class="panel query"><strong>采购需求： ${esc(r.name)}</strong>${[r.material,`${r.quantity} 吨`,`糖度 ≥ ${r.brix} °Brix`,`${r.delivery.slice(5).replace('-','.')} 前到厂`].map(v=>`<span class="tag">${esc(v)}</span>`).join('')}</div><div class="match-layout"><aside class="panel candidates"><h2>候选供应&nbsp; 3</h2>${list}</aside><section id="match-detail" class="panel match-detail">${matchDetails(candidates.find(c=>c.id===selected)||candidates[0])}</section></div>`+notice('匹配建议不等于检测放行；原件与联系人需双方授权后查看。','')+'<p class="footnote">规则版本 v1.0 · 数据快照 2026.09.03 10:30</p>';
  }
  function render() {
    root._view=view;root._tab=tab;root._selected=selected;root._listMode=listMode;
    root.innerHTML=`<div class="page" data-view="${view}">${feedback?`<div class="feedback" role="status">${esc(feedback)}</div>`:''}${({production,supply,demand,match:matching})[view]()}<p class="session-note">当前为演示工作台；保存、发布与对接只在本次会话模拟，不会发送给真实企业。</p></div><dialog aria-label="业务操作"></dialog>`;
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
    if(action==='save-demand'){persist();flash('需求草稿已保存到本次会话，可继续修改或查看匹配。');return;}
    if(action==='publish-demand') {
      const r=model.request;
      if(!r.name.trim()||!r.destination.trim()||!quantityRange(r.quantity)||!r.brix.trim()||!Number.isFinite(Number(r.brix))||Number(r.brix)<0||Number(r.brix)>40||!r.delivery){flash('请补齐需求名称、交货地点、有效的数量范围、糖度和到厂日期。');return;}
      if(r.report&&!r.checklist){flash('发布前请先上传企业验收清单。演示版仅保存文件名，不上传原件。');return;}
      r.published=true;persist();flash('需求已在本次会话模拟发布；未公开到真实供需市场。');return;
    }
    if(action==='edit-demand'){if(view==='demand'){tab=1;render();}else changeLocalView('demand');return;}
    if(action==='show-matches'||action?.startsWith('buyers-')){changeLocalView('match');return;}
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
    if(!el.closest('#demand-form')||!el.name||el.type==='file')return;
    model.request[el.name]=el.type==='checkbox'?el.checked:el.value;
    model.request.published=false;
    root.querySelector('#preview').innerHTML=preview();
  }
  function onChange(event) {
    const el=event.target;
    if(['supply-type','supply-status'].includes(el.name)){root.querySelector('#supply-results').innerHTML=supplyResults();return;}
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
    if(kind==='production')model.production.push(values);
    if(kind==='supply')model.supplies.push(values);
    if(kind==='equipment'){model.equipment=model.equipment||[];model.equipment.push(values);}
    if(kind==='template'){model.request=structuredClone(defaultRequest);tab=1;}
    root.querySelector('dialog').close();persist();
    flash(kind==='connection'?'对接申请草稿已保存；未发送给真实企业。':kind==='template'?'已载入示例需求模板。':'记录已保存到本次会话。');
  }
  if(root._view!==view||!root.querySelector('.page'))render();
  return bindWorkspaceEvents(root,{click:onClick,input:onInput,change:onChange,submit:onSubmit});
}
