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
  quality:{qualified:82,pending:13,unqualified:5}, updatedAt:'—',
};

const visualNumber = value => Number.isFinite(Number(value)) ? Number(value) : 0;
const compact = value => {
  const n=visualNumber(value);
  if(Math.abs(n)>=1000)return `${(n/1000).toFixed(1).replace(/\.0$/,'')}k`;
  if(Number.isInteger(n))return String(n);
  return n.toFixed(Math.abs(n)<1?2:1).replace(/0+$/,'').replace(/\.$/,'');
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
  if(!points.length)return '<div class="viz-empty"><b>暂无批次量数据</b></div>';
  const width=1000,height=260,top=10,bottom=250;
  const rawMax=Math.max(1,...points.flatMap(p=>[p.supply,p.output]));
  const magnitude=10**Math.floor(Math.log10(rawMax));
  const normalized=rawMax/magnitude;
  const step=normalized<=1?1:normalized<=2?2:normalized<=5?5:10;
  const max=step*magnitude;
  const x=i=>((i+.5)/points.length)*width;
  const y=value=>top+(1-value/max)*(bottom-top);
  const line=key=>points.map((p,i)=>`${i?'L':'M'} ${x(i).toFixed(1)} ${y(p[key]).toFixed(1)}`).join(' ');
  const area=`${line('supply')} L ${x(points.length-1).toFixed(1)} ${bottom} L ${x(0).toFixed(1)} ${bottom} Z`;
  const ticks=[1,.75,.5,.25,0];
  const grids=ticks.map(r=>`<line x1="0" x2="${width}" y1="${y(max*r).toFixed(1)}" y2="${y(max*r).toFixed(1)}"/>`).join('');
  const yLabels=ticks.map(r=>`<span style="--y:${((1-r)*92+4).toFixed(1)}%">${compact(max*r)}</span>`).join('');
  const xLabels=points.map((p,i)=>{
    if(!/^\d{4}-\d{2}$/.test(p.label))return `<span title="${esc(p.label)}">${esc(p.label)}</span>`;
    const showYear=i===0||!/^\d{4}-\d{2}$/.test(points[i-1].label)||points[i-1].label.slice(0,4)!==p.label.slice(0,4);
    return `<span class="${showYear?'year-mark':''}" title="${esc(p.label)}">${showYear?`<small>${esc(p.label.slice(2,4))}</small>`:''}${esc(p.label.slice(5))}</span>`;
  }).join('');
  const markers=points.map((p,i)=>[
    `<i class="viz-chart-point supply" style="--x:${((i+.5)/points.length*100).toFixed(2)}%;--y:${(4+(1-p.supply/max)*92).toFixed(2)}%" role="img" tabindex="0" aria-label="${esc(p.label)}供应量${compact(p.supply)}吨" title="${esc(p.label)} · 供应 ${compact(p.supply)} 吨"></i>`,
    `<i class="viz-chart-point output" style="--x:${((i+.5)/points.length*100).toFixed(2)}%;--y:${(4+(1-p.output/max)*92).toFixed(2)}%" role="img" tabindex="0" aria-label="${esc(p.label)}成品产量${compact(p.output)}吨" title="${esc(p.label)} · 成品 ${compact(p.output)} 吨"></i>`,
  ]).flat().join('');
  return `<figure class="viz-volume-figure"><div class="viz-chart-shell"><div class="viz-chart-y-axis" aria-hidden="true">${yLabels}</div><div class="viz-chart-main"><div class="viz-chart-plot"><svg class="viz-volume-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="供应量与成品产量趋势折线图"><g class="viz-grid">${grids}</g><path class="viz-area" d="${area}"/><path class="viz-line supply" d="${line('supply')}"/><path class="viz-line output" d="${line('output')}"/></svg>${markers}</div><div class="viz-chart-x-axis${points.length>8?' dense':''}" style="--columns:${points.length}" aria-hidden="true">${xLabels}</div></div></div></figure>`;
}

function qualityChart(quality) {
  const total=quality.qualified+quality.pending+quality.unqualified;
  if(!total)return '<div class="viz-empty compact"><b>暂无质检结论</b></div>';
  const pass=Math.round(quality.qualified/total*100),pending=Math.round(quality.pending/total*100);
  const items=[['pass','合格',quality.qualified],['pending','待复核',quality.pending],['fail','不合格',quality.unqualified]];
  return `<div class="viz-quality"><div class="viz-donut" style="--pass:${pass*3.6}deg;--pending:${(pass+pending)*3.6}deg" role="img" aria-label="合格占比${pass}%"><strong>${pass}%</strong><span>合格占比</span></div><div class="viz-quality-summary"><p>共计 <strong>${compact(total)}</strong> 条质检结论</p><dl>${items.map(([tone,label,value])=>`<div><dt><i class="${tone}"></i>${label}</dt><dd><strong>${compact(value)}</strong><span>${Math.round(value/total*100)}%</span></dd></div>`).join('')}</dl></div></div>`;
}

function originChart(origins, esc) {
  if(!origins.length)return '<div class="viz-empty"><b>暂无产地分布</b></div>';
  const max=Math.max(1,...origins.map(p=>p.value));
  return `<div class="viz-origin-bars">${origins.map((p,i)=>`<article class="viz-origin-row"><header><span>${String(i+1).padStart(2,'0')}</span><b>${esc(p.label)}</b><strong>${compact(p.value)}<small>批</small></strong></header><i aria-hidden="true"><em style="width:${Math.max(4,p.value/max*100)}%"></em></i></article>`).join('')}</div>`;
}

function routeChart(origins, destination, esc) {
  if(!origins.length)return '<div class="viz-empty"><b>暂无区域流向</b></div>';
  const selected=origins.slice(0,4), max=Math.max(1,...selected.map(p=>p.value));
  const total=selected.reduce((sum,p)=>sum+p.value,0);
  return `<div class="viz-route-board" role="group" aria-label="主要供应产地与采购目的地信息汇总"><div class="viz-route-heading"><span>供应来源</span><strong>${selected.length} 个主要产地</strong></div><div class="viz-route-list">${selected.map((p,i)=>`<article class="viz-route-origin"><header><span>${String(i+1).padStart(2,'0')}</span><strong>${compact(p.value)}<small>批次</small></strong></header><b>${esc(p.label)}</b><i aria-hidden="true"><em style="width:${Math.max(8,p.value/max*100)}%"></em></i></article>`).join('')}</div><div class="viz-route-merge" aria-hidden="true"><i></i><span>待匹配汇入</span><i></i><b>↓</b></div><article class="viz-route-target"><div><span>采购目的地</span><strong>${esc(destination||'待填写')}</strong></div><dl><div><dt>来源范围</dt><dd>${selected.length} 个产地</dd></div><div><dt>记录规模</dt><dd>${compact(total)} 个批次</dd></div></dl></article></div>`;
}

export function renderIndustryVisuals({tab, raw, request, header, tabs, button, svg, esc}) {
  const d=visualizationDataset(raw), preview=d.mode==='preview';
  const source=`<section class="viz-source" aria-label="数据口径"><dl><div><dt>数据状态</dt><dd><span class="viz-data-state ${preview?'preview':'recorded'}">${preview?'演示数据':'当前账号数据'}</span></dd></div><div><dt>数据来源</dt><dd>${esc(preview?'结构预览数据':d.source)}</dd></div><div><dt>记录数</dt><dd>${d.recordCount} 份</dd></div><div><dt>更新时间</dt><dd>${esc(d.updatedAt)}</dd></div></dl></section>`;
  const legend='<div class="viz-legend"><span><i class="supply"></i>供应端采收量</span><span><i class="output"></i>生产端成品产量</span><small>单位：吨</small></div>';
  const metrics=`<div class="viz-kpis"><article><span>采集记录</span><b>${compact(d.recordCount)}</b><small>供应 ${d.supplierCount} · 生产 ${d.processorCount}</small></article><article><span>供应端采收量</span><b>${compact(d.supplyTons)}<em>吨</em></b></article><article><span>生产端成品量</span><b>${compact(d.outputTons)}<em>吨</em></b></article><article><span>平均糖度</span><b>${d.averageBrix===null?'—':compact(d.averageBrix)}<em>°Brix</em></b></article></div>`;
  const volume=`<section class="panel viz-panel viz-wide"><div class="viz-panel-head"><div><span>01 / VOLUME</span><h2>供应与加工量月度对比</h2></div>${legend}</div>${volumeChart(d.timeline,esc)}</section>`;
  const quality=`<section class="panel viz-panel viz-quality-panel"><div class="viz-panel-head"><div><span>02 / QUALITY</span><h2>质检结论构成</h2></div></div>${qualityChart(d.quality)}</section>`;
  const origins=`<section class="panel viz-panel"><div class="viz-panel-head"><div><span>03 / ORIGIN</span><h2>供应批次产地分布</h2></div></div>${originChart(d.origins,esc)}</section>`;
  const summary=metrics+`<div class="viz-dashboard">${volume}${quality}${origins}</div>`;
  const detail=`<div class="viz-detail-layout">${volume}<section class="panel viz-panel"><div class="viz-panel-head"><div><span>02 / DATA</span><h2>月度数据明细</h2></div></div><div class="table-wrap"><table><thead><tr><th>月份</th><th>供应量（吨）</th><th>成品量（吨）</th></tr></thead><tbody>${d.timeline.map(p=>`<tr><td>${esc(p.label)}</td><td>${compact(p.supply)}</td><td>${compact(p.output)}</td></tr>`).join('')||'<tr><td colspan="3">暂无数据</td></tr>'}</tbody></table></div></section></div>`;
  const region=`<div class="viz-region-layout"><section class="panel viz-panel"><div class="viz-panel-head"><div><span>01 / FLOW</span><h2>区域供需位置关系</h2></div></div>${routeChart(d.origins,request?.destination,esc)}</section>${origins}</div>`;
  const libraryItems=[
    ['chart','供应与加工量月度对比','采收量、成品量','1','已接入'],
    ['map','区域供需流向','供应产地、采购目的地','2','已接入'],
    ['shield','质量结论构成','检测项目、放行结论','0','已接入'],
    ['database','批次产地分布','供应批次、标准产地','2','已接入'],
    ['factory','工艺参数分布','加工工序、参数名称与实测值','','待更多记录'],
    ['clock','季节供应日历','采收日期、供应起止日期','','待更多记录'],
  ];
  const library=`<div class="viz-library">${libraryItems.map(([icon,title,fields,target,status])=>`<article class="panel viz-library-card"><div class="viz-library-head"><div class="viz-library-icon">${svg(icon,24)}</div><div class="viz-library-copy"><h2>${esc(title)}</h2><p>所需字段：${esc(fields)}</p></div><span>${esc(status)}</span></div>${target!==''?`<button class="btn" type="button" data-action="visual-goto" data-visual-tab="${target}">查看当前图表</button>`:'<button class="btn" type="button" disabled>数据积累后开放</button>'}</article>`).join('')}</div>`;
  const bodies=[summary,detail,region,library];
  return header('VISUAL ANALYTICS','产业可视化')+`<div class="toolbar viz-toolbar">${tabs(['综合看板','产量与加工','区域供需','图表库'],tab)}<div class="actions">${button('导出当前数据','download-chart',false,'download')}</div></div>${source}${bodies[tab]||summary}`;
}
