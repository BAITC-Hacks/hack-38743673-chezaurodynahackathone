'use strict';
const $ = selector => document.querySelector(selector);
const state = {meta:null, busy:false, briefDirty:false, hasResults:false, searchId:null, formRevision:0, manualFields:new Set()};
const fields = {city:'city',event_date:'eventDate',category:'category',event_format:'eventFormat',language:'language',duration_hours:'duration',budget_kzt:'budget',min_budget_kzt:'minBudget',sort_by:'sortBy'};
const fieldNames = {city:'город',event_date:'дата',category:'категория',event_format:'формат',budget_kzt:'бюджет',language:'язык',duration_hours:'длительность'};
const money = value => new Intl.NumberFormat('ru-RU').format(value)+' ₸';
const escapeHtml = value => String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const compactDate = value => new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'2-digit'}).format(new Date(value+'T12:00:00'));
const fullDate = value => new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'long',year:'numeric'}).format(new Date(value+'T12:00:00'));

async function request(path,payload){
  const controller = new AbortController();
  const timeout = setTimeout(()=>controller.abort(),45000);
  try{
    const response = await fetch(path,{method:payload?'POST':'GET',headers:payload?{'Content-Type':'application/json'}:{},body:payload?JSON.stringify(payload):undefined,signal:controller.signal});
    const type = response.headers.get('Content-Type')||'';
    if(!type.includes('application/json')) throw new Error('Сервер подбора недоступен. Запустите сайт через run.py и обновите страницу.');
    const data = await response.json();
    if(!response.ok) throw new Error(data.error||'Не удалось выполнить запрос. Попробуйте ещё раз.');
    return data;
  }catch(error){
    if(error.name==='AbortError') throw new Error('Сервер не ответил вовремя. Попробуйте ещё раз или отключите ИИ для локального подбора.');
    if(error instanceof TypeError) throw new Error('Нет соединения с сервером. Проверьте, что он запущен, и повторите запрос.');
    throw error;
  }finally{clearTimeout(timeout);}
}
function fillSelect(id,values,placeholder){
  const select = $(id);select.replaceChildren(new Option(placeholder,''));
  for(const value of values) select.add(new Option(value,value));
}
function setBusy(busy,label='Найти подрядчиков'){
  state.busy=busy;
  $('#searchButton').disabled=busy||!state.meta;
  $('#searchButton').firstElementChild.textContent=label;
  $('#parseButton').disabled=busy||!state.meta;
  $('#resetButton').disabled=busy;
  $('#demoButton').disabled=busy||!state.meta;
  document.querySelectorAll('[data-example]').forEach(button=>button.disabled=busy||!state.meta);
  $('#resultsPanel').setAttribute('aria-busy',String(busy));
}
function notice(text,warning=false){
  $('#briefNotice').textContent=text;$('#briefNotice').hidden=!text;
  $('#briefNotice').classList.toggle('warning',warning);
}
function applyQuery(query){
  for(const [key,id] of Object.entries(fields)){
    const element=$('#'+id);const value=query[key]??(key==='sort_by'?'relevance':'');
    if(element.tagName==='SELECT'&&value&&!Array.from(element.options).some(o=>o.value===String(value))) element.add(new Option(value,value));
    element.value=value;
  }
  validateBudgetRange();
}
function queryFromForm(){
  return {city:$('#city').value,event_date:$('#eventDate').value,category:$('#category').value,event_format:$('#eventFormat').value,language:$('#language').value||null,duration_hours:$('#duration').value?Number($('#duration').value):null,budget_kzt:Number($('#budget').value),min_budget_kzt:Number($('#minBudget').value)||0,include_synthetic:$('#includeSynthetic').checked,sort_by:$('#sortBy').value,preferences:$('#description').value.trim(),use_ai:$('#useAI').checked};
}
function markStale(){
  state.searchId=null;
  document.querySelectorAll('[data-select-contractor]').forEach(button=>button.disabled=true);
  if(state.hasResults&&!$('#staleNotice')){
    const message=document.createElement('div');message.id='staleNotice';message.className='stale-label';
    message.textContent='Условия изменены. Выполните подбор ещё раз, чтобы обновить список.';
    $('#result').prepend(message);
  }
}
async function parseBrief(){
  const description=$('#description').value.trim();
  if(!description){notice('Опишите мероприятие или заполните параметры вручную.',true);return null;}
  const revision=state.formRevision;
  const data=await request('/api/parse-brief',{description,use_ai:$('#useAI').checked});
  if(revision!==state.formRevision){notice('Описание или параметры изменились во время разбора. Повторите разбор, чтобы применить актуальный текст.',true);return null;}
  const manual={};
  for(const key of state.manualFields)manual[key]=$('#'+fields[key]).value;
  applyQuery({...data.query,...manual});state.briefDirty=false;
  const missing=['city','event_date','category','event_format','budget_kzt'].filter(key=>!$('#'+fields[key]).value).map(key=>fieldNames[key]);
  const warnings=(data.warnings||[]).map(String);
  $('#parseState').textContent=data.mode==='ai'?'Разобрано ИИ':'Локальный разбор';
  const messages=[data.message||'Параметры заполнены из описания. Проверьте их перед подбором.'];
  if(Object.keys(manual).length)messages.push('Параметры, введённые вручную, сохранены.');
  if(missing.length) messages.push('Уточните: '+missing.join(', ')+'.');
  messages.push(...warnings);
  notice(messages.join(' '),missing.length>0||warnings.length>0);
  markStale();return data;
}
async function onParse(){
  if(state.busy)return;
  setBusy(true,'Разбираем описание…');
  try{await parseBrief();}catch(error){notice(error.message,true);}finally{setBusy(false);}
}
function examples(index){
  const sample=state.meta.demo_cases[index];
  return {...sample.query,description:sample.description};
}
function applyExample(index){
  const query=examples(index);state.manualFields.clear();applyQuery(query);$('#includeSynthetic').checked=true;$('#description').value=query.description;state.briefDirty=false;state.formRevision++;
  $('#parseState').textContent='Пример';notice('Пример заполнен. Вы можете изменить описание и параметры.');markStale();
}
async function submit(event,localDemo=false){
  if(event)event.preventDefault();if(state.busy||!state.meta)return;
  setBusy(true,'Проверяем условия…');
  try{
    if(state.briefDirty&&$('#description').value.trim()){
      $('#searchButton').firstElementChild.textContent='Разбираем описание…';
      const parsed=await parseBrief();if(!parsed)return;
      notice($('#briefNotice').textContent+' Проверьте распознанные условия и нажмите «Найти подрядчиков» ещё раз.',!!parsed.missing_fields?.length);
      $('#searchForm').reportValidity();return;
    }
    validateBudgetRange();
    if(!$('#searchForm').reportValidity())return;
    const query=queryFromForm();if(localDemo)query.use_ai=false;
    const revision=state.formRevision;
    $('#emptyState').hidden=true;$('#result').hidden=false;
    $('#result').innerHTML='<div class="loading-box"><div class="spinner" aria-hidden="true"></div>Проверяем ограничения и сравниваем профили…</div>';
    const started=performance.now();const data=await request('/api/recommend',query);
    renderResult(data,query,Math.round(performance.now()-started),localDemo);
    if(revision!==state.formRevision)markStale();
    if(window.matchMedia('(max-width:760px)').matches)$('#resultsPanel').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(error){renderError(error.message);}finally{setBusy(false);}
}
function renderResult(data,query,runtime,demo){
  state.searchId=data.saved?data.search_id:null;
  state.hasResults=true;$('#emptyState').hidden=true;$('#result').hidden=false;$('#resultCount').textContent=data.results.length+' / 3';
  const success=data.status==='success';
  const mode=data.ai?.used?'ИИ-подбор':(data.ai?.message||'Локальный поиск по словам. ИИ не использовался.');
  $('#result').innerHTML=`<div class="outcome ${success?'':'warning'}"><span class="outcome-icon" aria-hidden="true">${success?'✓':'!'}</span><div><h4>${escapeHtml(data.title)}</h4><p>${escapeHtml(data.message)}</p></div></div><p class="mode-note">${demo?'Пример подбора · ':''}${escapeHtml(mode)}${data.ai?.used&&data.ai.message?' · '+escapeHtml(data.ai.message):''}<br>${escapeHtml(fullDate(query.event_date))} · ${escapeHtml(query.city)} · до ${money(query.budget_kzt)} · ${(runtime/1000).toFixed(1)} с</p><div class="cards">${data.results.map((item,index)=>renderCard(item,index,query)).join('')}</div>${renderAudit(data)}<p class="saved-note">${data.saved?'Запрос и результат сохранены в базе.':''}</p>`;
}
function renderCard(item,index,query){
  const badges=[`<span class="tag">${escapeHtml(item.id)}</span>`,`<span class="tag">${item.synthetic?'Синтетический профиль':'Исходный профиль'}</span>`];
  if(item.synthetic)badges[1]=badges[1].replace('class="tag"','class="tag synthetic"');
  if(item.price_imputed)badges.push('<span class="tag imputed">Цена восстановлена</span>');
  if(item.city_imputed)badges.push('<span class="tag imputed">Город восстановлен</span>');
  const days=(item.busy_dates||[]).map(compactDate).join(', ');
  const scoreFactors=Object.entries(item.score_factors||{}).map(([name,value])=>`<div class="pipeline-row"><span>${escapeHtml(name)}</span><strong>${escapeHtml(value)} / 100</strong></div>`).join('');
  return `<article class="contractor-card"><div class="card-head"><span class="rank" aria-label="Место ${index+1}">${index+1}</span><div class="card-title"><h4>${escapeHtml(item.name)}</h4><p>${escapeHtml(item.category)} · ${escapeHtml(item.city)}</p></div><div class="price"><strong>от ${money(item.price_from_kzt)}</strong><span>в рамках бюджета</span></div></div><div class="tags">${badges.join('')}</div><div class="explanation"><div class="explanation-label"><span aria-hidden="true">✦</span> Почему этот кандидат</div><p>${escapeHtml(item.explanation)}</p></div><dl class="profile-facts"><div><dt>Форматы</dt><dd>${escapeHtml(item.event_formats.join(', '))}</dd></div><div><dt>Языки</dt><dd>${escapeHtml(item.languages.join(', '))}</dd></div><div><dt>Ваша дата · ${escapeHtml(compactDate(query.event_date))}</dt><dd>Не занята в календаре выборки</dd></div><div><dt>Время на площадке</dt><dd>${item.max_hours==null?'Не применяется к профилю':escapeHtml(item.max_hours)+' ч максимум'}</dd></div></dl><details class="card-details"><summary>Занятые даты и оценка соответствия</summary><p>Занятые даты 2026 года: ${escapeHtml(days||'не указаны')}.</p><p>Оценка: ${escapeHtml(item.score)} из 100. Это балл ранжирования, а не вероятность успеха.</p>${scoreFactors}</details>${state.searchId?`<div class="selection-actions"><button type="button" class="secondary-button" data-select-contractor="${escapeHtml(item.id)}">Интересен этот подрядчик</button><span class="selection-feedback" role="status"></span></div>`:''}</article>`;
}
function renderAudit(data){
  const exclusions=Object.entries(data.exclusions||{}).filter(([,count])=>count);
  return `<details class="audit"><summary>Как прошёл отбор</summary><div class="audit-grid"><div><h5>Этапы проверки</h5>${(data.pipeline||[]).map(row=>`<div class="pipeline-row"><span>${escapeHtml(row.stage)}</span><strong>${escapeHtml(row.remaining)}</strong></div>`).join('')}</div><div><h5>Причины исключения</h5>${exclusions.length?exclusions.map(([name,count])=>`<div class="exclusion-row"><span>${escapeHtml(name)}</span><strong>${count}</strong></div>`).join(''):'<p>Дополнительных исключений нет.</p>'}<p class="footnote">Один профиль может не пройти несколько условий.</p></div></div></details>`;
}
function renderError(message){
  state.searchId=null;
  state.hasResults=false;$('#emptyState').hidden=true;$('#result').hidden=false;$('#resultCount').textContent='0 / 3';
  $('#result').innerHTML=`<div class="outcome warning" role="alert"><span class="outcome-icon" aria-hidden="true">!</span><div><h4>Не удалось выполнить подбор</h4><p>${escapeHtml(message)}</p></div></div>`;
}
async function loadMeta(){
  if(location.protocol==='file:')throw new Error('Этому сайту нужен сервер для безопасной работы с ИИ. Откройте «Запустить SmartMatch.cmd» в папке проекта, затем http://127.0.0.1:8000.');
  state.meta=await request('/api/meta');
  fillSelect('#city',state.meta.cities,'Выберите город');fillSelect('#category',state.meta.categories,'Кого ищем?');fillSelect('#eventFormat',state.meta.event_formats,'Выберите формат');fillSelect('#language',state.meta.languages,'Любой');
  $('#eventDate').min=state.meta.calendar.min;$('#eventDate').max=state.meta.calendar.max;
  $('#catalogCount').textContent=state.meta.contractors+' профилей в выборке';
  $('#qualityNumber').innerHTML=state.meta.contractors+'<span>/'+(state.meta.contractors+state.meta.quarantined_count)+'</span>';
  $('#provenanceNote').textContent=`${state.meta.contractors-state.meta.synthetic_count} исходных и ${state.meta.synthetic_count} синтетических профилей. `;
  const ai=state.meta.ai||{};$('#useAI').disabled=!ai.configured;$('#useAI').checked=!!ai.configured;
  $('#storageStatus').textContent=state.meta.storage?.enabled?'Описание, условия, результаты и отмеченные кандидаты сохраняются в базе этого сервера. Не указывайте в описании контакты и личные данные.':'Сохранение истории недоступно.';
  const provider={openai:'OpenAI',gemini:'Gemini',compatible:'ИИ'}[ai.provider]||'ИИ';
  $('#aiStatus').textContent=ai.configured?provider+' настроен на сервере. ИИ анализирует описание и сравнивает подходящих кандидатов.':'OpenAI пока не подключён. Доступны локальный разбор и поиск по словам.';
  setBusy(false);
}
$('#searchForm').addEventListener('submit',submit);
$('#parseButton').addEventListener('click',onParse);
$('#description').addEventListener('input',()=>{state.briefDirty=true;$('#parseState').textContent='';});
function validateBudgetRange(){
  const low=Number($('#minBudget').value),high=Number($('#budget').value);
  $('#minBudget').setCustomValidity(high>0&&low>high?'Нижняя граница должна быть не больше максимального бюджета.':'');
}
function formChanged(event){state.formRevision++;const key=Object.keys(fields).find(key=>fields[key]===event.target.id);if(key)state.manualFields.add(key);validateBudgetRange();markStale();}
$('#searchForm').addEventListener('input',formChanged);
$('#searchForm').addEventListener('change',formChanged);
$('#resetButton').addEventListener('click',()=>{$('#searchForm').reset();applyQuery({});validateBudgetRange();$('#description').value='';$('#useAI').checked=!!state.meta?.ai?.configured;state.briefDirty=false;state.hasResults=false;state.searchId=null;state.manualFields.clear();state.formRevision++;notice('');$('#parseState').textContent='';$('#result').hidden=true;$('#result').replaceChildren();$('#emptyState').hidden=false;$('#resultCount').textContent='0 / 3';$('#description').focus();});
document.querySelectorAll('[data-example]').forEach(button=>button.addEventListener('click',()=>applyExample(Number(button.dataset.example))));
$('#demoButton').addEventListener('click',async()=>{applyExample(0);await submit(null,true);});
$('#result').addEventListener('click',async event=>{
  const button=event.target.closest('[data-select-contractor]');
  if(!button||button.disabled||!state.searchId)return;
  const searchId=state.searchId;
  button.disabled=true;
  const status=button.nextElementSibling;
  status.textContent='Сохраняем…';
  try{
    await request('/api/selection',{search_id:searchId,contractor_id:button.dataset.selectContractor});
    button.textContent='Отмечен ✓';
    status.textContent='Интерес сохранён. Это не бронирование.';
  }catch(error){
    status.textContent=error.message;
    button.disabled=state.searchId!==searchId;
  }
});
loadMeta().catch(error=>{renderError(error.message);$('#catalogCount').textContent='Каталог недоступен';$('#aiStatus').textContent='Нет соединения с сервером';setBusy(false);});
