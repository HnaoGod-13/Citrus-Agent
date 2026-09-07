// Evidence-labelled industry charts. Concatenated before workspace.js.
const VISUAL_PREVIEW = {
  source:'结构预览数据（非政府统计、非企业实报）', recordCount:48, supplierCount:31,
  processorCount:17, submittedCount:39, draftCount:9, supplyTons:84.6,
  inputTons:72.4, outputTons:28.9, averageBrix:12.3,
  timeline:[
    {label:'04月',supply:42,output:13},{label:'05月',supply:58,output:18},
    {label:'06月',supply:73,output:25},{label:'07月',supply:68,output:22},
    {label:'08月',supply:91,output:31},{label:'09月',supply:84.6,output:28.9},
  ],
  origins:[{label:'重庆奉节',value:31},{label:'江西赣州',value:26},{label:'广西武鸣',value:21},{label:'山东临沂',value:14}],
  quality:{qualified:82,pending:13,unqualified:5}, updatedAt:'仅用于预览页面结构',
};

const visualNumber = value => Number.isFinite(Number(value)) ? Number(value) : 0;
const compact = value => {
  const n=visualNumber(value);
  return Math.abs(n)>=1000 ? `${(n/1000).toFixed(1)}k` : Number.isInteger(n) ? String(n) : n.toFixed(1);
};

export function visualizationDataset(raw={}) {
  const real=visualNumber(raw.recordCount)>0;
  const source=real?raw:VISUAL_PREVIEW;
  const timeline=Array.isArray(source.timeline)?source.timeline.slice(-12).map(p=>({
    label:String(p.label||''), supply:Math.max(0,visualNumber(p.supply)), output:Math.max(0,visualNumber(p.output)),
  })):[];
  const origins=Array.isArray(source.origins)?source.origins.slice(0,8).map(p=>({
    label:String(p.label||''), value:Math.max(0,visualNumber(p.value)),
  })):[];
  const rawUpdated=String(source.updatedAt||'暂无更新时间');
  const parsedUpdated=new Date(rawUpdated);
  const updatedAt=real&&Number.isFinite(parsedUpdated.getTime())?parsedUpdated.toLocaleString('zh-CN',{hour12:false}):rawUpdated;
  return {
    mode:real?'recorded':'preview', source:String(source.source||VISUAL_PREVIEW.source),
    recordCount:visualNumber(source.recordCount), supplierCount:visualNumber(source.supplierCount),
    processorCount:visualNumber(source.processorCount), submittedCount:visualNumber(source.submittedCount),
    draftCount:visualNumber(source.draftCount), supplyTons:visualNumber(source.supplyTons),
    inputTons:visualNumber(source.inputTons), outputTons:visualNumber(source.outputTons),
    averageBrix:source.averageBrix===null||source.averageBrix===undefined?null:visualNumber(source.averageBrix),
    timeline, origins, quality:{qualified:visualNumber(source.quality?.qualified),pending:visualNumber(source.quality?.pending),unqualified:visualNumber(source.quality?.unqualified)},
    updatedAt,
  };
}

export function visualizationCsv(raw={}) {
  const d=visualizationDataset(raw), quote=value=>`"${String(value??'').replaceAll('"','""')}"`;
  const rows=[['数据属性',d.mode==='recorded'?'当前账号采集数据':'结构预览数据'],['数据来源',d.source],['更新时间',d.updatedAt],[],['月份','供应量（吨）','成品产量（吨）'],...d.timeline.map(p=>[p.label,p.supply,p.output]),[],['产地','批次数'],...d.origins.map(p=>[p.label,p.value])];
  return '\ufeff'+rows.map(row=>row.map(quote).join(',')).join('\r\n');
}

function volumeChart(points, esc) {
  if(!points.length)return '<div class="viz-empty"><b>暂无可绘制的批次量数据</b><span>完成供应端采收量或生产端成品产量填报后自动生成。</span></div>';
  const width=760,height=286,left=54,right=24,top=25,bottom=46,innerW=width-left-right,innerH=height-top-bottom;
  const max=Math.max(1,...points.flatMap(p=>[p.supply,p.output]));
  const x=i=>left+(points.length===1?innerW/2:i*innerW/(points.length-1));
  const y=value=>top+innerH-(value/max)*innerH;
  const line=key=>points.map((p,i)=>`${i?'L':'M'} ${x(i).toFixed(1)} ${y(p[key]).toFixed(1)}`).join(' ');
  const area=`${line('supply')} L ${x(points.length-1)} ${top+innerH} L ${x(0)} ${top+innerH} Z`;
  const grids=[0,.25,.5,.75,1].map(r=>`<g><line x1="${left}" x2="${width-right}" y1="${top+innerH*(1-r)}" y2="${top+innerH*(1-r)}"/><text x="${left-12}" y="${top+innerH*(1-r)+4}">${compact(max*r)}</text></g>`).join('');
  const labels=points.map((p,i)=>`<text class="axis-label" x="${x(i)}" y="${height-15}">${esc(p.label)}</text>`).join('');
  const dots=points.map((p,i)=>`<g class="viz-point"><circle cx="${x(i)}" cy="${y(p.supply)}" r="4"/><title>${esc(p.label)} 供应 ${compact(p.supply)} 吨</title></g><g class="viz-point output"><circle cx="${x(i)}" cy="${y(p.output)}" r="4"/><title>${esc(p.label)} 成品 ${compact(p.output)} 吨</title></g>`).join('');
  return `<svg class="viz-volume-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="供应量与成品产量趋势"><defs><linearGradient id="citrusArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#df810e" stop-opacity=".24"/><stop offset="1" stop-color="#df810e" stop-opacity="0"/></linearGradient></defs><g class="viz-grid">${grids}</g><path class="viz-area" d="${area}"/><path class="viz-line supply" d="${line('supply')}"/><path class="viz-line output" d="${line('output')}"/>${dots}${labels}</svg>`;
}

function qualityChart(quality) {
  const total=quality.qualified+quality.pending+quality.unqualified;
  if(!total)return '<div class="viz-empty compact"><b>暂无质检结论</b><span>检测项目或成品放行结论录入后展示。</span></div>';
  const pass=Math.round(quality.qualified/total*100),pending=Math.round(quality.pending/total*100);
  return `<div class="viz-quality"><div class="viz-donut" style="--pass:${pass*3.6}deg;--pending:${(pass+pending)*3.6}deg"><strong>${pass}%</strong><span>合格占比</span></div><dl><div><dt><i class="pass"></i>合格</dt><dd>${quality.qualified}</dd></div><div><dt><i class="pending"></i>待复核</dt><dd>${quality.pending}</dd></div><div><dt><i class="fail"></i>不合格</dt><dd>${quality.unqualified}</dd></div></dl></div>`;
}

function originChart(origins, esc) {
  if(!origins.length)return '<div class="viz-empty"><b>暂无产地分布</b><span>供应端填写产地并保存后自动汇总。</span></div>';
  const max=Math.max(1,...origins.map(p=>p.value));
  return `<div class="viz-origin-bars">${origins.map((p,i)=>`<div><span>${String(i+1).padStart(2,'0')}</span><b>${esc(p.label)}</b><i><em style="width:${Math.max(4,p.value/max*100)}%"></em></i><strong>${compact(p.value)} 批</strong></div>`).join('')}</div>`;
}

function routeChart(origins, destination, esc) {
  if(!origins.length)return '<div class="viz-empty"><b>暂无可核验的区域流向</b><span>需要供应端产地和当前采购目的地共同形成。</span></div>';
  const selected=origins.slice(0,4), max=Math.max(1,...selected.map(p=>p.value));
  const total=selected.reduce((sum,p)=>sum+p.value,0);
  return `<div class="viz-route-flow" role="img" aria-label="供应产地到采购目的地的流向示意"><div class="viz-route-list">${selected.map((p,i)=>`<article class="viz-route-origin"><span>${String(i+1).padStart(2,'0')}</span><div><b>${esc(p.label)}</b><i><em style="width:${Math.max(8,p.value/max*100)}%"></em></i></div><strong>${compact(p.value)}<small>批次</small></strong></article>`).join('')}</div><div class="viz-route-direction" aria-hidden="true"><span>候选汇入</span><i></i><b>→</b></div><div class="viz-route-target"><span>采购目的地</span><strong>${esc(destination||'待填写')}</strong><p>${selected.length} 个产地 · ${compact(total)} 批次</p></div></div>`;
}

export function renderIndustryVisuals({tab, raw, request, header, tabs, button, svg, esc}) {
  const d=visualizationDataset(raw), preview=d.mode==='preview';
  const source=`<section class="viz-source ${preview?'preview':''}"><div><span>${preview?'结构预览':'当前账号实报'}</span><h2>${esc(d.source)}</h2><p>${preview?'当前账号尚无已保存采集记录，下方数字仅用于展示图表结构，不代表任何地区真实产量。':'仅汇总当前账号已保存的供应端与生产端记录，不包含外部统计数据。'}</p></div><dl><div><dt>统计范围</dt><dd>${d.recordCount} 份记录</dd></div><div><dt>更新时间</dt><dd>${esc(d.updatedAt)}</dd></div></dl></section>`;
  const legend='<div class="viz-legend"><span><i class="supply"></i>供应端采收量</span><span><i class="output"></i>生产端成品产量</span><small>统一折算为吨</small></div>';
  const metrics=`<div class="viz-kpis"><article><span>采集记录</span><b>${compact(d.recordCount)}</b><small>供应 ${d.supplierCount} · 生产 ${d.processorCount}</small></article><article><span>供应端采收量</span><b>${compact(d.supplyTons)}<em>吨</em></b><small>按批次填报数量折算</small></article><article><span>生产端成品量</span><b>${compact(d.outputTons)}<em>吨</em></b><small>由成品净产量换算</small></article><article><span>平均糖度</span><b>${d.averageBrix===null?'—':compact(d.averageBrix)}<em>°Brix</em></b><small>仅统计已填糖度的供应批次</small></article></div>`;
  const volume=`<section class="panel viz-panel viz-wide"><div class="viz-panel-head"><div><span>VOLUME · TON</span><h2>供应与加工量趋势</h2><p>供应端采收量对比生产端成品净产量</p></div>${legend}</div>${volumeChart(d.timeline,esc)}</section>`;
  const quality=`<section class="panel viz-panel"><div class="viz-panel-head"><div><span>QUALITY · RESULT</span><h2>质检结论构成</h2><p>来源于检测明细与成品放行结论</p></div></div>${qualityChart(d.quality)}</section>`;
  const origins=`<section class="panel viz-panel"><div class="viz-panel-head"><div><span>ORIGIN · BATCH</span><h2>供应批次产地分布</h2><p>按供应端批次数统计，不代表地区总产量</p></div></div>${originChart(d.origins,esc)}</section>`;
  const summary=metrics+`<div class="viz-dashboard">${volume}${quality}${origins}</div>`;
  const detail=`<div class="viz-detail-layout">${volume}<section class="panel viz-panel"><div class="viz-panel-head"><div><span>DATA · TABLE</span><h2>月度数据明细</h2><p>图表所用的同一组数据</p></div></div><div class="table-wrap"><table><thead><tr><th>月份</th><th>供应量（吨）</th><th>成品量（吨）</th></tr></thead><tbody>${d.timeline.map(p=>`<tr><td>${esc(p.label)}</td><td>${compact(p.supply)}</td><td>${compact(p.output)}</td></tr>`).join('')||'<tr><td colspan="3">暂无数据</td></tr>'}</tbody></table></div></section></div>`;
  const region=`<div class="viz-region-layout"><section class="panel viz-panel"><div class="viz-panel-head"><div><span>REGION · FLOW</span><h2>产地与采购流向</h2><p>产地来自供应记录；终点来自当前会话采购需求</p></div></div>${routeChart(d.origins,request?.destination,esc)}<p class="viz-caption">流向图只表示候选关系，不表示已成交、已运输或已验收。</p></section>${origins}</div>`;
  const libraryItems=[
    ['chart','供应与加工量趋势','采收量、投料量、成品量','1','已接入'],
    ['map','区域供需流向','供应产地、采购目的地','2','已接入'],
    ['shield','质量结论构成','检测项目、放行结论','0','已接入'],
    ['database','批次产地分布','供应批次、标准产地','2','已接入'],
    ['factory','工艺参数分布','加工工序、参数名称与实测值','','待更多记录'],
    ['clock','季节供应日历','采收日期、供应起止日期','','待更多记录'],
  ];
  const library=`<div class="viz-library">${libraryItems.map(([icon,title,fields,target,status])=>`<article class="panel viz-library-card"><div class="viz-library-icon">${svg(icon,24)}</div><span>${esc(status)}</span><h2>${esc(title)}</h2><p>所需字段：${esc(fields)}</p>${target!==''?`<button class="btn" type="button" data-action="visual-goto" data-visual-tab="${target}">查看当前图表</button>`:'<button class="btn" type="button" disabled>数据积累后开放</button>'}</article>`).join('')}</div>`;
  const bodies=[summary,detail,region,library];
  return header('VISUAL ANALYTICS','产业可视化','用来源明确的批次数据形成可复核、可导出的业务图表')+`<div class="toolbar viz-toolbar">${tabs(['综合看板','产量与加工','区域供需','图表库'],tab)}<div class="actions">${button('导出当前数据','download-chart',false,'download')}</div></div>${source}${bodies[tab]||summary}`;
}
