const $ = (selector) => document.querySelector(selector);
const state = { meta: null };

function fillSelect(id, values) {
  const select = $(id);
  select.innerHTML = values.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

function money(value) {
  return new Intl.NumberFormat("ru-RU").format(value) + " ₸";
}

async function loadMeta() {
  const response = await fetch("/api/meta");
  state.meta = await response.json();
  fillSelect("#city", state.meta.cities);
  fillSelect("#eventFormat", state.meta.event_formats);
  fillSelect("#category", state.meta.categories);
  $("#language").insertAdjacentHTML("beforeend", state.meta.languages.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join(""));
  $("#eventDate").min = state.meta.calendar.min;
  $("#eventDate").max = state.meta.calendar.max;
  $("#eventDate").value = "2026-10-15";
  $("#catalogCount").textContent = `${state.meta.contractors} профилей`;
  $("#qualityNumber").textContent = `${state.meta.contractors}/${state.meta.contractors + state.meta.quarantined_count}`;
  renderDemoCases();
  applyQuery(state.meta.demo_cases[0].query);
}

function renderDemoCases() {
  $("#demoCases").innerHTML = state.meta.demo_cases.map((item, index) => `
    <button class="demo-button" type="button" data-demo="${index}">
      <strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.description)}</span>
    </button>`).join("");
  document.querySelectorAll("[data-demo]").forEach(button => {
    button.addEventListener("click", () => {
      applyQuery(state.meta.demo_cases[Number(button.dataset.demo)].query);
      $("#searchForm").requestSubmit();
    });
  });
}

function applyQuery(query) {
  $("#city").value = query.city;
  $("#eventDate").value = query.event_date;
  $("#eventFormat").value = query.event_format;
  $("#category").value = query.category;
  $("#budget").value = query.budget_kzt;
  $("#language").value = query.language || "";
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
    language: $("#language").value || null,
    duration_hours: $("#duration").value ? Number($("#duration").value) : null,
    preferences: $("#preferences").value.trim(),
  };
}

async function submit(event) {
  event.preventDefault();
  const button = $(".primary");
  button.disabled = true;
  button.firstElementChild.textContent = "Проверяем условия";
  const started = performance.now();
  try {
    const response = await fetch("/api/recommend", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(queryFromForm()),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Не удалось выполнить запрос");
    $("#runtime").textContent = `${Math.round(performance.now() - started)} мс`;
    renderResult(data);
  } catch (error) {
    renderError(error.message);
  } finally {
    button.disabled = false;
    button.firstElementChild.textContent = "Подобрать подрядчиков";
  }
}

function renderResult(data) {
  $("#emptyState").hidden = true;
  $("#result").hidden = false;
  const tone = data.status === "success" ? "success" : data.status === "no_market" ? "neutral" : "warning";
  $("#result").innerHTML = `
    <div class="outcome ${tone}"><span class="outcome-dot"></span><div><h3>${escapeHtml(data.title)}</h3><p>${escapeHtml(data.message)}</p></div></div>
    ${data.results.length ? `<div class="cards">${data.results.map(renderCard).join("")}</div>` : ""}
    <div class="audit-grid">
      <div><h3>Путь через фильтры</h3><div class="pipeline">${data.pipeline.map(renderStage).join("")}</div></div>
      <div><h3>Почему отсеялись</h3>${renderExclusions(data)}</div>
    </div>`;
}

function renderCard(item, index) {
  const badges = [
    item.synthetic ? "Синтетический профиль" : "Исходный профиль",
    item.price_imputed ? "Цена восстановлена" : "Цена из профиля",
    item.city_imputed ? "Город восстановлен" : "Город из профиля",
  ];
  return `<article class="contractor-card">
    <div class="rank">${index + 1}</div>
    <div class="card-main">
      <div class="card-title"><div><p class="card-category">${escapeHtml(item.category)}</p><h3>${escapeHtml(item.name)}</h3><p class="card-id">${escapeHtml(item.id)} · ${escapeHtml(item.city)}</p></div><div class="score"><strong>${item.score}</strong><span>балла</span></div></div>
      <p class="explanation">${escapeHtml(item.explanation)}</p>
      <div class="facts"><span>${money(item.price_from_kzt)}</span><span>${escapeHtml(item.languages.join(", "))}</span><span>${item.max_hours == null ? "без лимита присутствия" : `до ${item.max_hours} ч`}</span></div>
      <div class="badges">${badges.map((value, i) => `<span class="badge ${i && value.includes("восстановлен") ? "badge-warn" : ""}">${escapeHtml(value)}</span>`).join("")}</div>
      <details><summary>Из чего сложился балл</summary><div class="factors">${Object.entries(item.score_factors).map(([name, value]) => `<div><span>${escapeHtml(name)}</span><meter min="0" max="100" value="${value}"></meter><strong>${value}</strong></div>`).join("")}</div></details>
    </div>
  </article>`;
}

function renderStage(stage, index, stages) {
  const previous = index ? stages[index - 1].remaining : stage.remaining;
  const removed = Math.max(0, previous - stage.remaining);
  return `<div class="pipeline-row"><span>${escapeHtml(stage.stage)}</span><span class="pipeline-rule"></span><strong>${stage.remaining}</strong>${removed ? `<small>−${removed}</small>` : ""}</div>`;
}

function renderExclusions(data) {
  const entries = Object.entries(data.exclusions || {}).filter(([, count]) => count);
  const quality = data.data_quality_excluded ? `<li><span>нет критических данных</span><strong>${data.data_quality_excluded}</strong></li>` : "";
  if (!entries.length && !quality) return `<p class="muted">На этом запросе дополнительных исключений нет.</p>`;
  return `<ul class="exclusion-list">${quality}${entries.map(([name, count]) => `<li><span>${escapeHtml(name)}</span><strong>${count}</strong></li>`).join("")}</ul><p class="footnote">Один профиль может нарушать несколько условий.</p>`;
}

function renderError(message) {
  $("#emptyState").hidden = true;
  $("#result").hidden = false;
  $("#result").innerHTML = `<div class="outcome error"><span class="outcome-dot"></span><div><h3>Запрос не выполнен</h3><p>${escapeHtml(message)}</p></div></div>`;
}

$("#searchForm").addEventListener("submit", submit);
loadMeta().catch(error => renderError(error.message));

