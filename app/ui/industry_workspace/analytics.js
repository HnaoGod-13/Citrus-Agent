// Evidence-labelled industry charts. Concatenated before workspace.js.
const VISUAL_PREVIEW = {
  source:'结构预览数据（非政府统计、非企业实报）', recordCount:48, supplierCount:31,
  processorCount:17, submittedCount:39, draftCount:9, supplyTons:84.6,
  inputTons:72.4, outputTons:28.9, averageBrix:12.3, brixCount:12,
  timeline:[
    {label:'04月',supply:10.5,output:3.2},{label:'05月',supply:12.6,output:4.1},
    {label:'06月',supply:13.8,output:4.6},{label:'07月',supply:14.2,output:5},
    {label:'08月',supply:16,output:5.8},{label:'09月',supply:17.5,output:6.2},
  ],
  origins:[{label:'重庆奉节',value:12},{label:'江西赣州',value:8},{label:'广西武鸣',value:6},{label:'山东临沂',value:5}],
  quality:{qualified:82,pending:13,unqualified:5}, updatedAt:'—',
};

const visualNumber = value => Number.isFinite(Number(value)) ? Number(value) : 0;
const compact = value => {
  const n=visualNumber(value);
  if(Math.abs(n)>=1000)return `${(n/1000).toFixed(1).replace(/\.0$/,'')}k`;
  if(Number.isInteger(n))return String(n);
  return n.toFixed(Math.abs(n)<1?2:1).replace(/0+$/,'').replace(/\.$/,'');
};
const sum = (rows,key) => rows.reduce((total,row)=>total+visualNumber(row[key]),0);
const cleanFilters = filters => ({
  period:String(filters?.period||''), origin:String(filters?.origin||''),
  side:String(filters?.side||''), status:String(filters?.status||''),
});
const statusLabel = value => ({draft:'草稿',submitted:'已提交',approved:'已通过',needs_changes:'待修改',rejected:'已退回',archived:'已归档'})[value]||value;
const sideLabel = value => ({supplier:'供应端',processor:'生产端'})[value]||value;

function normalizeMetricRecord(record={}) {
  const date=String(record.date||'');
  return {
    side:String(record.side||''), status:String(record.status||''), date,
    period:/^\d{4}-\d{2}/.test(date)?date.slice(0,7):date,
    origin:String(record.origin||''), supplyTons:Math.max(0,visualNumber(record.supplyTons)),
    inputTons:Math.max(0,visualNumber(record.inputTons)), outputTons:Math.max(0,visualNumber(record.outputTons)),
    brix:record.brix===null||record.brix===undefined||record.brix===''?null:visualNumber(record.brix),
    quality:{qualified:visualNumber(record.quality?.qualified),pending:visualNumber(record.quality?.pending),unqualified:visualNumber(record.quality?.unqualified)},
    updatedAt:String(record.updatedAt||''),
  };
}

function aggregateMetricRecords(records, raw) {
  const timeline=new Map(), origins=new Map(), brix=[];
  const quality={qualified:0,pending:0,unqualified:0};
  for(const row of records){
    const period=row.period||'日期待补';
    const point=timeline.get(period)||{label:period,supply:0,output:0};
    point.supply+=row.supplyTons;point.output+=row.outputTons;timeline.set(period,point);
    if(row.side==='supplier'&&row.origin)origins.set(row.origin,(origins.get(row.origin)||0)+1);
    if(row.brix!==null)brix.push(row.brix);
    for(const key of Object.keys(quality))quality[key]+=row.quality[key];
  }
  const orderedTimeline=[...timeline.values()].sort((a,b)=>a.label.localeCompare(b.label)).slice(-12).map(point=>({
    ...point,supply:Number(point.supply.toFixed(3)),output:Number(point.output.toFixed(3)),
  }));
  return {
    mode:'recorded', source:String(raw.source||'当前账号产业数据采集记录'), recordCount:records.length,
    supplierCount:records.filter(row=>row.side==='supplier').length,
    processorCount:records.filter(row=>row.side==='processor').length,
    submittedCount:records.filter(row=>row.status!=='draft').length,
    draftCount:records.filter(row=>row.status==='draft').length,
    supplyTons:Number(sum(records,'supplyTons').toFixed(3)), inputTons:Number(sum(records,'inputTons').toFixed(3)),
    outputTons:Number(sum(records,'outputTons').toFixed(3)),
    averageBrix:brix.length?Number((brix.reduce((a,b)=>a+b,0)/brix.length).toFixed(2)):null,
    brixCount:brix.length, timeline:orderedTimeline,
    origins:[...origins].map(([label,value])=>({label,value})).sort((a,b)=>b.value-a.value).slice(0,8),
    quality, updatedAt:records.map(row=>row.updatedAt).filter(Boolean).sort().at(-1)||String(raw.updatedAt||''),
  };
}

export function visualizationFilterOptions(raw={}) {
  const records=Array.isArray(raw.records)?raw.records.map(normalizeMetricRecord):[];
  const unique=values=>[...new Set(values.filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b),'zh-CN'));
  return {
    periods:unique(records.map(row=>row.period)).reverse(), origins:unique(records.filter(row=>row.side==='supplier').map(row=>row.origin)),
    sides:unique(records.map(row=>row.side)), statuses:unique(records.map(row=>row.status)), enabled:records.length>0,
  };
}

export function visualizationDataset(raw={}, filters={}) {
  const real=visualNumber(raw.recordCount)>0;
  const normalizedFilters=cleanFilters(filters);
  if(real&&Array.isArray(raw.records)){
    const records=raw.records.map(normalizeMetricRecord).filter(row=>(
      (!normalizedFilters.period||row.period===normalizedFilters.period)&&
      (!normalizedFilters.origin||row.origin===normalizedFilters.origin)&&
      (!normalizedFilters.side||row.side===normalizedFilters.side)&&
      (!normalizedFilters.status||row.status===normalizedFilters.status)
    ));
    return {...aggregateMetricRecords(records,raw),filters:normalizedFilters,filtered:Object.values(normalizedFilters).some(Boolean)};
  }
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
    brixCount:visualNumber(source.brixCount), timeline, origins,
    quality:{qualified:visualNumber(source.quality?.qualified),pending:visualNumber(source.quality?.pending),unqualified:visualNumber(source.quality?.unqualified)},
    updatedAt, filters:normalizedFilters, filtered:false,
  };
}

export function visualizationCsv(raw={}, filters={}) {
  const d=visualizationDataset(raw,filters), quote=value=>`"${String(value??'').replaceAll('"','""')}"`;
  const filterRows=Object.entries(d.filters||{}).filter(([,value])=>value).map(([key,value])=>[`筛选条件：${{period:'月份',origin:'产地',side:'记录类型',status:'记录状态'}[key]}`,value]);
  const rows=[
    ['数据属性',d.mode==='recorded'?'当前账号采集数据':'结构预览数据'],['数据来源',d.source],['更新时间',d.updatedAt],...filterRows,[],
    ['核心指标','数值','单位'],['采集记录',d.recordCount,'条'],['供应端采收量',d.supplyTons,'吨'],['投入加工量',d.inputTons,'吨'],['成品产量',d.outputTons,'吨'],['平均糖度',d.averageBrix??'','°Brix'],[],
    ['月份','供应量（吨）','成品产量（吨）'],...d.timeline.map(p=>[p.label,p.supply,p.output]),[],
    ['产地','供应端记录数'],...d.origins.map(p=>[p.label,p.value]),[],
    ['质量结论','数量'],['合格',d.quality.qualified],['待复核',d.quality.pending],['不合格',d.quality.unqualified],
  ];
  return '\ufeff'+rows.map(row=>row.map(quote).join(',')).join('\r\n');
}

function volumeChart(points, esc) {
  if(!points.length)return '<div class="viz-empty"><b>暂无可分析的时间序列</b><span>采集记录包含日期和数量后，这里会显示真实趋势。</span></div>';
  const width=1000,height=260,top=10,bottom=250;
  const rawMax=Math.max(1,...points.flatMap(p=>[p.supply,p.output]));
  const magnitude=10**Math.floor(Math.log10(rawMax));
  const normalized=rawMax/magnitude;
  const step=normalized<=1?1:normalized<=2?2:normalized<=5?5:10;
  const max=step*magnitude;
  const x=i=>((i+.5)/points.length)*width;
  const y=value=>top+(1-value/max)*(bottom-top);
  const line=points.map((p,i)=>`${i?'L':'M'} ${x(i).toFixed(1)} ${y(p.output).toFixed(1)}`).join(' ');
  const ticks=[1,.75,.5,.25,0];
  const grids=ticks.map(r=>`<line x1="0" x2="${width}" y1="${y(max*r).toFixed(1)}" y2="${y(max*r).toFixed(1)}"/>`).join('');
  const yLabels=ticks.map(r=>`<span style="--y:${((1-r)*92+4).toFixed(1)}%">${compact(max*r)}</span>`).join('');
  const xLabels=points.map((p,i)=>{
    if(!/^\d{4}-\d{2}$/.test(p.label))return `<span title="${esc(p.label)}">${esc(p.label)}</span>`;
    const showYear=i===0||!/^\d{4}-\d{2}$/.test(points[i-1].label)||points[i-1].label.slice(0,4)!==p.label.slice(0,4);
    return `<span class="${showYear?'year-mark':''}" title="${esc(p.label)}">${showYear?`<small>${esc(p.label.slice(0,4))}</small>`:''}${esc(p.label.slice(5))}月</span>`;
  }).join('');
  const bars=points.map((p,i)=>{
    const barWidth=Math.min(46,Math.max(16,width/points.length*.42)),barX=x(i)-barWidth/2,barY=y(p.supply);
    return `<rect class="viz-bar-fill" x="${barX.toFixed(1)}" y="${barY.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${Math.max(0,bottom-barY).toFixed(1)}" rx="5"><title>${esc(p.label)} · 供应端采收量 ${compact(p.supply)} 吨</title></rect>`;
  }).join('');
  const markers=points.map((p,i)=>`<i class="viz-chart-point output" style="--x:${((i+.5)/points.length*100).toFixed(2)}%;--y:${(4+(1-p.output/max)*92).toFixed(2)}%" role="img" tabindex="0" aria-label="${esc(p.label)}成品产量${compact(p.output)}吨" title="${esc(p.label)} · 成品产量 ${compact(p.output)} 吨"></i>`).join('');
  return `<figure class="viz-volume-figure"><div class="viz-chart-shell"><div class="viz-chart-y-axis" aria-hidden="true">${yLabels}</div><div class="viz-chart-main"><div class="viz-chart-plot"><svg class="viz-volume-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="供应量与成品产量趋势图"><g class="viz-grid">${grids}</g><g class="viz-bars">${bars}</g><path class="viz-line output" d="${line}"/></svg>${markers}</div><div class="viz-chart-x-axis${points.length>8?' dense':''}" style="--columns:${points.length}" aria-hidden="true">${xLabels}</div></div></div></figure>`;
}

function qualityChart(d) {
  const quality=d.quality,total=quality.qualified+quality.pending+quality.unqualified;
  const pass=total?Math.round(quality.qualified/total*100):null,pending=total?Math.round(quality.pending/total*100):0;
  const items=[['pass','合格',quality.qualified],['pending','待复核',quality.pending],['fail','不合格',quality.unqualified]];
  const donut=total?`<div class="viz-donut" style="--pass:${pass*3.6}deg;--pending:${(pass+pending)*3.6}deg" role="img" aria-label="合格占比${pass}%"><strong>${pass}%</strong><span>合格占比</span></div>`:'<div class="viz-donut is-empty" role="img" aria-label="暂无质检结论"><strong>—</strong><span>暂无结论</span></div>';
  return `<div class="viz-quality"><div class="viz-brix-card"><span>平均糖度</span><strong>${d.averageBrix===null?'—':compact(d.averageBrix)}<small>${d.averageBrix===null?'':'°Brix'}</small></strong><p>${d.brixCount?`来自 ${compact(d.brixCount)} 条有效糖度记录`:'暂无有效糖度样本'}</p></div><div class="viz-quality-status">${donut}<dl>${items.map(([tone,label,value])=>`<div><dt><i class="${tone}"></i>${label}</dt><dd><strong>${compact(value)}</strong><span>${total?Math.round(value/total*100):0}%</span></dd></div>`).join('')}</dl></div><p class="viz-quality-note">结论仅汇总已录入的检测或放行判定；平均糖度为描述性指标，不单独作为合格依据。</p></div>`;
}

function originChart(origins, esc) {
  if(!origins.length)return '<div class="viz-empty compact"><b>暂无产地分布</b></div>';
  const max=Math.max(1,...origins.map(p=>p.value));
  return `<div class="viz-origin-bars">${origins.map((p,i)=>`<article class="viz-origin-row"><header><span>${String(i+1).padStart(2,'0')}</span><b>${esc(p.label)}</b><strong>${compact(p.value)}<small>条</small></strong></header><i aria-hidden="true"><em style="width:${Math.max(4,p.value/max*100)}%"></em></i></article>`).join('')}</div>`;
}

function sparkline(values, label='指标趋势') {
  const points=values.filter(value=>Number.isFinite(Number(value))).map(Number);
  if(points.length<2)return '';
  const max=Math.max(...points),min=Math.min(...points),span=Math.max(max-min,1);
  const coords=points.map((value,index)=>[(index/(points.length-1))*100,8+((max-value)/span)*34]);
  const line=coords.map(([x,y],index)=>`${index?'L':'M'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' '),area=`${line} L 100 50 L 0 50 Z`;
  return `<svg class="viz-sparkline" viewBox="0 0 100 52" preserveAspectRatio="none" role="img" aria-label="${label}"><path class="viz-spark-area" d="${area}"/><path class="viz-spark-line" d="${line}"/><circle cx="${coords.at(-1)[0].toFixed(1)}" cy="${coords.at(-1)[1].toFixed(1)}" r="2.5"/></svg>`;
}

function regionDistribution(origins, esc) {
  if(!origins.length)return '<div class="viz-empty"><b>暂无区域分布数据</b><span>供应端记录补充产地后，这里会按真实字段聚合。</span></div>';
  const selected=origins.slice(0,6),total=selected.reduce((value,item)=>value+item.value,0),top=selected[0];
  return `<div class="viz-region-board"><div class="viz-region-summary"><span>已识别产地</span><strong>${selected.length}<small>个</small></strong><p>最高产地 <b>${esc(top.label)}</b> · ${compact(top.value)} 条</p></div><div class="viz-region-share"><div class="viz-region-segments" role="img" aria-label="产地记录份额">${selected.map((item,index)=>`<i class="tone-${index%4}" style="width:${(item.value/Math.max(total,1)*100).toFixed(2)}%" title="${esc(item.label)} ${compact(item.value)} 条"></i>`).join('')}</div><div class="viz-region-items">${selected.map((item,index)=>`<div><span><i class="tone-${index%4}"></i>${esc(item.label)}</span><strong>${compact(item.value)}<small>条 · ${Math.round(item.value/Math.max(total,1)*100)}%</small></strong></div>`).join('')}</div><p>当前记录未收集经纬度或行政区编码，因此以份额视图呈现，不推断地理位置。</p></div></div>`;
}

function recordMixChart(d) {
  const supplier=Math.max(0,d.supplierCount),processor=Math.max(0,d.processorCount),total=supplier+processor;
  if(!total)return '<div class="viz-empty compact"><b>暂无记录构成</b></div>';
  const supplierDeg=supplier/total*360;
  return `<div class="viz-mix"><div class="viz-mix-donut" style="--supplier:${supplierDeg}deg" role="img" aria-label="供应端占比${Math.round(supplier/total*100)}%"><strong>${compact(total)}</strong><span>条记录</span></div><div class="viz-mix-list"><div><span><i></i>供应端</span><strong>${compact(supplier)}<small>${Math.round(supplier/total*100)}%</small></strong></div><div><span><i class="processor"></i>生产端</span><strong>${compact(processor)}<small>${Math.round(processor/total*100)}%</small></strong></div><p>已提交 ${compact(d.submittedCount)} 条 · 草稿 ${compact(d.draftCount)} 条</p></div></div>`;
}

function routeChart(origins, destination, esc) {
  if(!origins.length)return '<div class="viz-empty"><b>暂无区域流向</b></div>';
  const selected=origins.slice(0,4),max=Math.max(1,...selected.map(p=>p.value)),total=selected.reduce((value,p)=>value+p.value,0);
  return `<div class="viz-route-board" role="group" aria-label="主要供应产地与采购目的地信息汇总"><div class="viz-route-heading"><span>供应来源</span><strong>${selected.length} 个主要产地</strong></div><div class="viz-route-list">${selected.map((p,i)=>`<article class="viz-route-origin"><header><span>${String(i+1).padStart(2,'0')}</span><strong>${compact(p.value)}<small>条记录</small></strong></header><b>${esc(p.label)}</b><i aria-hidden="true"><em style="width:${Math.max(8,p.value/max*100)}%"></em></i></article>`).join('')}</div><div class="viz-route-merge" aria-hidden="true"><i></i><span>待匹配汇入</span><i></i><b>↓</b></div><article class="viz-route-target"><div><span>采购目的地</span><strong>${esc(destination||'待填写')}</strong></div><dl><div><dt>来源范围</dt><dd>${selected.length} 个产地</dd></div><div><dt>记录规模</dt><dd>${compact(total)} 条记录</dd></div></dl></article></div>`;
}

function filterSelect(name,label,value,items,esc,formatter=v=>v,disabled=false) {
  return `<label><span>${label}</span><select data-visual-filter="${name}" aria-label="${label}"${disabled?' disabled':''}><option value="">全部</option>${items.map(item=>`<option value="${esc(item)}"${value===item?' selected':''}>${esc(formatter(item))}</option>`).join('')}</select></label>`;
}

export function renderIndustryVisuals({tab,raw,request,filters,header,tabs,button,svg,esc}) {
  const activeFilters=cleanFilters(filters),d=visualizationDataset(raw,activeFilters),preview=d.mode==='preview',options=visualizationFilterOptions(raw);
  const sourceLabel=preview?'结构预览数据':d.source,status=preview?'演示数据':d.filtered?'已筛选数据':'当前账号数据';
  const hasFilter=Object.values(activeFilters).some(Boolean);
  const controls=`<section class="viz-controls" aria-label="看板筛选与数据状态"><div class="viz-data-meta"><span class="viz-status${preview?' is-preview':''}"><i></i>${status}</span><p><strong>数据来源 · ${esc(sourceLabel)}</strong><span>${compact(d.recordCount)} 条记录 · 更新 ${esc(d.updatedAt||'暂无')}</span></p></div><div class="viz-filters${options.enabled?'':' is-disabled'}">${filterSelect('period','月份',activeFilters.period,options.periods,esc,v=>v,!options.enabled)}${filterSelect('origin','产地',activeFilters.origin,options.origins,esc,v=>v,!options.enabled)}${filterSelect('side','记录类型',activeFilters.side,options.sides,esc,sideLabel,!options.enabled)}${filterSelect('status','状态',activeFilters.status,options.statuses,esc,statusLabel,!options.enabled)}${hasFilter?'<button type="button" class="viz-filter-reset" data-action="visual-filter-reset">清除筛选</button>':''}</div></section>`;
  const metric=(icon,label,value,unit,detail,tone,trend=[])=>`<article class="viz-kpi ${tone||''}"><div class="viz-kpi-icon">${svg(icon,18)}</div><div class="viz-kpi-copy"><span>${label}</span><b>${value}${unit?`<em>${unit}</em>`:''}</b><small>${detail||'—'}</small></div>${sparkline(trend,label+'趋势')}</article>`;
  const supplySeries=d.timeline.map(point=>point.supply),outputSeries=d.timeline.map(point=>point.output);
  const metrics=`<section class="viz-kpis" aria-label="核心指标">${metric('database','采集记录总量',compact(d.recordCount),'条',`供应端 ${compact(d.supplierCount)} · 生产端 ${compact(d.processorCount)}`,'neutral')}${metric('conveyor','供应端采收量',compact(d.supplyTons),'吨','按供应端采收量汇总','supply',supplySeries)}${metric('factory','投入加工量',compact(d.inputTons),'吨','按生产端原料投入汇总','warning')}${metric('box','成品产量',compact(d.outputTons),'吨',`产出率 ${d.inputTons?Math.round(d.outputTons/d.inputTons*100)+'%':'—'}`,'output',outputSeries)}</section>`;
  const legend='<div class="viz-legend"><span><i class="supply"></i>供应端采收量</span><span><i class="output"></i>生产端成品产量</span><small>单位：吨</small></div>';
  const volume=`<section class="panel viz-panel viz-volume-panel"><div class="viz-panel-head"><div><h2>供应与加工量趋势</h2><p>按采集记录日期归集；柱形为采收量，折线为成品产量。</p></div>${legend}</div>${volumeChart(d.timeline,esc)}</section>`;
  const qualityTotal=d.quality.qualified+d.quality.pending+d.quality.unqualified,passRate=qualityTotal?Math.round(d.quality.qualified/qualityTotal*100):null;
  const quality=`<section class="panel viz-panel viz-quality-panel"><div class="viz-panel-head"><div><h2>质量分析</h2><p>糖度与质检结论均来自已保存的字段。</p></div><span class="viz-panel-badge">${passRate===null?'暂无结论':`合格 ${passRate}%`}</span></div>${qualityChart(d)}</section>`;
  const origins=`<section class="panel viz-panel viz-origin-panel"><div class="viz-panel-head"><div><h2>主要供应产地排行</h2><p>按供应端采集记录数排序，单位为条记录。</p></div><span class="viz-panel-badge">Top ${Math.min(5,d.origins.length)}</span></div>${originChart(d.origins.slice(0,5),esc)}</section>`;
  const scope=`<section class="panel viz-panel viz-scope-panel"><div class="viz-panel-head"><div><h2>数据覆盖与状态</h2><p>统计维度为当前授权范围内的采集记录。</p></div></div><div class="viz-scope-grid"><div><span>供应端</span><strong>${compact(d.supplierCount)}</strong><small>条记录</small></div><div><span>生产端</span><strong>${compact(d.processorCount)}</strong><small>条记录</small></div><div><span>已提交</span><strong>${compact(d.submittedCount)}</strong><small>非草稿记录</small></div><div><span>草稿</span><strong>${compact(d.draftCount)}</strong><small>条记录</small></div></div><div class="viz-scope-total"><span>${d.filtered?'筛选后记录总量':'授权记录总量'}</span><strong>${compact(d.recordCount)} <small>条</small></strong></div></section>`;
  const recordMix=`<section class="panel viz-panel viz-mix-panel"><div class="viz-panel-head"><div><h2>供应与生产构成</h2><p>按记录类型统计，与总量口径一致。</p></div></div>${recordMixChart(d)}</section>`;
  const regionPanel=`<section class="panel viz-panel viz-region-panel"><div class="viz-panel-head"><div><h2>供应区域分布</h2><p>按供应端产地字段聚合，份额按记录数计算。</p></div><span class="viz-panel-badge">${d.origins.length?`${d.origins.length} 个产地`:'暂无产地'}</span></div>${regionDistribution(d.origins,esc)}</section>`;
  const summary=`${controls}${metrics}<div class="viz-dashboard-home"><div class="viz-top-grid">${regionPanel}${origins}</div>${volume}<div class="viz-lower-grid">${quality}<div class="viz-lower-stack">${recordMix}${scope}</div></div></div>`;
  const detail=`${controls}<div class="viz-detail-layout">${volume}<section class="panel viz-panel"><div class="viz-panel-head"><div><h2>月度数据明细</h2><p>与趋势图使用相同的筛选口径。</p></div></div><div class="table-wrap"><table><thead><tr><th>月份</th><th>供应量（吨）</th><th>成品量（吨）</th></tr></thead><tbody>${d.timeline.map(p=>`<tr><td>${esc(p.label)}</td><td>${compact(p.supply)}</td><td>${compact(p.output)}</td></tr>`).join('')||'<tr><td colspan="3">暂无数据</td></tr>'}</tbody></table></div></section></div>`;
  const region=`${controls}<div class="viz-region-layout">${regionPanel}${origins}<section class="panel viz-panel viz-route-panel"><div class="viz-panel-head"><div><h2>供需位置关系</h2><p>只展示已记录的产地与当前需求目的地。</p></div></div>${routeChart(d.origins,request?.destination,esc)}</section></div>`;
  const libraryItems=[
    ['chart','供应与加工量月度对比','采收量、成品量','1','已接入'],
    ['map','供应区域份额','供应产地','2','已接入'],
    ['shield','质量结论构成','检测项目、放行结论','0','已接入'],
    ['database','采集记录产地排行','供应端记录、标准产地','2','已接入'],
    ['factory','工艺参数分布','加工工序、参数名称与实测值','','待更多记录'],
    ['clock','季节供应日历','采收日期、供应起止日期','','待更多记录'],
  ];
  const library=`<div class="viz-library">${libraryItems.map(([icon,title,fields,target,state])=>`<article class="panel viz-library-card"><div class="viz-library-head"><div class="viz-library-icon">${svg(icon,22)}</div><div class="viz-library-copy"><h2>${esc(title)}</h2><p>所需字段：${esc(fields)}</p></div><span>${esc(state)}</span></div>${target!==''?`<button class="btn" type="button" data-action="visual-goto" data-visual-tab="${target}">查看当前图表</button>`:'<button class="btn" type="button" disabled>数据积累后开放</button>'}</article>`).join('')}</div>`;
  const bodies=[summary,detail,region,library];
  return `<div class="toolbar viz-toolbar">${tabs(['综合看板','产量与加工','区域供需','图表库'],tab)}<div class="actions">${button('导出当前数据','download-chart',false,'download')}</div></div>${bodies[tab]||summary}`;
}
