const $ = (selector) => document.querySelector(selector);
const state = { meta: null };

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

function fillSelect(id, values) {
  const select = $(id);
  select.innerHTML = values.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
}

function money(value) {
  return new Intl.NumberFormat("ru-RU").format(value) + " ₸";
}

function compactDate(value) {
  return new Intl.DateTimeFormat("ru-RU", {day: "2-digit", month: "2-digit"}).format(new Date(`${value}T00:00:00`));
}

async function loadMeta() {
  const response = await fetch("/api/meta");
  state.meta = await response.json();
  fillSelect("#city", state.meta.cities);
  fillSelect("#eventFormat", state.meta.event_formats);
  fillSelect("#category", state.meta.categories);
  fillSelect("#language", state.meta.languages);
  $("#eventDate").min = state.meta.calendar.min;
  $("#eventDate").max = state.meta.calendar.max;
  $("#catalogCount").textContent = `${state.meta.contractors} профилей`;
  $("#qualityNumber").textContent = `${state.meta.contractors}/${state.meta.contractors + state.meta.quarantined_count}`;
  applyQuery(state.meta.demo_cases[0].query);
  $("#searchForm").requestSubmit();
}

function applyQuery(query) {
  $("#city").value = query.city;
  $("#eventDate").value = query.event_date;
  $("#eventFormat").value = query.event_format;
  $("#category").value = query.category;
  $("#budget").value = query.budget_kzt;
  $("#budgetFrom").value = 0;
  $("#language").value = query.language || state.meta.languages[0];
  $("#duration").value = query.duration_hours || "";
  $("#preferences").value = query.preferences || "";
}

function queryFromForm() {
  return {
    city: $("#city").value,
    event_date: $("#eventDate").value,
    event_format: $("#eventFormat").value,
    category: $("#category").value,
    budget_kzt: Number($("#budget").value),
    language: $("#language").value,
    duration_hours: $("#duration").value ? Number($("#duration").value) : null,
    preferences: $("#preferences").value.trim(),
  };
}

async function submit(event) {
  event.preventDefault();
  const button = $(".primary");
  const original = button.innerHTML;
  button.disabled = true;
  button.textContent = "проверяем условия...";
  const started = performance.now();
  try {
    const response = await fetch("/api/recommend", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(queryFromForm()),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Не удалось выполнить запрос");
    renderResult(data, Math.round(performance.now() - started));
  } catch (error) {
    renderError(error.message);
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}

function renderResult(data, runtime) {
  $("#emptyState").hidden = true;
  $("#result").hidden = false;
  const tone = data.status === "success" ? "success" : data.status === "no_market" ? "neutral" : "warning";
  $("#result").innerHTML = `
    <div class="outcome ${tone}">
      <span class="outcome-dot"></span>
      <div><h2>${escapeHtml(data.title)}</h2><p>${escapeHtml(data.message)}</p></div>
      <span class="runtime">${runtime} мс</span>
    </div>
    ${data.results.length ? `<div class="cards">${data.results.map(renderCard).join("")}</div>` : ""}
    ${renderAudit(data)}`;
}

function renderCard(item, index) {
  const busyDates = item.busy_dates?.length ? item.busy_dates.slice(0, 5).map(compactDate).join(", ") : "нет";
  return `<article class="contractor-card">
    <div class="card-head">
      <div class="rank">${index + 1}</div>
      <div class="card-title">
        <h3>${escapeHtml(item.name)}</h3>
        <p class="category">${escapeHtml(item.category)}</p>
        <p class="facts"><span>${escapeHtml(item.city)}</span><span>${money(item.price_from_kzt)}</span></p>
      </div>
      <span class="card-code">${escapeHtml(item.id)}</span>
    </div>
    ${item.synthetic ? `<p class="synthetic">#synthetic</p>` : ""}
    <div class="profile-details">
      <dl>
        <div><dt>форматы:</dt><dd>${escapeHtml(item.event_formats.join(", "))}</dd></div>
        <div><dt>языки:</dt><dd>${escapeHtml(item.languages.join(", "))}</dd></div>
        <div><dt>занятые дни:</dt><dd>${escapeHtml(busyDates)}</dd></div>
        <div><dt>макс часов на площадке:</dt><dd>${item.max_hours == null ? "без ограничения" : `${item.max_hours} ч`}</dd></div>
      </dl>
      <div class="explanation">
        <span>почему этот кандидат?</span>
        <p>${escapeHtml(item.explanation)}</p>
      </div>
    </div>
  </article>`;
}

function renderAudit(data) {
  const entries = Object.entries(data.exclusions || {}).filter(([, count]) => count);
  return `<details class="audit">
    <summary>Показать путь через жёсткие фильтры</summary>
    <div class="audit-grid">
      <div><h4>Этапы проверки</h4><div class="pipeline">${data.pipeline.map(stage => `<div class="pipeline-row"><span>${escapeHtml(stage.stage)}</span><strong>${stage.remaining}</strong></div>`).join("")}</div></div>
      <div><h4>Почему отсеялись</h4>${entries.length ? `<ul class="exclusion-list">${entries.map(([name, count]) => `<li><span>${escapeHtml(name)}</span><strong>${count}</strong></li>`).join("")}</ul><p class="footnote">Причины могут пересекаться.</p>` : `<p class="muted">Дополнительных исключений нет.</p>`}</div>
    </div>
  </details>`;
}

function renderError(message) {
  $("#emptyState").hidden = true;
  $("#result").hidden = false;
  $("#result").innerHTML = `<div class="outcome warning"><span class="outcome-dot"></span><div><h2>Запрос не выполнен</h2><p>${escapeHtml(message)}</p></div></div>`;
}

$("#searchForm").addEventListener("submit", submit);
loadMeta().catch(error => renderError(error.message));

