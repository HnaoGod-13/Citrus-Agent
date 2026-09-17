// Schema-driven intake. Concatenated before workspace.js by the Python host.
export const intakeEscape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const intakeNewDocument = side => ({schemaVersion:1, side, fields:{}, rows:{}, declarations:{}, attachments:[]});

export function intakeAudit(document, schema) {
  const side = schema.sides[document.side], errors = [];
  let required = 0, completed = 0;
  const check = (spec, value, label, step) => {
    const present = spec.type === 'checkbox' ? value === true : String(value ?? '').trim() !== '';
    if (spec.required) {
      required++; if (present) completed++;
      else errors.push({step, message:`${label}：请填写${spec.label}`});
    }
    if (present && spec.type === 'number') {
      const num = Number(String(value).replaceAll(',', ''));
      if (!Number.isFinite(num) || num < (spec.min ?? -Infinity) || num > (spec.max ?? Infinity)) errors.push({step, message:`${label}：${spec.label}数值不在有效范围内`});
    }
  };
  side.steps.forEach((part, step) => part.groups.forEach(g => {
    if (!g.repeat) { g.fields.forEach(f => check(f, document.fields[`${g.key}.${f.key}`], g.title, step)); return; }
    const rows = document.rows[g.key] || [], declared = document.declarations[g.key];
    if (g.declaration) {
      required++; if (['已使用','未使用'].includes(declared)) completed++;
      else errors.push({step,message:`${g.title}：请选择已使用或未使用`});
      if (declared === '未使用' && rows.some(r => g.fields.some(f => String(r[f.key] ?? '').trim()))) errors.push({step,message:`${g.title}：未使用声明与明细冲突`});
    }
    if ((g.required || declared === '已使用') && !rows.length) { required++; errors.push({step,message:`${g.title}：至少添加一条完整记录`}); }
    rows.forEach((r,i) => g.fields.forEach(f => check(f,r[f.key],`${g.title}第${i+1}条`,step)));
  }));
  return {errors, required, completed, score:Math.round(100 * completed / Math.max(required,1)), valid:!errors.length};
}

export function intakeLinkMaterial(source) {
  const f = source.fields;
  return {batch:f['harvest.batch'] || '', name:f['base.variety'] || '', origin:f['base.origin'] || '',
    supplier:f['profile.organization'] || '', address:f['profile.address'] || '', phone:f['profile.phone'] || '',
    harvestDate:f['harvest.date'] || '', specification:f['quality.grade'] || '',
    brix:f['quality.brix'] || '', acidity:f['quality.acidity'] || ''};
}

export function intakePrintable(document, schema) {
  const e = intakeEscape, side = schema.sides[document.side];
  const table = (fields, values, prefix='') => `<table>${fields.map(f=>`<tr><th>${e(f.label)}${f.unit?` (${e(f.unit)})`:''}</th><td>${e(values[prefix+f.key] === true ? '是' : values[prefix+f.key] === false ? '否' : values[prefix+f.key] || '未填写')}</td></tr>`).join('')}</table>`;
  return `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>${e(side.title)}</title><style>body{font:15px/1.7 sans-serif;max-width:900px;margin:40px auto;padding:20px;color:#222}h1{text-align:center}h2{border-bottom:1px solid #bbb;padding:12px 0}table{border-collapse:collapse;width:100%;margin:16px 0;table-layout:fixed}td,th{border:1px solid #ccc;padding:8px 12px;white-space:pre-wrap;overflow-wrap:anywhere;text-align:left}th{width:40%;background:#f5f5f5}p,small{color:#666}@media print{h2,h3{break-after:avoid}tr{break-inside:avoid}}</style><body><h1>${e(side.title)}</h1><p>记录版本：${e(document.revision || '未保存')} · ${e(document.updated_at || '当前填写内容')} · 状态：${document.status === 'submitted' ? '已提交，待复核' : '草稿'}</p>${side.steps.map(step=>`<h2>${e(step.title)}</h2>${step.groups.map(g=>`<h3>${e(g.title)}</h3>${g.repeat ? `<p>${e(document.declarations[g.key] || '')}</p>${(document.rows[g.key]||[]).map((r,i)=>`<p>第 ${i+1} 条</p>${table(g.fields,r)}`).join('') || '<p>未登记</p>'}` : table(g.fields,document.fields,`${g.key}.`)}`).join('')}`).join('')}<h2>附件清单</h2>${document.attachments.map(a=>`<p>${e(a.name)} · ${Math.round(a.size/1024)} KB</p>`).join('') || '<p>未附文件</p>'}<small>本表保留用户填报内容，检测和企业放行结论须按原始资料复核。附件原件随 JSON 备份保存。</small></body></html>`;
}

export function createIntakeController({root, model, data, setStateValue, render, flash, download, persist, changeView}) {
  const schema = data.intakeSchema;
  if (!schema) return null;
  const e = intakeEscape;
  const state = model.collection ||= {side:'', panel:'form', steps:{supplier:0,processor:0}, documents:{}, dirty:{}};
  state.analysis ||= model.analysis || null;
  state.taskContext ||= model.taskContext || null;
  const current = () => state.documents[state.side] ||= intakeNewDocument(state.side);
  const docs = data.intakeRecords || [];
  const result = data.intakeResult;
  let refreshed = false;
  if (result?.requestId && state.handledRequestId !== result.requestId) {
    state.handledRequestId = result.requestId;
    root._intakeAck = result.requestId;
    state.pending = false;
    state.message = result.message;
    state.errors = result.audit?.errors || [];
    if (result.document && result.ok) {
      if (result.operation === 'link') {
        const processor = state.documents.processor ||= intakeNewDocument('processor');
        (processor.rows.materials ||= []).push(intakeLinkMaterial(result.document));
        state.dirty.processor = true;
      } else {
        state.side = result.document.side;
        state.documents[state.side] = result.document;
        state.dirty[state.side] = false;
        delete state.undo;
        if (result.operation === 'load') {state.panel='form'; state.steps[state.side]=0;}
      }
      if (result.analysis) {
        state.analysis = structuredClone(result.analysis);
        model.analysis = structuredClone(result.analysis);
      } else if (result.operation !== 'link') {
        state.analysis = null;
        model.analysis = null;
      }
      if (result.operation !== 'link') {
        state.taskContext = structuredClone(result.taskContext || result.analysis?.task_context || {});
        model.taskContext = structuredClone(state.taskContext);
      }
    }
    if (!result.ok && state.errors.length) state.panel='check';
    refreshed = true;
  }
  const request = (operation, payload={}) => {
    if (state.pending) return;
    state.pending = true; state.message='正在处理采集记录…'; render();
    setStateValue('intake_action', {requestId:crypto.randomUUID(), operation, ...payload});
  };
  const button = (label, action, primary=false, extra='') => `<button type="button" class="btn${primary?' primary':''}" data-action="ic-${action}" ${extra}>${e(label)}</button>`;
  const touch = () => {state.dirty[state.side]=true; state.errors=[]; state.message=''; current().status='draft';};
  function input(spec, value, group, row) {
    const path = `${group}.${spec.key}`, id=`ic-${path}-${row ?? 'field'}`;
    const attrs = `id="${id}" name="${id}" ${state.pending?'disabled':''} data-intake-field="${path}"${row !== undefined ? ` data-intake-row="${row}"` : ''} aria-label="${e(spec.label)}${row !== undefined ? `（第${row+1}条）` : ''}"`;
    const display = value ?? '';
    let control;
    if (spec.type === 'checkbox') return `<label class="ic-check" for="${id}"><input ${attrs} type="checkbox" ${value===true?'checked':''}><span>${e(spec.label)}${spec.required?' <b>提交必选</b>':''}</span></label>`;
    if (spec.type === 'select') control=`<select ${attrs}><option value="">请选择</option>${spec.options.map(o=>`<option ${o===display?'selected':''}>${e(o)}</option>`).join('')}</select>`;
    else if (spec.type === 'textarea') control=`<textarea ${attrs} rows="3" maxlength="4000">${e(display)}</textarea>`;
    else control=`<input ${attrs} type="${spec.type}" value="${e(display)}" ${spec.type==='number'?`step="any" ${spec.min!==undefined?`min="${spec.min}"`:''} ${spec.max!==undefined?`max="${spec.max}"`:''}`:'maxlength="4000"'}>`;
    return `<label class="data-field${spec.type==='textarea'?' ic-wide':''}" for="${id}"><span>${e(spec.label)} ${spec.required?'<b>必填</b>':'<em>选填</em>'}</span><div class="ic-control">${control}${spec.unit?`<small>${e(spec.unit)}</small>`:''}</div></label>`;
  }
  function groupMarkup(g) {
    const document=current(), rows=document.rows[g.key] || [];
    const head=`<div class="section-heading"><h2>${e(g.title)}</h2>${g.repeat?`<small>${rows.length} 条记录</small>`:''}</div>${g.hint?`<p class="ic-hint">${e(g.hint)}</p>`:''}`;
    if (!g.repeat) return `<section class="panel intake-section">${head}<div class="data-grid">${g.fields.map(f=>input(f,document.fields[`${g.key}.${f.key}`],g.key)).join('')}</div></section>`;
    const declaration=g.declaration?`<label class="ic-declaration">本周期使用情况<select data-intake-declaration="${g.key}" aria-label="${e(g.title)}使用情况"><option value="">请选择</option>${['已使用','未使用'].map(o=>`<option ${document.declarations[g.key]===o?'selected':''}>${o}</option>`).join('')}</select></label>`:'';
    const link=g.key==='materials'?`<div class="ic-link"><label>关联已保存的供应批次<select aria-label="关联供应批次" id="ic-source-batch"><option value="">请选择本次访问保存的供应记录</option>${docs.filter(d=>d.side==='supplier').map(d=>`<option value="${e(d.id)}">${e(d.title)}</option>`).join('')}</select></label>${button('带入批次资料','link')}</div><p class="ic-hint">带入产地、品种及批次来源后，仍需填写到货数量与实际验收结果。</p>`:'';
    return `<section class="panel intake-section">${head}${declaration}${link}${g.key==='steps'?`<div class="ic-template">${button('按产品添加工序名称','process-template')}<small>仅添加工序名称，实测参数由企业填写。</small></div>`:''}${rows.map((r,i)=>`<details class="ic-row" open><summary><strong>记录 ${i+1}${r.name?` · ${e(r.name)}`:''}</strong></summary><div class="data-grid">${g.fields.map(f=>input(f,r[f.key],g.key,i)).join('')}</div><div class="ic-row-actions">${button('移除此条',`remove-${g.key}-${i}`)}</div></details>`).join('') || '<p class="ic-empty-row">暂无明细，可逐条添加记录。</p>'}${button('＋ 新增一条',`add-${g.key}`)}</section>`;
  }
  function attachments() {
    const document=current();
    return `<section class="panel intake-section"><div class="section-heading"><h2>证据附件</h2><small>检测报告、标签、采购凭证及生产记录</small></div><label class="ic-upload">选择文件<input type="file" data-intake-upload="evidence" aria-label="上传证据附件" accept=".pdf,.png,.jpg,.jpeg" multiple></label><p class="ic-hint">PDF、PNG、JPEG；每个3MB以内，最多8个，合计9MB。附件内容随采集记录一并保存。</p><div class="ic-attachments">${document.attachments.map((a,i)=>`<div><span>${e(a.name)} <small>${Math.round(a.size/1024)} KB</small></span>${button('下载',`attachment-${i}`)}${button('移除',`file-remove-${i}`)}</div>`).join('')}</div></section>`;
  }
  function progress() {
    const audit=intakeAudit(current(),schema), document=current();
    const rows=Object.values(document.rows).reduce((sum,r)=>sum+r.length,0);
    const raw=Number(document.fields['output.rawMass']), product=Number(document.fields['output.productMass']);
    return `<div class="collection-score"><span>必填内容完整度</span><strong>${audit.score}%</strong><div class="meter"><i style="width:${audit.score}%"></i></div><p>${audit.completed} / ${audit.required} 项已填写</p></div><dl class="ic-summary"><div><dt>明细记录</dt><dd>${rows} 条</dd></div><div><dt>证据附件</dt><dd>${document.attachments.length} 个</dd></div><div><dt>记录状态</dt><dd>${state.dirty[state.side]?'有未保存修改':document.status==='submitted'?'已提交 · 待复核':document.id?'已保存草稿':'未保存'}</dd></div>${document.fields['output.productMass']!==undefined && String(document.fields['output.productMass']).trim() && raw>0 && Number.isFinite(product)?`<div><dt>质量口径得率</dt><dd>${(product/raw*100).toFixed(2)}%</dd></div>`:''}</dl><p class="ic-hint">完整度仅衡量填写情况；检测、工艺适用性及质量结论由原始资料和企业复核确认。</p>`;
  }
  function autoDecisionPanel() {
    const analysis=state.analysis || model.analysis;if (!analysis) return '';
    const cleaning=analysis.cleaning||{}, route=analysis.recommended_route||{}, context=analysis.task_context||state.taskContext||{};
    const routeRows=(analysis.routes||[]).slice(0,3).map(r=>`<div class="ic-route-row"><span>${e(r.tier||'候选')} · ${e(r.label||r.route)}</span><strong>${e(r.score)}/100</strong></div>`).join('');
    return `<section class="panel ic-auto-panel"><div class="section-heading"><h2>自动决策与工艺</h2><small>任务 ${e(context.task_id||'待生成')}</small></div><div class="ic-auto-score"><strong>${e(cleaning.weighted_score??0)}</strong><span>加权数据质量分</span><em class="${cleaning.decision_ready?'ok':'warn'}">${cleaning.decision_ready?'可进入路线评审':'待补资料 / 复核'}</em></div><p class="ic-hint">数据已按字段重要性清洗并自动生成路线排序；右侧助手只解释当前任务。</p><div class="ic-route-list">${routeRows||'<p class="ic-empty-row">填写并保存批次信息后自动生成路线。</p>'}</div><div class="ic-task-meta"><span>task_id：${e(context.task_id||'—')}</span><span>record_id：${e(context.record_id||'—')}</span></div></section>`;
  }
  function recordList() {
    return `<section class="panel intake-section"><div class="section-heading"><h2>已保存的采集记录</h2><small>当前访问身份下的记录，可继续填写或关联批次</small></div>${docs.length?`<div class="table-wrap"><table><thead><tr><th>主体 / 批次</th><th>类型</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${docs.map(d=>`<tr><td>${e(d.title)}</td><td>${d.side==='supplier'?'供应端':'生产端'}</td><td>${d.status==='submitted'?'待复核':'草稿'}</td><td>${e(new Date(d.updated_at).toLocaleString('zh-CN'))}</td><td>${button('打开',`load-${d.id}`)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="empty">保存第一份采集表后，记录会显示在这里。</p>'}</section>`;
  }
  function standards() {
    return `<div class="ic-guidance"><h2>采集依据与字段说明</h2><p>“必填”指本次采集提交的业务要求。具体法定义务取决于主体类型、产品类别与实际工艺，不将所有字段视为统一法律强制项。</p><small>依据复核日期：${e(schema.reviewed)}</small></div><div class="standard-list">${schema.standards.map(s=>`<a class="panel standard-card" href="${e(s.url)}" target="_blank" rel="noopener noreferrer"><b>${e(s.title)}</b><span>${e(s.scope)} · ${e(s.version)}</span><span>${e(s.note)}</span><em>查看官方依据 →</em></a>`).join('')}</div>`;
  }
  function checkPanel() {
    const a=intakeAudit(current(),schema), errors=state.errors?.length?state.errors:a.errors;
    return `<section class="panel intake-section"><div class="section-heading"><h2>填写检查</h2><small>${errors.length} 项待处理</small></div><p class="ic-hint">保存时会统一空格、字符格式及有效数字；原始检测结果表达予以保留。不会因字段填满而自动标记“合格”。</p>${errors.length?`<ul class="ic-error-list">${errors.map(item=>`<li><span>${e(item.message)}</span>${button('去完善',`step-${item.step}`)}</li>`).join('')}</ul>`:'<p class="ic-ready">本地填写检查通过，提交时将再次校验日期、批次关联和检测结论。</p>'}${button('提交采集记录','submit',true)}</section>`;
  }
  function markup() {
    const side=state.side && schema.sides[state.side], step=state.steps[state.side] || 0;
    const headline=`<header class="page-head"><div class="eyebrow">CITRUS AI · DATA INTAKE</div><h1>${side?e(side.title):'产业数据采集'}</h1></header>`;
    const nav=`<div class="toolbar ic-toolbar"><div class="tabs">${button('采集入口','home')}${button('采集记录','records')}${button('标准依据','standards')}</div>${side?`<div class="actions">${button('导出采集表','print')}${button(state.pending?'保存中…':'保存草稿','save',true,state.pending?'disabled':'')}</div>`:''}</div>`;
    const status=state.message?`<div class="feedback" role="status">${e(state.message)}</div>`:'';
    if (state.panel==='records') return headline+nav+status+recordList();
    if (state.panel==='standards') return headline+nav+status+standards();
    if (!side) return headline+nav+status+`<div class="ic-entry-grid">${Object.entries(schema.sides).map(([key,s])=>`<button type="button" class="panel ic-entry ic-entry-${key}" data-action="ic-side-${key}"><span class="ic-entry-symbol">${key==='supplier'?'01':'02'}</span><h2>${e(s.title)}</h2><p>${e(s.subtitle)}</p><div class="ic-entry-tags">${(key==='supplier'?['种植基地','农业投入品','原料品质','采收供应']:['批次接收','实际加工参数','成品质检','产出追溯']).map(t=>`<span>${t}</span>`).join('')}</div><b>进入采集 <span aria-hidden="true">→</span></b></button>`).join('')}</div>`;
    const form=state.panel==='check'?checkPanel():`<form id="dual-intake-form"><div class="ic-step-heading"><div><span>STEP ${String(step+1).padStart(2,'0')} / ${side.steps.length}</span><h2>${e(side.steps[step].title)}</h2></div>${button(state.side==='supplier'?'切换到生产端':'切换到供应端',`side-${state.side==='supplier'?'processor':'supplier'}`)}</div>${side.steps[step].groups.map(groupMarkup).join('')}${step===side.steps.length-1?attachments():''}<div class="ic-step-actions">${button('上一步',`step-${Math.max(0,step-1)}`,false,step===0?'disabled':'')}${button(step===side.steps.length-1?'检查并提交':'下一步',step===side.steps.length-1?'check':`step-${step+1}`,true)}</div></form>`;
    return headline+nav+status+`<nav class="ic-steps" aria-label="采集环节">${side.steps.map((s,i)=>`<button type="button" data-action="ic-step-${i}" class="${step===i&&state.panel==='form'?'active':''}" ${step===i&&state.panel==='form'?'aria-current="step"':''}><span>${String(i+1).padStart(2,'0')}</span>${e(s.title)}</button>`).join('')}</nav><div class="ic-intake-layout"><div>${form}</div><aside class="panel collection-summary"><h2>采集状态</h2><div id="ic-progress">${progress()}</div>${autoDecisionPanel()}<div class="ic-side-actions">${button('检查完整度','check')}${button('导出完整备份','backup')}${button('用于业务报告','report')}${button('新建另一批次','new')}</div></aside></div>`;
  }
  function handleClick(el) {
    const action=el.dataset.action;
    if (!action?.startsWith('ic-')) return false;
    const a=action.slice(3);
    if (state.pending) {state.message='上一项保存或读取仍在处理中，请稍候。';render();return true;}
    if (a==='home') {state.side='';state.panel='form';}
    else if (a==='records' || a==='standards') state.panel=a;
    else if (a.startsWith('side-')) {state.side=a.slice(5);state.panel='form';current();}
    else if (a.startsWith('step-')) {state.steps[state.side]=Number(a.slice(5));state.panel='form';}
    else if (a==='check') {state.errors=[];state.panel='check';}
    else if (a==='save' || a==='submit') {request(a,{document:structuredClone(current())});return true;}
    else if (a.startsWith('load-')) {
      if (state.side && state.dirty[state.side]) {state.message='当前有未保存修改，请先保存草稿后再打开另一条记录。';}
      else {request('load',{id:a.slice(5)});return true;}
    }
    else if (a==='new') {
      if (state.dirty[state.side]) state.message='请先保存当前草稿，再新建另一批次。';
      else {state.documents[state.side]=intakeNewDocument(state.side);state.steps[state.side]=0;state.panel='form';state.message='已新建空白采集表。';}
    }
    else if (a==='link') {
      const id=root.querySelector('#ic-source-batch')?.value;
      if (id) {request('link',{id});return true;}
      state.message='请先选择已保存的供应记录。';
    }
    else if (a.startsWith('add-')) {
      const key=a.slice(4), rows=current().rows[key] ||= [];
      if (rows.length>=60) state.message='单项最多60条明细，请分批记录。';
      else {rows.push({});touch();}
    }
    else if (a.startsWith('remove-')) {
      const [,key,index]=a.match(/^remove-(.+)-(\d+)$/) || [];
      if (key) {state.undo={key,index:Number(index),row:current().rows[key].splice(Number(index),1)[0],side:state.side};touch();state.message='已移除此条，保存前可撤销。';}
    }
    else if (a==='undo' && state.undo?.side===state.side) {const {key,index,row}=state.undo;current().rows[key].splice(index,0,row);delete state.undo;touch();}
    else if (a.startsWith('file-remove-')) {current().attachments.splice(Number(a.slice(12)),1);touch();}
    else if (a.startsWith('attachment-')) {
      const file=current().attachments[Number(a.slice(11))];
      if (file) download(file.name,Uint8Array.from(atob(file.content),c=>c.charCodeAt(0)),'application/octet-stream');
    }
    else if (a==='print') download(`${current().fields['harvest.batch']||current().fields['product.batch']||'产业'}-采集表.html`.replace(/[\\/:*?"<>|]/g,'_'),intakePrintable(current(),schema),'text/html;charset=utf-8');
    else if (a==='backup') download('产业采集备份.json',JSON.stringify({exportVersion:1,document:current()},null,2),'application/json;charset=utf-8');
    else if (a==='report') {
      if (!current().fields['consent.reportUse']) state.message='请在“证据与提交”中选择允许本记录用于工作报告。';
      else {model.activeIntakeReport=structuredClone(current());persist();changeView('reports');return true;}
    }
    else if (a==='process-template') {
      const names=({'NFC 果汁':['接收分选','清洗','榨汁','过滤','杀菌','灌装','冷却储存'],'浓缩汁':['接收分选','清洗','榨汁','过滤','浓缩','杀菌','包装'],'果干 / 果脯':['接收分选','清洗切分','预处理','干燥','分选包装'],'果胶':['原料预处理','提取','固液分离','浓缩','沉淀','干燥'],'精油':['原料预处理','提取','分离','精制','包装'],'果皮 / 陈皮制品':['原料验收','清洗剥皮','干燥','储存陈化','包装']})[current().fields['product.category']] || ['原料验收','加工','成品检验','包装入库'];
      const rows=current().rows.steps ||= [], existing=new Set(rows.map(r=>r.name));
      names.filter(name=>!existing.has(name)).slice(0,60-rows.length).forEach(name=>rows.push({name}));touch();
    }
    render();persist();return true;
  }
  function handleInput(el) {
    if (!el.dataset.intakeField) return false;
    const path=el.dataset.intakeField, [group,key]=path.split('.'), value=el.type==='checkbox'?el.checked:el.value;
    if (el.dataset.intakeRow!==undefined) current().rows[group][Number(el.dataset.intakeRow)][key]=value;
    else current().fields[path]=value;
    touch();const target=root.querySelector('#ic-progress');if(target)target.innerHTML=progress();return true;
  }
  async function upload(el) {
    try {
      if (el.dataset.intakeUpload==='backup') {
        const file=el.files[0];if(!file)return;
        if(file.size>14*1024*1024)throw Error('备份文件不能超过14MB。');
        const parsed=JSON.parse(await file.text()), doc=parsed.document;
        if(parsed.exportVersion!==1 || !schema.sides[doc?.side] || !doc.fields || typeof doc.fields!=='object' || !doc.rows || !Array.isArray(doc.attachments))throw Error('不是受支持的采集备份文件。');
        if(state.dirty[doc.side])throw Error('请先保存该端当前草稿，再导入备份。');
        // Server validates structure and file signatures. Import is a new private draft.
        const {id,revision,status,updated_at,...copy}=doc;
        request('save',{document:copy});return;
      }
      const target=current(), side=state.side, files=Array.from(el.files || []);
      if(target.attachments.length+files.length>8)throw Error('最多8个附件。');
      if(target.attachments.reduce((s,f)=>s+f.size,0)+files.reduce((s,f)=>s+f.size,0)>9*1024*1024)throw Error('附件合计不能超过9MB。');
      if(files.some(f=>f.size>3*1024*1024 || !/\.(pdf|png|jpe?g)$/i.test(f.name)))throw Error('请上传3MB以内的 PDF、PNG 或 JPEG 文件。');
      const additions=[];
      for(const file of files) {
        const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('文件读取失败'));reader.readAsDataURL(file);});
        additions.push({name:file.name,size:file.size,content});
      }
      target.attachments.push(...additions);state.dirty[side]=true;target.status='draft';state.message='附件已加入草稿，点击保存后提交文件内容。';render();persist();
    } catch(error) {state.message=error.message || '附件处理失败';render();}
  }
  function handleChange(el) {
    if(el.dataset.intakeUpload) {upload(el);return true;}
    if(el.dataset.intakeDeclaration) {current().declarations[el.dataset.intakeDeclaration]=el.value;touch();render();persist();return true;}
    if(handleInput(el)) {persist();return true;}
    return false;
  }
  const renderMarkup = () => markup() + (state.undo?.side===state.side?`<div class="ic-undo">${button('撤销移除明细','undo')}</div>`:'');
  return {render:renderMarkup,click:handleClick,input:handleInput,change:handleChange,refreshed};
}
