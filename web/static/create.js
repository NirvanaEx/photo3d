// Раздел «Создать»: фото -> задание -> модель, руками человека.
//
// Отдельным файлом, а не куском nav.js, по той же причине, по какой nav.js
// отделён от app.js: над вьюером и прогулкой идёт работа параллельно, и файлы
// должны правиться, не задевая друг друга. Наружу отсюда торчит ровно одно
// имя - window.photo3dCreate, которое зовёт реестр разделов.
//
// Страница ничего не исполняет: она кладёт задание в очередь (POST /api/jobs),
// а считает воркер. Это то самое свойство, ради которого веб держали в
// стороне от пайплайна: вкладку можно закрыть посреди генерации.
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

const state = {
  photo: null,      // имя файла в data/input
  check: null,      // последний разбор кадра
  checking: false,
  sending: false,
  jobs: [],
  worker: {},
};

// Уведомления и диалоги живут в nav.js и в window не отдаются. Свои - через
// событие: nav.js его слушает и показывает. Дублировать всплывашку здесь
// значило бы завести вторую систему сообщений с другим видом.
const toast = (text, kind = "ok", ms) =>
  window.dispatchEvent(new CustomEvent("photo3d:toast",
    { detail: { text, kind, ms } }));

async function post(path, body) {
  let r;
  try {
    r = await fetch(path, {
      method: "POST",
      headers: { "X-Photo3D": "1", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    toast("Сервер не отвечает", "bad");
    return null;
  }
  let data = null;
  try { data = await r.json(); } catch { /* пустой ответ тоже бывает */ }
  if (!r.ok || (data && data.ok === false)) {
    const why = (data && data.error) || `ошибка ${r.status}`;
    const hint = data && data.hint ? ` — ${data.hint}` : "";
    toast(why + hint, "bad", 9000);
    return null;
  }
  return data || { ok: true };
}

// ------------------------------------------------------------------ загрузка

async function upload(files) {
  const fd = new FormData();
  let n = 0;
  for (const f of files) {
    // Отсеиваем на месте: отправить 300 МБ видео, чтобы получить отказ,
    // дороже, чем посмотреть на тип здесь.
    if (!/^image\//.test(f.type || "") && !/\.(jpe?g|png|webp)$/i.test(f.name)) {
      toast(`${f.name}: не картинка`, "warn");
      continue;
    }
    fd.append("file", f, f.name);
    n++;
  }
  if (!n) return;

  $("cr-drop").classList.add("busy");
  let data = null;
  try {
    const r = await fetch("/api/upload", {
      method: "POST", headers: { "X-Photo3D": "1" }, body: fd,
    });
    data = await r.json();
    if (!r.ok || data.ok === false) {
      toast((data.error || `ошибка ${r.status}`) +
            (data.hint ? ` — ${data.hint}` : ""), "bad", 9000);
      data = null;
    }
  } catch {
    toast("Не удалось загрузить файл", "bad");
  } finally {
    $("cr-drop").classList.remove("busy");
  }
  if (!data) return;

  for (const s of data.skipped || []) toast(s, "warn");
  const last = data.saved[data.saved.length - 1];
  pick(last.name);
  toast(`Принято: ${data.saved.map((s) => s.name).join(", ")}`);
}

function pick(name) {
  state.photo = name;
  state.check = null;
  render();
}

// -------------------------------------------------------------- разбор кадра

async function check() {
  if (!state.photo || state.checking) return;
  state.checking = true;
  render();
  const d = await post("/api/check", { name: state.photo });
  state.checking = false;
  state.check = d && d.ok ? d : null;
  render();
}

function measuresHtml(c) {
  const m = c.measures || {};
  const kadr = m["кадр"] || [];
  const sil = m["габарит_силуэта"] || [];
  const rows = [
    ["кадр", `${kadr[0]}×${kadr[1]}`],
    ["маска", m["источник_маски"]],
    ["предмет занимает", `${((m["доля_кадра"] || 0) * 100).toFixed(1)}% кадра`],
    ["силуэт", `${sil[0]}×${sil[1]} точек, рамка заполнена на ` +
               `${Math.round((m["заполнение_рамки"] || 0) * 100)}%`],
    ["мелкой фактуры", `${Math.round(m["фактура"] || 0)} ` +
                       `<span class="dim">(у удачных примеров 384…7251)</span>`],
  ];
  return rows.map(([k, v]) => `<div class="cr-row"><span>${esc(k)}</span>` +
                              `<b>${v == null ? "—" : v}</b></div>`).join("");
}

// ------------------------------------------------------------------ задание

async function send() {
  if (!state.photo || state.sending) return;
  state.sending = true;
  render();
  const d = await post("/api/jobs", {
    image: state.photo,
    mode: $("cr-mode").value,
    seed: Number($("cr-seed").value || 0),
  });
  state.sending = false;
  if (d && d.ok) {
    toast(`Задание ${d.job.id} поставлено — считает воркер`);
    window.dispatchEvent(new Event("photo3d:refresh"));
  }
  render();
}

async function cancel(id) {
  const d = await post(`/api/jobs/${id}/cancel`);
  if (d && d.ok) {
    toast(d.note || `Задание ${id} снято`, d.running ? "warn" : "ok", 7000);
    window.dispatchEvent(new Event("photo3d:refresh"));
  }
}

const STATES = {
  queued: ["ждёт", "wait"],
  running: ["считается", "run"],
  done: ["готово", "ok"],
  failed: ["ошибка", "bad"],
  cancelled: ["отменено", "off"],
};

function secs(t) { return Math.max(0, Date.now() / 1000 - (t || 0)); }

function jobCard(j) {
  const [word, kind] = STATES[j.state] || [j.state, "off"];
  const mid = j.model_id || (j.result && j.result.model_id) || "";
  const box = el("div", `cr-job ${kind}`);

  let when = "";
  if (j.state === "running") when = `идёт ${secs(j.started).toFixed(0)} с`;
  else if (j.state === "queued") when = `в очереди ${secs(j.created).toFixed(0)} с`;
  else if (j.finished) when = `${secs(j.finished).toFixed(0)} с назад`;

  box.innerHTML =
    `<div class="cr-job-head">` +
      `<span class="cr-badge ${kind}">${esc(word)}</span>` +
      `<b>${esc(j.title || j.kind)}</b>` +
      `<span class="dim">${esc(j.by === "human" ? "я" : "агент")}</span>` +
      `<span class="spacer"></span>` +
      `<span class="dim">${esc(when)}</span>` +
    `</div>` +
    `<div class="cr-job-stage">${esc(j.stage || "")}</div>`;

  if (j.state === "failed" && j.error) {
    // Причина и что делать - целиком. Обрезанная ошибка отправляет искать
    // поломку не туда, а третья часть здесь есть всегда (server/errors.py).
    box.appendChild(el("div", "cr-err",
      `${esc(j.error.reason || "")}` +
      (j.error.hint ? `<div class="dim">${esc(j.error.hint)}</div>` : "")));
  }

  const foot = el("div", "cr-job-foot");
  if (mid) {
    const b = el("button", "btn small", "открыть модель");
    b.onclick = () => { location.hash = "#/m/" + mid; };
    foot.appendChild(b);
  }
  if (j.state === "queued" || j.state === "running") {
    const b = el("button", "btn small danger",
                 j.state === "running" ? "снять" : "отменить");
    b.onclick = () => cancel(j.id);
    foot.appendChild(b);
  }
  if (foot.children.length) box.appendChild(foot);
  return box;
}

// -------------------------------------------------------------------- показ

function render() {
  if ($("view-create").hidden) return;

  // Выбранное фото
  const has = !!state.photo;
  $("cr-picked").hidden = !has;
  if (has) {
    $("cr-thumb").src = "/input/" + encodeURIComponent(state.photo);
    $("cr-name").textContent = state.photo;
  }
  $("cr-check").disabled = !has || state.checking;
  $("cr-check").textContent = state.checking ? "смотрю…" : "проверить кадр";
  $("cr-send").disabled = !has || state.sending;

  // Разбор кадра
  const c = state.check;
  $("cr-report").hidden = !c;
  if (c) {
    $("cr-silhouette").src = c.preview + "?v=" + Date.now();
    $("cr-measures").innerHTML = measuresHtml(c);
    const warns = c.warnings || [];
    $("cr-warns").innerHTML = warns.length
      ? `<div class="cr-warn-title">на что обратить внимание</div>` +
        warns.map((w) => `<div class="cr-warn">• ${esc(w)}</div>`).join("")
      : `<div class="dim">Замеры не возражают — решай по силуэту. ` +
        `Плоский предмет (стена, панно, вывеска) числами не ловится: ` +
        `он выйдет свёрнутым в бочку, и видно это только глазом.</div>`;
  }

  // Очередь
  const box = $("cr-queue");
  box.innerHTML = "";
  const list = state.jobs || [];
  if (!list.length) {
    box.appendChild(el("div", "empty", "Очередь пуста"));
  } else {
    for (const j of list) box.appendChild(jobCard(j));
  }

  const w = state.worker || {};
  const active = list.filter((j) => j.state === "queued" || j.state === "running");
  $("cr-worker").innerHTML = w.alive
    ? `<span class="dot ok"></span>исполнитель работает` +
      (w.engine ? ` <span class="dim">· движок ${esc(w.engine)}</span>` : "") +
      (active.length ? ` <span class="dim">· в работе ${active.length}</span>` : "")
    : `<span class="dot off"></span>исполнитель спит — ` +
      `<span class="dim">поднимется сам, как только появится задание</span>`;
}

// ------------------------------------------------------------------- запуск

function wire() {
  const drop = $("cr-drop");
  const input = $("cr-file");

  drop.onclick = () => input.click();
  input.onchange = () => { if (input.files.length) upload(input.files); input.value = ""; };

  // Перетаскивание. dragover обязателен с preventDefault - без него браузер
  // просто откроет файл вместо того, чтобы отдать его странице.
  for (const ev of ["dragenter", "dragover"]) {
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.add("over");
    });
  }
  for (const ev of ["dragleave", "drop"]) {
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.remove("over");
    });
  }
  drop.addEventListener("drop", (e) => {
    if (e.dataTransfer && e.dataTransfer.files.length) upload(e.dataTransfer.files);
  });

  // Файл можно и вставить из буфера: снимок экрана обычно там и оказывается,
  // а сохранять его на диск ради загрузки - лишний круг.
  window.addEventListener("paste", (e) => {
    if ($("view-create").hidden) return;
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) { e.preventDefault(); upload(files); }
  });

  $("cr-check").onclick = check;
  $("cr-send").onclick = send;
  $("cr-seed-rnd").onclick = () => {
    $("cr-seed").value = Math.floor(Math.random() * 100000);
  };
}

window.addEventListener("photo3d:state", (e) => {
  const d = e.detail || {};
  state.jobs = d.jobs || [];
  state.worker = d.worker || {};
  render();
});

// Пока задание идёт, время в карточке должно тикать само: состояние с
// сервера приходит по изменению файла, а «идёт 12 с» меняется каждую секунду
// и без всяких изменений на диске.
setInterval(() => {
  if ($("view-create").hidden) return;
  if (state.jobs.some((j) => j.state === "queued" || j.state === "running")) render();
}, 1000);

wire();

window.photo3dCreate = { render, pick };
})();
