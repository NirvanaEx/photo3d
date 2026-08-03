// Навигация, главная страница и корзина.
//
// Лежит отдельно от app.js намеренно. app.js занят вьюером - камерой, сеткой
// пола, турнтейблом; здесь - распоряжение библиотекой моделей. Разделение
// не только по смыслу: над вьюером идёт работа параллельно, и два файла
// правятся, не задевая друг друга.
//
// Всё завёрнуто в IIFE, поэтому имена ($, fmtBytes и прочие) не спорят
// с одноимёнными в app.js. Наружу не торчит ничего.
//
// Состояние приходит одним куском из app.js событием photo3d:state -
// второе соединение SSE стоило бы серверу отдельного обхода папок по drvfs.
(() => {
"use strict";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtBytes(n) {
  if (!n) return "—";
  const u = ["Б", "КБ", "МБ", "ГБ"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${i === 0 ? n : n.toFixed(1)} ${u[i]}`;
}
const fmtNum = (n) => (typeof n === "number" ? n.toLocaleString("ru-RU") : "—");
function fmtAgo(ts) {
  if (!ts) return "—";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return `${Math.round(s)} с назад`;
  if (s < 3600) return `${Math.round(s / 60)} мин назад`;
  if (s < 86400) return `${Math.round(s / 3600)} ч назад`;
  return `${Math.round(s / 86400)} дн назад`;
}

// --------------------------------------------------------------- состояние

const nav = {
  models: [],
  trash: [],
  route: { name: "home", id: null },
  q: "",
  engine: "",
  // Отбор по игре: "" — все, "in" — стоит хотя бы в одной сцене, "out" —
  // ни в одной. Ось отдельная от движка нарочно: движок это чем сделано,
  // а игра — дошло ли до дела, и складывать их в один ряд фишек значило бы
  // сделать невозможным «trellis2, которые ещё не в сцене».
  game: "",
  sort: "new",
  sel: new Set(),
  jobs: [],
  ready: false,
  // Чей ракурс сейчас во вьюере. Держим сами, а не подсматриваем в app.js:
  // там это `const state`, а объявленный так const в область window не
  // попадает - `window.state` всегда undefined. Ошибка была тихой, потому
  // что `undefined !== id` выглядит как «выбрано другое» и всё почти
  // работало.
  selected: null,
};

const byId = (id) => nav.models.find((m) => m.id === id);
const nameOf = (m) => (m && (m.title || m.id)) || "—";

// ------------------------------------------------------------------ разделы

// Реестр. Добавить раздел - дописать сюда одну запись: пункт в панели,
// маршрут и показ секции возьмутся отсюда сами. Ради этого он и заведён -
// «на будущее» означает, что следующий раздел не должен требовать правок
// в разметке, роутере и обработчиках разом.
const SECTIONS = [
  {
    id: "home",
    // Значок — готовая строка <svg> из icons.js. Раньше здесь стоял
    // юникод-глиф, и ряд разделов не выстраивался: у ▦, ◈, ＋ и ⌫ разная
    // ширина и разная базовая линия, потому что каждый приходит из своего
    // системного шрифта.
    icon: icon("library"),
    label: "Главная",
    hash: "#/",
    view: "view-home",
    crumbs: () => "Библиотека моделей",
    badge: () => nav.models.length,
    render: renderHome,
  },
  {
    id: "viewer",
    icon: icon("cube"),
    label: "Просмотр",
    hash: "#/m/",
    view: "view-viewer",
    crumbs: () => {
      const m = byId(nav.route.id);
      return m ? `Просмотр · ${esc(nameOf(m))}` : "Просмотр";
    },
    render: renderViewerRoute,
  },
  {
    id: "create",
    icon: icon("plus"),
    label: "Создать",
    hash: "#/new",
    view: "view-create",
    crumbs: () => "Создать модель",
    // Значок считает то, что сейчас в работе, а не все задания подряд:
    // цифра рядом с пунктом должна означать «идёт прямо сейчас».
    badge: () => nav.jobs.filter(
      (j) => j.state === "queued" || j.state === "running").length,
    // Отрисовка живёт в create.js: там же загрузка, разбор кадра и очередь.
    // Здесь только запись в реестре - ради этого он и заведён.
    render: () => window.photo3dCreate && window.photo3dCreate.render(),
  },
  {
    id: "trash",
    icon: icon("trash"),
    label: "Корзина",
    hash: "#/trash",
    view: "view-trash",
    crumbs: () => "Корзина",
    badge: () => nav.trash.length,
    render: renderTrash,
  },
];

const sectionOf = (name) => SECTIONS.find((s) => s.id === name) || SECTIONS[0];

// ------------------------------------------------------------------- роутер

function parseHash() {
  const h = location.hash || "#/";
  const m = h.match(/^#\/m\/([a-z0-9_]+)/i);
  if (m) return { name: "viewer", id: m[1] };
  if (h.startsWith("#/trash")) return { name: "trash", id: null };
  if (h.startsWith("#/new")) return { name: "create", id: null };
  return { name: "home", id: null };
}

function go(hash) {
  if (location.hash === hash) applyRoute();
  else location.hash = hash;
}

function applyRoute() {
  nav.route = parseHash();
  const sec = sectionOf(nav.route.name);

  for (const s of SECTIONS) $(s.view).hidden = s.id !== sec.id;
  $("crumbs").innerHTML = sec.crumbs();

  // «Следить за новыми» имеет смысл только там, где есть что открывать
  // само собой. На главной и в корзине переключатель только мешает.
  $("follow-wrap").hidden = sec.id !== "viewer";

  renderNav();
  sec.render();
}

// ------------------------------------------------------------------- панель

function renderNav() {
  const box = $("nav");
  box.innerHTML = "";
  for (const s of SECTIONS) {
    const n = nav.route.name === s.id;
    const b = el("button", "nav-item" + (n ? " active" : ""));
    const count = s.badge ? s.badge() : null;
    b.innerHTML =
      `<span class="nav-icon">${s.icon}</span>` +
      `<span class="nav-label">${esc(s.label)}</span>` +
      (count ? `<span class="nav-badge">${count}</span>` : "");
    b.onclick = () => {
      // У просмотра нет своего адреса без модели: открываем выбранную,
      // а если ни одной ещё не трогали - первую в списке.
      if (s.id === "viewer") {
        const id = nav.route.id || nav.selected || nav.models[0]?.id;
        if (!id) { toast("Моделей пока нет", "warn"); return; }
        go("#/m/" + id);
      } else {
        go(s.hash);
      }
    };
    box.appendChild(b);
  }

  const total = nav.models.reduce((a, m) => a + (m.size || 0), 0);
  $("stat-count").textContent = nav.models.length || "—";
  $("stat-size").textContent = fmtBytes(total);
}

// -------------------------------------------------------------------- сеть

// Свой заголовок обязателен: сервер отклоняет изменяющие запросы без него,
// см. SameOriginOnly в web/app.py.
async function api(path, body) {
  let r;
  try {
    r = await fetch(path, {
      method: "POST",
      headers: { "X-Photo3D": "1", "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    toast("Сервер не отвечает", "bad");
    return null;
  }
  let data = null;
  try { data = await r.json(); } catch { /* пустой ответ тоже бывает */ }
  if (!r.ok || (data && data.ok === false)) {
    // Показываем причину и подсказку целиком: молчаливый отказ отправляет
    // искать поломку не туда.
    const why = (data && data.error) || `ошибка ${r.status}`;
    const hint = data && data.hint ? ` — ${data.hint}` : "";
    toast(why + hint, "bad", 7000);
    return null;
  }
  return data || { ok: true };
}

// Обновиться немедленно, не дожидаясь опроса SSE: своё же действие должно
// быть видно сразу, иначе кажется, что кнопка не сработала.
async function refresh() {
  try {
    const d = await (await fetch("/api/models")).json();
    onState(d);
  } catch { /* SSE догонит */ }
}

// ------------------------------------------------------------- уведомления

function toast(text, kind = "ok", ms = 3500) {
  const t = el("div", "toast " + kind, esc(text));
  $("toasts").appendChild(t);
  setTimeout(() => {
    t.classList.add("out");
    setTimeout(() => t.remove(), 250);
  }, ms);
}

// --------------------------------------------------------------- диалоги

let modalClose = null;

function modal({ title, body, ok = "ок", cancel = "отмена", danger = false,
                 onShow = null }) {
  return new Promise((resolve) => {
    $("modal-title").textContent = title;
    $("modal-body").innerHTML = body;
    $("modal-ok").textContent = ok;
    $("modal-ok").className = "btn " + (danger ? "danger" : "primary");
    $("modal-cancel").textContent = cancel;
    $("modal-cancel").hidden = !cancel;
    $("modal").hidden = false;

    const done = (v) => {
      $("modal").hidden = true;
      modalClose = null;
      resolve(v);
    };
    modalClose = () => done(null);
    $("modal-ok").onclick = () => done(onShow ? onShow.get() : true);
    $("modal-cancel").onclick = () => done(null);
    if (onShow && onShow.init) onShow.init();
  });
}

// Клавиатуру диалога гасим здесь, до document: app.js слушает документ и
// вешает на одиночные буквы действия вьюера (f - полный экран). Без этого
// «f» в поле имени уводило бы страницу в полный экран.
$("modal").addEventListener("keydown", (e) => {
  e.stopPropagation();
  if (e.key === "Escape") { e.preventDefault(); modalClose && modalClose(); }
  if (e.key === "Enter" && e.target.tagName !== "TEXTAREA") {
    e.preventDefault();
    $("modal-ok").click();
  }
});
$("modal").addEventListener("mousedown", (e) => {
  if (e.target.id === "modal") modalClose && modalClose();
});

// ------------------------------------------------------------------ действия

function warnings(m) {
  const w = [];
  if (m.fresh) {
    w.push('<div class="warn-line">Модель менялась меньше пятнадцати минут ' +
           'назад — по ней может прямо сейчас идти работа.</div>');
  }
  if (m.children && m.children.length) {
    w.push('<div class="warn-line">На неё опираются производные: ' +
           m.children.map((c) => `<code>${esc(c)}</code>`).join(", ") +
           '. Они останутся, но без исходника.</div>');
  }
  return w.join("");
}

async function doDelete(ids) {
  const list = ids.map(byId).filter(Boolean);
  if (!list.length) return;
  const size = list.reduce((a, m) => a + (m.size || 0), 0);

  const rows = list.map((m) =>
    `<li><code>${esc(m.id)}</code> ${m.title ? esc(m.title) + " · " : ""}` +
    `${fmtBytes(m.size)}</li>`).join("");

  const ok = await modal({
    title: list.length === 1 ? `Удалить ${nameOf(list[0])}?` : `Удалить ${list.length} модели?`,
    danger: true,
    ok: "удалить",
    body:
      `<ul class="modal-list">${rows}</ul>` +
      `<div class="modal-note">Освободится ${fmtBytes(size)}. ` +
      `Модели уедут в корзину, откуда их можно вернуть.</div>` +
      list.map(warnings).join(""),
  });
  if (!ok) return;

  let done = 0;
  for (const m of list) {
    const r = await api(`/api/models/${m.id}/delete`);
    if (r) done++;
  }
  nav.sel.clear();
  await refresh();
  if (done) toast(done === 1 ? `${list[0].id} — в корзине` : `В корзину: ${done}`);
}

async function doRename(m) {
  const value = m.title || "";
  await modal({
    title: `Имя для ${m.id}`,
    ok: "сохранить",
    body:
      `<input class="modal-input" id="rename-input" maxlength="80" ` +
      `placeholder="например: девушка, бюст, вариант с волосами" ` +
      `value="${esc(value)}">` +
      `<div class="modal-note">Имя видно только здесь. Оно пишется в ui.json ` +
      `рядом с моделью и не трогает meta.json, который ведёт генератор.</div>`,
    onShow: {
      init: () => { const i = $("rename-input"); i.focus(); i.select(); },
      get: () => $("rename-input").value,
    },
  }).then(async (v) => {
    if (v === null) return;
    const r = await api(`/api/models/${m.id}/ui`, { title: v });
    if (r) { await refresh(); toast(v ? `Теперь это «${v}»` : "Имя снято"); }
  });
}

async function toggleStar(m) {
  const r = await api(`/api/models/${m.id}/ui`, { star: !m.star });
  if (r) refresh();
}

// «Переделать»: собираем готовый текст для Клода.
//
// Веб намеренно не запускает генерацию сам - он отдельный процесс, который
// можно ронять и перезапускать, и генерация этого не замечает. Стоит ему
// начать управлять пайплайном, и падение вкладки станет падением работы.
// Поэтому кнопка готовит вызов, а запускает его агент.
function redoCommand(m) {
  const seed = Math.floor(Math.random() * 100000);
  const e = m.engine || "";

  if (e.startsWith("trellis") || e === "stub") {
    return `photo_to_3d(image="${m.origin || "имя_файла.png"}", seed=${seed})`;
  }
  if (e === "sculpt-prep") {
    const faces = (String(m.mode).match(/\d+/) || ["5000"])[0];
    return `prepare_for_sculpting(model_id="${m.parents[0] || "last"}", ` +
           `target_faces=${faces})`;
  }
  if (e === "smooth") return `smooth_model(model_id="${m.parents[0] || m.id}")`;
  if (e === "paint") return `paint_model(model_id="${m.parents[0] || m.id}")`;

  // Пересадка головы и всё, чему нет отдельного инструмента: просьба словами.
  // Так честнее, чем выдумывать несуществующий вызов.
  return `Переделай ${m.id} заново — было: ${m.mode || m.origin || "то же самое"}`;
}

async function doRedo(m) {
  const cmd = redoCommand(m);
  const known = m.seed != null && m.seed !== 0
    ? `<div class="modal-note">Прошлый seed — <code>${esc(m.seed)}</code>. ` +
      `Здесь подставлен новый: тот же дал бы тот же результат.</div>`
    : "";
  await modal({
    title: `Переделать ${nameOf(m)}`,
    ok: "скопировать",
    body:
      `<div class="modal-note">Генерацию запускает агент, а не эта страница: ` +
      `веб держится в стороне от пайплайна, чтобы его можно было ронять и ` +
      `перезапускать посреди работы. Скопируй и вставь Клоду в чат.</div>` +
      `<textarea class="modal-input mono" id="redo-text" rows="3">${esc(cmd)}</textarea>` +
      known,
    onShow: {
      init: () => { const t = $("redo-text"); t.focus(); t.select(); },
      get: () => $("redo-text").value,
    },
  }).then(async (text) => {
    if (text === null) return;
    try {
      await navigator.clipboard.writeText(text);
      toast("Скопировано — вставь Клоду в чат");
    } catch {
      // Буфер может быть недоступен; текст всё равно виден и выделен.
      toast("Скопировать не вышло — выдели текст и нажми Ctrl+C", "warn", 6000);
    }
  });
}

async function doRestore(m) {
  const r = await api(`/api/trash/${m.id}/restore`);
  if (r) { await refresh(); toast(`${m.id} вернулась в библиотеку`); }
}

async function doPurge(m) {
  const ok = await modal({
    title: `Стереть ${m.id} насовсем?`,
    danger: true,
    ok: "стереть",
    body: `<div class="modal-note">Освободится ${fmtBytes(m.size)}. ` +
          `Вернуть будет нельзя — только сгенерировать заново.</div>`,
  });
  if (!ok) return;
  const r = await api(`/api/trash/${m.id}/purge`);
  if (r) { await refresh(); toast(`${m.id} стёрта`); }
}

async function doPurgeAll() {
  const size = nav.trash.reduce((a, m) => a + (m.size || 0), 0);
  const ok = await modal({
    title: `Очистить корзину?`,
    danger: true,
    ok: "очистить",
    body: `<div class="modal-note">В корзине ${nav.trash.length} ` +
          `${plural(nav.trash.length, "модель", "модели", "моделей")} ` +
          `на ${fmtBytes(size)}. Вернуть будет нельзя.</div>`,
  });
  if (!ok) return;
  const r = await api("/api/trash/purge");
  if (r) { await refresh(); toast(`Стёрто: ${r.purged}`); }
}

function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

// -------------------------------------------------------------- главная

function engineList() {
  const counts = new Map();
  for (const m of nav.models) {
    const e = m.engine || "без движка";
    counts.set(e, (counts.get(e) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

function visibleModels() {
  const q = nav.q.trim().toLowerCase();
  let list = nav.models.filter((m) => {
    if (nav.engine && (m.engine || "без движка") !== nav.engine) return false;
    if (nav.game === "in" && !inScene(m)) return false;
    if (nav.game === "out" && inScene(m)) return false;
    if (!q) return true;
    return [m.id, m.title, m.origin, m.engine, m.mode]
      .some((v) => String(v ?? "").toLowerCase().includes(q));
  });

  const by = {
    new: (a, b) => b.updated - a.updated,
    old: (a, b) => a.updated - b.updated,
    big: (a, b) => b.size - a.size,
    faces: (a, b) => (b.faces || 0) - (a.faces || 0),
    name: (a, b) => nameOf(a).localeCompare(nameOf(b), "ru"),
  }[nav.sort];

  // Отмеченные звёздочкой всегда сверху: их и отмечают, чтобы не искать.
  return list.sort((a, b) => (b.star - a.star) || by(a, b));
}

function renderTiles() {
  const total = nav.models.reduce((a, m) => a + (m.size || 0), 0);
  const trashSize = nav.trash.reduce((a, m) => a + (m.size || 0), 0);
  const engines = engineList();
  const starred = nav.models.filter((m) => m.star).length;

  const tile = (label, value, sub) =>
    `<div class="tile"><div class="tile-v">${value}</div>` +
    `<div class="tile-k">${label}</div>` +
    (sub ? `<div class="tile-s">${sub}</div>` : "") + `</div>`;

  $("tiles").innerHTML =
    tile("моделей", nav.models.length,
         starred ? `${starred} отмечено` : "") +
    tile("на диске", fmtBytes(total),
         engines.map(([e, n]) => `${esc(e)} ${n}`).join(" · ")) +
    tile("в корзине", nav.trash.length, fmtBytes(trashSize));
}

function renderChips() {
  const box = $("engine-chips");
  box.innerHTML = "";
  const mk = (label, value, n) => {
    const c = el("button", "chip" + (nav.engine === value ? " on" : ""),
                 `${esc(label)}${n != null ? ` <b>${n}</b>` : ""}`);
    c.onclick = () => { nav.engine = value; renderHome(); };
    box.appendChild(c);
  };
  mk("все", "", nav.models.length);
  for (const [e, n] of engineList()) mk(e, e, n);
}

// Отбор по игре. Прячется целиком, когда в игру не уехало ничего: полоса
// с тремя кнопками, из которых две всегда дают пусто, только сбивает с
// толку - то же правило, по которому прячется полоса действий над выбранным.
function renderGameFilter() {
  const box = $("game-filter");
  const total = nav.models.length;
  const inN = nav.models.filter(inScene).length;
  const known = nav.models.some((m) => m.game);
  box.hidden = !known;
  if (!known) { nav.game = ""; return; }

  box.innerHTML = "";
  const opts = [
    ["", "все", "Вся библиотека", total],
    ["in", "в игре", "Стоит хотя бы в одной сцене Godot", inN],
    ["out", "не в игре", "Ни в одной сцене — считая импортированные и забытые",
     total - inN],
  ];
  for (const [val, label, title, n] of opts) {
    const b = el("button", nav.game === val ? "active" : "",
                 `${esc(label)} <b>${n}</b>`);
    b.title = title;
    b.onclick = () => { nav.game = val; renderHome(); };
    box.appendChild(b);
  }
}

// ------------------------------------------------------------ связь с игрой

// Поле game приходит с сервера (web/game_link.py) и есть только у тех
// моделей, чей GLB уехал в game/assets. Различаются два состояния, и это
// не педантизм: «импортирована» и «стоит в сцене» — разные ответы на вопрос
// «сделано ли с ней что-нибудь». Модель, доехавшую до проекта и забытую,
// иначе не отличить от работающей.
const inScene = (m) => !!(m.game && m.game.scenes.length);

function gameMark(m) {
  if (!m.game) return "";
  const where = inScene(m)
    ? "в сцене: " + m.game.scenes.map((s) => s.title).join(", ")
    : "импортирована в игру, но ни в одной сцене не стоит";
  return `<span class="ggame${inScene(m) ? "" : " idle"}" title="${esc(where)}">` +
         icon("scene", "icon-sm") + `</span>`;
}

function gameLine(m) {
  if (!m.game) return "";
  if (!inScene(m)) return `<div class="gline game idle">импортирована, но не в сцене</div>`;
  return `<div class="gline game">${icon("scene", "icon-sm")}` +
         esc(m.game.scenes.map((s) => s.title).join(" · ")) + `</div>`;
}

function card(m, { trashed = false } = {}) {
  const c = el("div", "gcard" + (nav.sel.has(m.id) ? " picked" : "") +
                      (m.star ? " starred" : ""));

  const base = trashed ? "trash-files" : "files";
  const thumb = m.views.length
    ? `<img loading="lazy" src="/${base}/${m.id}/views/${m.views[0]}?v=${m.updated}" alt="">`
    : `<div class="no-thumb">${icon("cube", "icon-xl")}</div>`;

  const lineage = [];
  if (m.parents && m.parents.length) {
    lineage.push(`из ${m.parents.map((p) => `<code>${esc(p)}</code>`).join(" + ")}`);
  }
  if (m.children && m.children.length) {
    lineage.push(`${m.children.length} ` +
      plural(m.children.length, "производная", "производные", "производных"));
  }

  c.innerHTML =
    `<div class="gthumb">${thumb}` +
      (trashed ? "" : `<label class="pick"><input type="checkbox" ${
        nav.sel.has(m.id) ? "checked" : ""}></label>`) +
      (m.engine ? `<span class="gbadge">${esc(m.engine)}</span>` : "") +
      (!trashed ? gameMark(m) : "") +
      (m.star && !trashed ? `<span class="gstar">${icon("star", "icon-sm")}</span>` : "") +
    `</div>` +
    `<div class="gbody">` +
      `<div class="gname" title="${esc(m.id)}">${esc(nameOf(m))}</div>` +
      `<div class="gsub">${fmtNum(m.faces)} полиг. · ${fmtBytes(m.size)}</div>` +
      `<div class="gsub dim">${trashed
        ? "удалена " + fmtAgo(m.deleted_at)
        : fmtAgo(m.updated)}${m.fresh && !trashed ? ' <span class="hot">в работе</span>' : ""}</div>` +
      (!trashed ? gameLine(m) : "") +
      (lineage.length ? `<div class="gline">${lineage.join(" · ")}</div>` : "") +
    `</div>` +
    `<div class="gacts"></div>`;

  const acts = c.querySelector(".gacts");
  const btn = (label, title, fn, cls = "") => {
    const b = el("button", "gact " + cls, label);
    b.title = title;
    b.onclick = (e) => { e.stopPropagation(); fn(); };
    acts.appendChild(b);
  };

  // Со значком идут только действия, у которых он однозначен: звезда,
  // переименование, повтор, удаление. «Открыть» остаётся словом — это
  // главное действие карточки, и читаться оно должно без расшифровки
  // картинки.
  const ico = (name) => icon(name, "icon-sm");

  if (trashed) {
    btn(ico("restore") + "вернуть", "Вернуть в библиотеку", () => doRestore(m));
    btn(ico("close") + "стереть", "Удалить окончательно", () => doPurge(m), "danger");
  } else {
    btn("открыть", "Открыть в просмотре", () => go("#/m/" + m.id));
    btn(ico("star"), m.star ? "Снять отметку" : "Отметить",
        () => toggleStar(m), "icon" + (m.star ? " on" : ""));
    btn(ico("rename"), "Переименовать", () => doRename(m), "icon");
    btn(ico("redo"), "Собрать команду для повторной генерации", () => doRedo(m), "icon");
    btn(ico("trash"), "Убрать в корзину", () => doDelete([m.id]), "icon danger");
  }

  if (!trashed) {
    c.querySelector(".pick input").onclick = (e) => {
      e.stopPropagation();
      if (e.target.checked) nav.sel.add(m.id); else nav.sel.delete(m.id);
      renderHome();
    };
    c.onclick = () => go("#/m/" + m.id);
  }
  return c;
}

function renderHome() {
  renderTiles();
  renderChips();
  renderGameFilter();
  $("q").value = nav.q;
  $("sort").value = nav.sort;

  const list = visibleModels();
  const box = $("gallery");
  box.innerHTML = "";
  for (const m of list) box.appendChild(card(m));

  const empty = $("home-empty");
  if (!nav.models.length) {
    empty.hidden = false;
    empty.innerHTML = nav.ready
      ? "Пока пусто.<br>Сгенерируй модель — она появится здесь сама."
      : "Загрузка…";
  } else if (!list.length) {
    empty.hidden = false;
    empty.innerHTML = "Ничего не нашлось.<br>Попробуй другой запрос или сними фильтр.";
  } else {
    empty.hidden = true;
  }

  const n = nav.sel.size;
  $("bulk").hidden = !n;
  if (n) {
    const size = [...nav.sel].map(byId).filter(Boolean)
      .reduce((a, m) => a + (m.size || 0), 0);
    $("bulk-text").innerHTML =
      `Выбрано ${n} ${plural(n, "модель", "модели", "моделей")} · ${fmtBytes(size)}`;
  }
  renderNav();
}

// -------------------------------------------------------------- корзина

function renderTrash() {
  const size = nav.trash.reduce((a, m) => a + (m.size || 0), 0);
  $("trash-sub").textContent = nav.trash.length
    ? `${nav.trash.length} ${plural(nav.trash.length, "модель", "модели", "моделей")} · ${fmtBytes(size)}`
    : "пусто";
  $("purge-all").hidden = !nav.trash.length;

  const box = $("trash-grid");
  box.innerHTML = "";
  for (const m of nav.trash) box.appendChild(card(m, { trashed: true }));
  $("trash-empty").hidden = nav.trash.length > 0;
  renderNav();
}

// -------------------------------------------------------------- просмотр

function renderViewerRoute() {
  const id = nav.route.id;
  const m = byId(id);
  if (!m) {
    // Модель могли удалить из другой вкладки. Молча показывать пустой вьюер
    // нельзя - это выглядит как поломка.
    if (nav.ready && id) {
      toast(`Модель ${id} не найдена — возможно, удалена`, "warn");
      go("#/");
    }
    return;
  }
  if (nav.selected !== id) window.select(id);

  // Вьюер всё время, пока раздел был скрыт, не знал своего размера.
  // Пинок нужен, чтобы сетка пола и камера пересчитались под фактическую
  // ширину: без него первый кадр после возврата приходит с прошлым аспектом.
  window.dispatchEvent(new Event("resize"));

  renderPanelActions(m);
}

// Действия для открытой модели. Панель вьюера размечена в app.js, поэтому
// строку кнопок вставляем отсюда, а не правим ту разметку.
function renderPanelActions(m) {
  let bar = $("panel-actions");
  if (!bar) {
    bar = el("div", "panel-actions");
    bar.id = "panel-actions";
    $("panel").insertBefore(bar, $("panel").firstChild);
  }
  bar.innerHTML = "";
  const btn = (label, fn, cls = "") => {
    const b = el("button", "btn " + cls, label);
    b.onclick = fn;
    bar.appendChild(b);
  };
  const ico = (name) => icon(name, "icon-sm");
  btn(ico("star") + (m.star ? "отмечена" : "отметить"), () => toggleStar(m),
      m.star ? "starred" : "");
  btn(ico("rename") + "переименовать", () => doRename(m));
  btn(ico("redo") + "переделать", () => doRedo(m));
  btn(ico("trash") + "удалить", () => doDelete([m.id]), "danger");
  btn(ico("chevron-left") + "к списку", () => go("#/"));
}

// ------------------------------------------------------------- состояние

function onState(d) {
  nav.models = d.models || [];
  nav.trash = d.trash || [];
  nav.jobs = d.jobs || [];
  nav.ready = true;

  // Выбор чистим от исчезнувшего: иначе «удалить выбранные» считало бы
  // модели, которых уже нет.
  const alive = new Set(nav.models.map((m) => m.id));
  for (const id of [...nav.sel]) if (!alive.has(id)) nav.sel.delete(id);

  sectionOf(nav.route.name).render();
  renderNav();
}

// Выбрать модель можно и мимо навигации - щелчком в списке слева, который
// рисует app.js. Оборачиваем select, чтобы адрес шёл следом за выбором,
// откуда бы тот ни пришёл: иначе в заголовке осталась бы прошлая модель,
// а кнопки внизу правили бы не ту.
//
// Подмена работает потому, что select объявлен обычной функцией: такое
// объявление и свойство window - одна и та же ячейка. С `const` (как у
// state рядом) этот приём не сработал бы.
// Если app.js не загрузился, молчать нельзя: навигация будет работать, а
// просмотр - нет, и выглядеть это будет как «сломались модели».
if (typeof window.select !== "function") {
  toast("app.js не загрузился — просмотр моделей работать не будет", "bad", 20000);
}
const baseSelect = window.select || (() => {});
window.select = function (id) {
  baseSelect(id);
  if (nav.selected === id) return;
  nav.selected = id;
  if (nav.route.name === "viewer" && nav.route.id !== id) {
    // replaceState, а не hash: переключение моделей стрелками не должно
    // засорять историю - «назад» обязано уводить туда, откуда пришли.
    history.replaceState(null, "", "#/m/" + id);
    nav.route = parseHash();
    $("crumbs").innerHTML = sectionOf("viewer").crumbs();
    const m = byId(id);
    if (m) renderPanelActions(m);
    renderNav();
  }
};

window.addEventListener("photo3d:state", (e) => onState(e.detail));
window.addEventListener("hashchange", applyRoute);

// Сообщения и обновление для create.js. Он лежит отдельным файлом и в наши
// внутренности не лезет: просит событием, показываем мы. Двух систем
// всплывающих сообщений с разным видом в интерфейсе быть не должно.
window.addEventListener("photo3d:toast", (e) => {
  const d = e.detail || {};
  toast(d.text, d.kind, d.ms);
});
window.addEventListener("photo3d:refresh", () => refresh());

// «Следить за новыми» ведёт себя как раньше - открывает свежую модель, -
// но только когда мы и так в просмотре. Утаскивать с главной посреди
// разбора библиотеки было бы грубо.
let lastTop = null;
window.addEventListener("photo3d:state", () => {
  const top = nav.models[0]?.id;
  if (top && top !== lastTop && lastTop !== null &&
      $("follow").checked && nav.route.name === "viewer") {
    go("#/m/" + top);
  }
  lastTop = top ?? null;
});

$("q").addEventListener("input", (e) => { nav.q = e.target.value; renderHome(); });
$("sort").addEventListener("change", (e) => { nav.sort = e.target.value; renderHome(); });
$("bulk-none").onclick = () => { nav.sel.clear(); renderHome(); };
$("bulk-del").onclick = () => doDelete([...nav.sel]);
$("purge-all").onclick = doPurgeAll;

// Цифры 1..3 переключают разделы. Поле ввода и диалог не трогаем.
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.altKey || e.metaKey) return;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  if (!$("modal").hidden) return;
  const i = ["1", "2", "3"].indexOf(e.key);
  if (i >= 0 && SECTIONS[i]) {
    e.preventDefault();
    $("nav").children[i].click();
  }
});

applyRoute();

})();
