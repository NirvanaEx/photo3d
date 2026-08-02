// Логика просмотра. Состояние моделей приходит целиком по SSE, локально
// хранится только выбор пользователя и положение камеры.

const $ = (id) => document.getElementById(id);
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

const state = {
  models: [],
  selectedId: null,
  known: new Set(),   // чтобы отличать новые модели от уже виденных
  fresh: new Set(),   // подсветка новинки, живёт по таймеру
  first: true,
  mode: "3d",
  fbTimer: null,
};

// Турнтейбл: вращение по заранее отрендеренным кадрам.
const spin = {
  frames: [], i: 0, scale: 1, px: 0, py: 0,
  dragging: false, panning: false, lastX: 0, lastY: 0, acc: 0,
};

// Подсветку нельзя выводить из known: генерация вызывает несколько
// обновлений подряд (мета, потом рендеры), и ко второму модель уже
// «известна» — вспышка гасла, не успев показаться.
function markFresh(ids) {
  if (!ids.length) return;
  ids.forEach((id) => state.fresh.add(id));
  setTimeout(() => {
    ids.forEach((id) => state.fresh.delete(id));
    renderList();
  }, 2500);
}

// --------------------------------------------------------------------- утилиты

function fmtBytes(n) {
  if (!n) return "—";
  const u = ["Б", "КБ", "МБ", "ГБ"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${i === 0 ? n : n.toFixed(1)} ${u[i]}`;
}

const fmtNum = (n) => (typeof n === "number" ? n.toLocaleString("ru-RU") : "—");

function fmtAgo(ts) {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return `${Math.round(s)} с назад`;
  if (s < 3600) return `${Math.round(s / 60)} мин назад`;
  if (s < 86400) return `${Math.round(s / 3600)} ч назад`;
  return `${Math.round(s / 86400)} дн назад`;
}

// Равномерная выборка: кадров полного оборота два десятка, в полосе
// столько миниатюр не нужно.
function sample(arr, n) {
  if (arr.length <= n) return arr.map((v, i) => [v, i]);
  const step = arr.length / n;
  return Array.from({ length: n }, (_, i) => {
    const idx = Math.round(i * step) % arr.length;
    return [arr[idx], idx];
  });
}

// --------------------------------------------------------------------- список

function renderList() {
  const list = $("list");
  const models = state.models;
  $("count").textContent = models.length || "—";
  $("empty").hidden = models.length > 0;

  list.innerHTML = "";
  for (const m of models) {
    const card = document.createElement("div");
    card.className = "card" + (m.id === state.selectedId ? " active" : "");
    if (state.fresh.has(m.id)) card.classList.add("fresh");

    const thumb = m.views.length
      ? `<img src="/files/${m.id}/views/${m.views[0]}?v=${m.updated}" alt="">`
      : `<div class="no-thumb">◇</div>`;
    const badge = m.engine
      ? `<span class="badge ${m.engine === "stub" ? "stub" : ""}">${m.engine}</span>`
      : "";

    card.innerHTML = `
      ${thumb}
      <div>
        <div class="card-id">${m.id}</div>
        <div class="card-sub">${badge}${fmtNum(m.faces)} полиг.</div>
        <div class="card-sub">${fmtAgo(m.updated)}</div>
      </div>`;
    card.onclick = () => select(m.id);
    list.appendChild(card);
  }
  for (const m of models) state.known.add(m.id);
  state.first = false;
}

// --------------------------------------------------------------------- деталь

function select(id) {
  state.selectedId = id;
  const m = state.models.find((x) => x.id === id);
  if (!m) return;

  spin.frames = m.views.map((v) => `/files/${m.id}/views/${v}?v=${m.updated}`);
  spin.frames.forEach((src) => { const im = new Image(); im.src = src; });
  resetSpin();
  setSpinFrame(0);

  const viewer = $("viewer");
  // Смена самой геометрии переставляет камеру вьюера, и точка, из которой
  // летели, теряет смысл. Перерисовка того же файла (а select зовётся на
  // каждое обновление списка) из режима не выкидывает.
  const srcKey = `${m.id}@${m.updated}`;
  if (fly.on && srcKey !== state.srcKey) flyExit();
  state.srcKey = srcKey;

  state.glbUrl = m.glb ? `/files/${m.id}/model.glb?v=${m.updated}` : null;
  if (window.walk) window.walk.setModel(state.glbUrl);

  if (m.glb) {
    // v= сбрасывает кэш, когда модель перегенерировали под тем же id
    viewer.src = `/files/${m.id}/model.glb?v=${m.updated}`;
    viewer.alt = `Модель ${m.id}`;
    $("viewer-empty").hidden = true;
    scheduleFallbackCheck();
  } else {
    viewer.removeAttribute("src");
    $("viewer-empty").hidden = false;
    $("viewer-empty").textContent = "у этой модели нет GLB";
  }

  const wt = m.watertight
    ? `<span class="v">замкнута</span>`
    : `<span class="v bad">не замкнута</span>`;

  $("meta").innerHTML = `
    <span><span class="k">id</span> <span class="v">${m.id}</span></span>
    <span><span class="k">движок</span> <span class="v">${m.engine || "?"}/${m.mode || "?"}</span></span>
    <span><span class="k">seed</span> <span class="v">${m.seed ?? "—"}</span></span>
    <span><span class="k">вершин</span> <span class="v">${fmtNum(m.vertices)}</span></span>
    <span><span class="k">полигонов</span> <span class="v">${fmtNum(m.faces)}</span></span>
    <span><span class="k">оболочка</span> ${wt}</span>
    <span><span class="k">время</span> <span class="v">${m.elapsed} с</span></span>
    <span><span class="k">размер</span> <span class="v">${fmtBytes(m.glb_size)}</span></span>
    <span><a href="/files/${m.id}/model.glb" download>скачать GLB</a></span>`;

  const strip = $("strip");
  strip.innerHTML = "";
  for (const [v, idx] of sample(m.views, 8)) {
    const src = `/files/${m.id}/views/${v}?v=${m.updated}`;
    const f = figure(src, v.replace(".png", "°"));
    // Клик по миниатюре доворачивает турнтейбл на этот ракурс
    f.querySelector("img").onclick = () => { setMode("spin"); setSpinFrame(idx); };
    strip.appendChild(f);
  }
  if (m.source) {
    strip.appendChild(figure(`/files/${m.id}/${m.source}?v=${m.updated}`, "исходник", true));
  }
  renderList();
}

function figure(src, caption, lightbox = false) {
  const f = document.createElement("figure");
  const img = document.createElement("img");
  img.src = src;
  img.alt = caption;
  if (lightbox) {
    img.onclick = () => { $("lightbox-img").src = src; $("lightbox").hidden = false; };
  }
  const cap = document.createElement("figcaption");
  cap.textContent = caption;
  f.append(img, cap);
  return f;
}

// ------------------------------------------------------------------ турнтейбл

function setSpinFrame(i) {
  const n = spin.frames.length;
  if (!n) return;
  spin.i = ((i % n) + n) % n;
  $("spin-img").src = spin.frames[spin.i];
}

function applySpinTransform() {
  $("spin-img").style.transform =
    `translate(${spin.px}px, ${spin.py}px) scale(${spin.scale})`;
}

function resetSpin() {
  spin.scale = 1; spin.px = 0; spin.py = 0; spin.acc = 0;
  applySpinTransform();
}

function initSpin() {
  const stage = $("spin-stage");

  stage.addEventListener("pointerdown", (e) => {
    spin.dragging = true;
    spin.panning = e.shiftKey || e.button === 1 || e.button === 2;
    spin.lastX = e.clientX; spin.lastY = e.clientY; spin.acc = 0;
    stage.classList.add("dragging");
    // Захват указателя не критичен, а бросить может: на некоторых вводах
    // и на синтетических событиях id не существует. Без него всё работает,
    // просто перетаскивание прервётся при уходе курсора за край.
    try { stage.setPointerCapture(e.pointerId); } catch { /* не беда */ }
  });

  stage.addEventListener("pointermove", (e) => {
    if (!spin.dragging) return;
    const dx = e.clientX - spin.lastX;
    const dy = e.clientY - spin.lastY;
    spin.lastX = e.clientX; spin.lastY = e.clientY;

    if (spin.panning) {
      spin.px += dx; spin.py += dy;
      applySpinTransform();
      return;
    }
    // ~9 пикселей на кадр: полный оборот примерно за ширину окна
    spin.acc += dx;
    const step = Math.trunc(spin.acc / 9);
    if (step) { spin.acc -= step * 9; setSpinFrame(spin.i - step); }
  });

  const stop = (e) => {
    spin.dragging = false; spin.panning = false;
    stage.classList.remove("dragging");
    try {
      if (e && e.pointerId != null && stage.hasPointerCapture(e.pointerId)) {
        stage.releasePointerCapture(e.pointerId);
      }
    } catch { /* см. выше */ }
  };
  stage.addEventListener("pointerup", stop);
  stage.addEventListener("pointercancel", stop);
  stage.addEventListener("contextmenu", (e) => e.preventDefault());

  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    spin.scale = clamp(spin.scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15), 1, 8);
    if (spin.scale === 1) { spin.px = 0; spin.py = 0; }
    applySpinTransform();
  }, { passive: false });

  stage.addEventListener("dblclick", resetSpin);
}

// ---------------------------------------------------------------- сетка пола

// Пол рисуется сеткой в перспективе, а не градиентом: градиент читается
// просто как серое пятно и не даёт ни плоскости, ни масштаба, ни понимания,
// куда повёрнута модель. Сетка считается из фактических параметров камеры
// вьюера на каждом её изменении, поэтому не разъезжается при вращении.
//
// Canvas лежит ПОД model-viewer, и это заодно решает перекрытие: модель
// закрывает сетку сама, отдельной проверкой глубины заниматься не нужно.
const gridState = { raf: 0, scene: null, warned: false };

// Камера берётся у самого рендерера, а не собирается заново из орбиты.
// Собственная сборка была ошибкой: model-viewer вращает камеру вокруг
// начала координат и смещает сцену, а не наоборот, поэтому прибавление
// getCameraTarget() к позиции камеры давало промах — маленький в покое
// и равный всему сдвигу после панорамирования. Сетка уезжала от модели.
//
// Это внутренности model-viewer, они могут измениться в новой версии.
// Поэтому при их отсутствии сетка не рисуется вовсе: лучше без пола,
// чем пол не там, где модель.
function sceneOf(v) {
  if (gridState.scene && gridState.scene.camera) return gridState.scene;
  for (const s of Object.getOwnPropertySymbols(v)) {
    const o = v[s];
    if (o && typeof o === "object" && o.camera && o.boundingBox && o.target) {
      gridState.scene = o;
      return o;
    }
  }
  if (!gridState.warned) {
    gridState.warned = true;
    console.warn("photo3d: внутренняя сцена model-viewer не найдена, сетка пола отключена");
  }
  return null;
}

function mul4(m, p) {
  const e = m.elements;
  return [
    e[0] * p[0] + e[4] * p[1] + e[8] * p[2] + e[12] * p[3],
    e[1] * p[0] + e[5] * p[1] + e[9] * p[2] + e[13] * p[3],
    e[2] * p[0] + e[6] * p[1] + e[10] * p[2] + e[14] * p[3],
    e[3] * p[0] + e[7] * p[1] + e[11] * p[2] + e[15] * p[3],
  ];
}

function drawGrid() {
  gridState.raf = 0;
  const canvas = $("grid");
  const wrap = $("viewer-wrap");
  const v = $("viewer");
  const ctx = canvas.getContext("2d");

  const dpr = window.devicePixelRatio || 1;
  const w = wrap.clientWidth, h = wrap.clientHeight;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  if (state.mode !== "3d" || wrap.classList.contains("plain") || !v.loaded) return;

  const sc = sceneOf(v);
  if (!sc) return;
  const cam = sc.camera;
  const bb = sc.boundingBox;
  if (!cam || !bb || !isFinite(bb.min.y)) return;

  // Матрицы обновляем сами: рендерер делает это каждый кадр, но сетка может
  // рисоваться и до его первого прохода.
  // updateMatrixWorld безопасен — рендерер делает то же каждый кадр.
  // А вот updateProjectionMatrix здесь НЕ вызывается: он пересобрал бы
  // матрицу из fov/aspect и стёр бы всё, что model-viewer мог в неё
  // положить сам. Читаем как есть.
  // Если камера ещё не подхватила размер окна, её матрица проекции считает
  // по другому аспекту — сетка уедет вбок относительно модели. Такое бывает
  // между изменением размера и первым кадром рендерера. Лучше пропустить
  // кадр: следующее camera-change всё равно перерисует.
  if (Math.abs(cam.aspect - w / h) > 0.03) return;

  cam.updateMatrixWorld(true);
  const inv = cam.matrixWorld.clone().invert();
  const near = Math.max(cam.near || 0.001, 1e-5);

  // Габаритный ящик хранится в своём пространстве; в мир его переводит
  // сдвиг scene.target.position. Без этой поправки центр модели промахивался
  // мимо центра экрана, а после панорамирования — на весь сдвиг.
  const off = sc.target.position;
  const toView = (x, y, z) => mul4(inv, [x + off.x, y + off.y, z + off.z, 1]);
  const viewToScreen = (vp) => {
    const c = mul4(cam.projectionMatrix, vp);
    if (c[3] <= 1e-9) return null;
    return [(c[0] / c[3] * 0.5 + 0.5) * w, (0.5 - c[1] / c[3] * 0.5) * h];
  };

  const floorY = bb.min.y;
  const cx = (bb.min.x + bb.max.x) / 2;
  const cz = (bb.min.z + bb.max.z) / 2;
  const span = Math.max(bb.max.x - bb.min.x, bb.max.z - bb.min.z) || 1;

  // Шаг — «круглое» число, чтобы модель занимала около шести клеток
  const raw = span / 6;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  let cell = [1, 2, 5, 10].map((m) => m * pow)
    .reduce((a, b) => (Math.abs(b - raw) < Math.abs(a - raw) ? b : a));

  // Поле заметно больше расстояния до камеры: край сетки не должен попадать
  // в кадр — иначе пол читается как висящая в пустоте площадка, а не как пол.
  // Позиция камеры в координатах модели. cam.position — смещение от цели
  // (вьюер вращает камеру вокруг начала координат и двигает сцену), поэтому
  // в мир она переводится тем же off, что и точки пола. В орбите разницы
  // почти нет, а в свободной камере цель улетает вместе с камерой, и без
  // этой поправки поле сетки считалось бы по радиусу орбиты — то есть пол
  // обрывался бы прямо под ногами.
  const camx = cam.position.x - off.x;
  const camy = cam.position.y - off.y;
  const camz = cam.position.z - off.z;
  const dist = Math.hypot(camx - cx, camy - floorY, camz - cz) || span * 4;
  const half = Math.max(span * 4, dist * 7);
  // Клетку укрупняем, пока число линий не станет разумным. Так сетка
  // подстраивается под масштаб, как в 3D-редакторах, вместо того чтобы
  // при отдалении превращаться в сплошную заливку.
  while ((2 * half) / cell > 130) cell *= (cell.toString()[0] === "1" ? 2 : 2.5);
  const N = Math.ceil(half / cell);

  const seg = (ax, ay, az, bx, by, bz, alpha, width) => {
    let A = toView(ax, ay, az);
    let B = toView(bx, by, bz);
    const da = -A[2], db = -B[2];                 // глубина в видовом пространстве
    if (da <= near && db <= near) return;
    if (da <= near || db <= near) {
      // Подрезаем по ближней плоскости: точка «за спиной» иначе
      // проецируется зеркально и линия улетает через весь экран.
      const t = (near - da) / (db - da);
      const M = [A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t,
                 A[2] + (B[2] - A[2]) * t, 1];
      if (da > near) B = M; else A = M;
    }
    const p = viewToScreen(A), q = viewToScreen(B);
    if (!p || !q) return;
    ctx.globalAlpha = alpha;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo(p[0], p[1]);
    ctx.lineTo(q[0], q[1]);
    ctx.stroke();
  };

  ctx.strokeStyle = "#93a6c0";
  ctx.lineCap = "butt";
  for (let i = -N; i <= N; i++) {
    const t = i * cell;
    if (Math.abs(t) >= half) continue;
    // Линии обрезаются по КРУГУ, а не по квадрату: у квадрата в кадр попадает
    // прямой угол, и пол читается как площадка с краем.
    const L = Math.sqrt(half * half - t * t);
    const axis = i === 0;
    const major = i % 5 === 0;
    const alpha = axis ? 0.55 : major ? 0.42 : 0.22;
    const width = axis ? 1.4 : major ? 1.1 : 0.8;
    seg(cx + t, floorY, cz - L, cx + t, floorY, cz + L, alpha, width);
    seg(cx - L, floorY, cz + t, cx + L, floorY, cz + t, alpha, width);
  }

  // Круг под моделью: показывает точку опоры и сразу читается как «низ»
  ctx.globalAlpha = 0.55;
  ctx.lineWidth = 1.3;
  ctx.strokeStyle = "#c2cfe0";
  const r = span * 0.62;
  ctx.beginPath();
  let started = false;
  for (let a = 0; a <= 72; a++) {
    const ang = (a / 72) * Math.PI * 2;
    const vp = toView(cx + r * Math.cos(ang), floorY, cz + r * Math.sin(ang));
    if (-vp[2] <= near) { started = false; continue; }
    const p = viewToScreen(vp);
    if (!p) { started = false; continue; }
    if (!started) { ctx.moveTo(p[0], p[1]); started = true; }
    else ctx.lineTo(p[0], p[1]);
  }
  ctx.stroke();
  ctx.globalAlpha = 1;

  // Растворение вместо обрезки. Даже круглое поле имеет край, и в кадре он
  // выглядит границей пола. Гасим готовую сетку радиальным градиентом от
  // основания модели — тогда она уходит в ничто и читается бесконечной.
  const baseView = toView(cx, floorY, cz);
  const base = -baseView[2] > near ? viewToScreen(baseView) : [w / 2, h * 0.62];

  ctx.globalCompositeOperation = "destination-in";

  // 1. По глубине. Вдали линии сходятся и сливаются в сплошную заливку,
  // поэтому дальний план надо гасить сильнее ближнего. Ориентир — экранная
  // высота точки на полу в отдалении: она и задаёт направление «вглубь».
  const away = Math.hypot(cx - camx, cz - camz) > 1e-6
    ? [cx - camx, cz - camz] : [0, -1];
  const alen = Math.hypot(away[0], away[1]) || 1;
  const farView = toView(cx + away[0] / alen * half * 0.5, floorY,
                         cz + away[1] / alen * half * 0.5);
  const far = -farView[2] > near ? viewToScreen(farView) : [w / 2, -h];
  const depth = ctx.createLinearGradient(0, base[1], 0, far[1]);
  depth.addColorStop(0, "rgba(0,0,0,1)");
  depth.addColorStop(0.35, "rgba(0,0,0,0.55)");
  depth.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = depth;
  ctx.fillRect(0, 0, w, h);

  // 2. По радиусу — чтобы сетка не обрывалась краем по бокам и снизу.
  const R = Math.hypot(w, h) * 0.72;
  const radial = ctx.createRadialGradient(base[0], base[1], R * 0.10,
                                          base[0], base[1], R);
  radial.addColorStop(0, "rgba(0,0,0,1)");
  radial.addColorStop(0.5, "rgba(0,0,0,0.9)");
  radial.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = radial;
  ctx.fillRect(0, 0, w, h);

  ctx.globalCompositeOperation = "source-over";
}

function scheduleGrid() {
  if (!gridState.raf) gridState.raf = requestAnimationFrame(drawGrid);
}

function initGrid() {
  const v = $("viewer");
  v.addEventListener("camera-change", scheduleGrid);
  v.addEventListener("load", scheduleGrid);
  new ResizeObserver(scheduleGrid).observe($("viewer-wrap"));
}

// ------------------------------------------------------------------- режимы

function setMode(mode, auto = false) {
  if (mode !== "3d") flyExit();     // турнтейбл — картинки, летать негде
  state.mode = mode;
  const is3d = mode === "3d";
  const isWalk = mode === "walk";
  $("viewer").style.visibility = is3d ? "visible" : "hidden";
  $("spin-stage").hidden = mode !== "spin";
  document.querySelectorAll(".mode").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === mode));
  $("btn-rotate").style.display = is3d ? "" : "none";

  // Прогулка живёт в walk.js: он модуль, app.js — обычный скрипт, поэтому
  // общаются через window.walk. Модуль грузится позже разметки, так что
  // проверка на его наличие обязательна, а не «на всякий случай».
  if (window.walk) {
    if (isWalk) window.walk.enter(state.glbUrl);
    else window.walk.exit();
  } else if (isWalk) {
    $("walk-stage").hidden = false;
    $("walk-error").hidden = false;
    $("walk-error").textContent =
      "модуль прогулки не загрузился. Прогони scripts/fetch-vendor.sh three — " +
      "он кладёт three.js в web/static/vendor/three/.";
  }

  const hint = $("hint");
  hint.hidden = false;
  hint.classList.toggle("warn", auto);
  if (auto) {
    hint.textContent = "3D-вьюер не смог отрисовать сцену — включён турнтейбл " +
      "по готовым кадрам. Тяни мышью, колесо меняет масштаб.";
  } else if (isWalk) {
    hint.hidden = true;                        // в прогулке своя подсказка
  } else if (is3d) {
    hint.textContent = "ЛКМ — вращать · колесо — масштаб · ПКМ — сдвинуть · C — свободная камера";
  } else {
    hint.textContent = "тяни влево-вправо — вращать · колесо — масштаб · Shift+тяни — сдвинуть";
  }
  clearTimeout(state.hintTimer);
  if (!auto) state.hintTimer = setTimeout(() => { $("hint").hidden = true; }, 4000);
  scheduleGrid();
}

// model-viewer рисует только когда страница реально композитит кадры.
// Если через несколько секунд холст так и не ожил — молча показывать
// пустоту нельзя, переключаемся на турнтейбл.
function scheduleFallbackCheck() {
  clearInterval(state.fbTimer);
  // Проверяем не один раз, а до восьми секунд: тяжёлый GLB может рисоваться
  // не сразу, и однократная проверка через 3.5 с уводила бы в турнтейбл
  // работающий вьюер. Переключаемся только если холст так и не ожил.
  const deadline = Date.now() + 8000;
  state.fbTimer = setInterval(() => {
    if (state.mode !== "3d" || !spin.frames.length) {
      clearInterval(state.fbTimer);
      return;
    }
    const v = $("viewer");
    const c = v.shadowRoot && v.shadowRoot.querySelector("canvas");
    if (v.modelIsVisible && c && c.width > 300) {
      clearInterval(state.fbTimer);          // ожил, всё в порядке
    } else if (Date.now() > deadline) {
      clearInterval(state.fbTimer);
      setMode("spin", true);
    }
  }, 600);
}

// -------------------------------------------------------------- 3D-управление

function zoom3d(factor) {
  const v = $("viewer");
  // В свободной камере приближение — это шаг вперёд, а не изменение радиуса:
  // радиус там держит отсечение и трогать его нельзя (см. flyEnter).
  if (fly.on) { flyMove(factor < 1 ? fly.speed * 0.4 : -fly.speed * 0.4); return; }
  if (state.mode !== "3d") {
    spin.scale = clamp(spin.scale * (factor < 1 ? 1.25 : 1 / 1.25), 1, 8);
    if (spin.scale === 1) { spin.px = 0; spin.py = 0; }
    applySpinTransform();
    return;
  }
  try {
    const o = v.getCameraOrbit();
    v.cameraOrbit = `${o.theta}rad ${o.phi}rad ${Math.max(o.radius * factor, 0.01)}m`;
  } catch { /* вьюер ещё не готов */ }
}

$("btn-zoom-in").onclick = () => zoom3d(0.8);
$("btn-zoom-out").onclick = () => zoom3d(1.25);

$("btn-reset").onclick = () => {
  if (fly.on) {
    // «Я улетел и не вижу модель» — главный способ потеряться в свободной
    // камере. Сброс не выкидывает из режима, а разворачивает на модель и
    // подтягивает к ней, если улетели совсем далеко.
    const c = fly.center;
    let dx = fly.eye.x - c.x, dy = fly.eye.y - c.y, dz = fly.eye.z - c.z;
    let dist = Math.hypot(dx, dy, dz) || fly.span;
    if (dist > fly.span * 6) {
      const k = (fly.span * 3) / dist;
      fly.eye = { x: c.x + dx * k, y: c.y + dy * k, z: c.z + dz * k };
      dx *= k; dy *= k; dz *= k; dist *= k;
    }
    fly.yaw = Math.atan2(-dx, -dz);
    fly.pitch = Math.asin(clamp(-dy / dist, -1, 1));
    flyApply();
    return;
  }
  if (state.mode === "3d") {
    const v = $("viewer");
    v.cameraOrbit = "0deg 75deg auto";
    v.fieldOfView = "auto";
    v.resetTurntableRotation && v.resetTurntableRotation();
  } else {
    resetSpin();
  }
};

$("btn-rotate").onclick = (e) => {
  const v = $("viewer");
  const on = v.hasAttribute("auto-rotate");
  if (on) v.removeAttribute("auto-rotate"); else v.setAttribute("auto-rotate", "");
  e.currentTarget.classList.toggle("off", on);
};

$("btn-scene").onclick = (e) => {
  const wrap = $("viewer-wrap");
  const off = wrap.classList.toggle("plain");
  e.currentTarget.classList.toggle("off", off);
  // Тень имеет смысл только вместе с подложкой: висящая в пустоте она
  // читается как грязь под моделью.
  $("viewer").setAttribute("shadow-intensity", off ? "0" : "1.5");
  scheduleGrid();
};

$("btn-full").onclick = () => {
  const el = $("viewer-wrap");
  if (document.fullscreenElement) document.exitFullscreen();
  else el.requestFullscreen && el.requestFullscreen();
};

// ------------------------------------------------------------ свободная камера

// model-viewer умеет только орбиту: камера всегда смотрит в цель и стоит от
// неё на расстоянии radius. Свободного полёта в его API нет, но он собирается
// из двух свойств сразу. Держим своё состояние — глаз и углы взгляда, — а во
// вьюер отдаём цель = глаз + направление·radius и орбиту, развёрнутую на 180°.
// Камера, которую вьюер вычислит из этой пары, встанет ровно в глаз, а поворот
// головы перестанет таскать её по дуге вокруг модели, как делает орбита.
//
// radius при этом не трогается вовсе. Соблазн «подъезжать» его уменьшением
// велик, но ближняя и дальняя плоскости пересчитываются только при смене
// max-camera-orbit, и радиус, уехавший от того, под который их считали, даёт
// отсечение не там. Едем целиком глазом, радиус — константа режима.
const fly = {
  on: false,
  eye: { x: 0, y: 0, z: 0 },
  yaw: 0, pitch: 0,
  radius: 1,          // орбита режима, см. выше
  span: 1,            // габарит модели: к нему привязаны скорость и пределы
  half: 1,            // половина диагонали габаритного ящика
  center: { x: 0, y: 0, z: 0 },
  speed: 1,           // единиц модели в секунду
  keys: new Set(),
  raf: 0, last: 0,
  dragging: false,
  hadLock: false,
  clamped: false,
  saved: null,
};

// Клавиши читаются по e.code, а не по e.key: при русской раскладке key даёт
// «ц», «ф», «ы», «в», и WASD молча перестаёт работать. code от раскладки
// не зависит.
const FLY_KEYS = new Set([
  "KeyW", "KeyA", "KeyS", "KeyD", "KeyQ", "KeyE", "Space",
  "ControlLeft", "ControlRight", "ShiftLeft", "ShiftRight",
]);

const FLY_BOOST = 3;          // ускорение по Shift
const FLY_FOV = 65;           // градусов, «человеческий» обзор вместо кадрирующего
const FLY_TURN = 600;         // пикселей мыши на поворот в высоту кадра

// Чувствительность мыши считается от фактического поля зрения, а не задана
// в радианах на пиксель. Кадрирующий объектив вьюера узкий (30° на типовой
// модели), и при постоянной чувствительности один пиксель мыши сдвигал мир
// на четыре экранных: поворот читался как рывки из стороны в сторону.
// Привязка к обзору держит отклик в долях кадра, а не в градусах.
function flySens() {
  const fov = $("viewer").getFieldOfView() || FLY_FOV;
  return (fov * Math.PI / 180) / FLY_TURN;
}

function flyDir() {
  const cp = Math.cos(fly.pitch);
  return {
    x: Math.sin(fly.yaw) * cp,
    y: Math.sin(fly.pitch),
    z: Math.cos(fly.yaw) * cp,
  };
}

// Дальше этого предела модель уходит за дальнюю плоскость и просто пропадает
// с экрана. Пустой вьюер без объяснения читается как поломка, поэтому дальше
// камеру не пускаем и говорим об этом в подсказке.
function flyLimit() {
  const sc = sceneOf($("viewer"));
  const far = sc && sc.camera ? sc.camera.far : 0;
  return far > 0 ? Math.max(far * 0.9 - fly.half, fly.span) : fly.span * 25;
}

function flyHud() {
  // Скорость показывается в габаритах модели в секунду: абсолютные единицы
  // GLB ничего не говорят — модели приходят и метровые, и сантиметровые.
  $("fly-speed").textContent = `скорость ${(fly.speed / fly.span).toFixed(2)} мод/с`;
}

function flyApply() {
  const v = $("viewer");
  const d = flyDir(), r = fly.radius, e = fly.eye;
  v.cameraTarget = `${e.x + d.x * r}m ${e.y + d.y * r}m ${e.z + d.z * r}m`;
  v.cameraOrbit = `${fly.yaw + Math.PI}rad ${fly.pitch + Math.PI / 2}rad ${r}m`;
}

function flyLook(dx, dy) {
  const s = flySens();
  fly.yaw -= dx * s;
  // Ровно на полюсе орбита вырождается: theta теряет смысл, картинка дёргается
  const lim = Math.PI / 2 - 0.02;
  fly.pitch = clamp(fly.pitch - dy * s, -lim, lim);
  flyApply();
}

function flyMove(dist) {
  const d = flyDir();
  fly.eye.x += d.x * dist; fly.eye.y += d.y * dist; fly.eye.z += d.z * dist;
  flyHold();
  flyApply();
}

function flyHold() {
  const lim = flyLimit(), c = fly.center;
  const dx = fly.eye.x - c.x, dy = fly.eye.y - c.y, dz = fly.eye.z - c.z;
  const dist = Math.hypot(dx, dy, dz);
  const over = dist > lim;
  if (over) {
    const k = lim / dist;
    fly.eye.x = c.x + dx * k; fly.eye.y = c.y + dy * k; fly.eye.z = c.z + dz * k;
  }
  if (over !== fly.clamped) { fly.clamped = over; $("fly-warn").hidden = !over; }
}

function flyTick(now) {
  fly.raf = requestAnimationFrame(flyTick);
  // Свёрнутая вкладка не получает кадров, и первый после разворачивания
  // придёт с шагом в секунды: без потолка одно нажатие уносит за горизонт.
  const dt = Math.min((now - fly.last) / 1000, 0.1);
  fly.last = now;

  const k = fly.keys;
  const fwd = (k.has("KeyW") ? 1 : 0) - (k.has("KeyS") ? 1 : 0);
  const side = (k.has("KeyD") ? 1 : 0) - (k.has("KeyA") ? 1 : 0);
  const up = ((k.has("KeyE") || k.has("Space")) ? 1 : 0)
           - ((k.has("KeyQ") || k.has("ControlLeft") || k.has("ControlRight")) ? 1 : 0);
  if (!fwd && !side && !up) return;

  const step = fly.speed * (k.has("ShiftLeft") || k.has("ShiftRight") ? FLY_BOOST : 1) * dt;
  const d = flyDir();
  // Вбок — строго по горизонтали. С честным векторным «вправо» шаг вбок при
  // взгляде вверх уводил бы камеру вниз, хотя ехали ровно вбок.
  const rx = -Math.cos(fly.yaw), rz = Math.sin(fly.yaw);

  fly.eye.x += (d.x * fwd + rx * side) * step;
  fly.eye.y += (d.y * fwd + up) * step;
  fly.eye.z += (d.z * fwd + rz * side) * step;
  flyHold();
  flyApply();
}

function flyEnter() {
  const v = $("viewer");
  if (fly.on) return;
  if (state.mode !== "3d" || !v.loaded) {
    const hint = $("hint");
    hint.hidden = false;
    hint.classList.add("warn");
    hint.textContent = "свободная камера работает в режиме 3D и только с загруженной моделью";
    clearTimeout(state.hintTimer);
    state.hintTimer = setTimeout(() => {
      $("hint").hidden = true; $("hint").classList.remove("warn");
    }, 3000);
    return;
  }

  const o = v.getCameraOrbit();
  const t = v.getCameraTarget();
  fly.radius = Math.max(o.radius, 1e-4);
  fly.eye = {
    x: t.x + fly.radius * Math.sin(o.phi) * Math.sin(o.theta),
    y: t.y + fly.radius * Math.cos(o.phi),
    z: t.z + fly.radius * Math.sin(o.phi) * Math.cos(o.theta),
  };
  fly.yaw = o.theta - Math.PI;
  fly.pitch = clamp(o.phi - Math.PI / 2, -Math.PI / 2 + 0.02, Math.PI / 2 - 0.02);

  const dim = v.getDimensions();
  const c = v.getBoundingBoxCenter();
  fly.span = Math.max(dim.x, dim.y, dim.z) || 1;
  fly.half = Math.hypot(dim.x, dim.y, dim.z) / 2 || fly.span;
  fly.center = { x: c.x, y: c.y, z: c.z };
  fly.speed = fly.span * 1.4;      // примерно полтора габарита в секунду

  // Свойства, а не атрибуты: снятый атрибут у lit превращает число в null,
  // и interpolation-decay после выхода остался бы сломанным навсегда.
  // auto-rotate — исключение: его состояние читает кнопка ⟳ по атрибуту.
  fly.saved = {
    orbit: `${o.theta}rad ${o.phi}rad ${o.radius}m`,
    target: `${t.x}m ${t.y}m ${t.z}m`,
    min: v.minCameraOrbit, max: v.maxCameraOrbit,
    controls: v.cameraControls, decay: v.interpolationDecay,
    prompt: v.interactionPrompt, rotate: v.hasAttribute("auto-rotate"),
    fov: v.fieldOfView, maxFov: v.maxFieldOfView,
  };

  v.cameraControls = false;              // мышь и колесо ведём сами
  v.removeAttribute("auto-rotate");
  v.interactionPrompt = "none";          // подсказка вьюера сама крутит камеру
  // Штатный наклон ограничен «не под пол» — от первого лица это значило бы
  // «вверх смотреть нельзя».
  //
  // Третье число — радиус, и оно тут не про орбиту: из него вьюер считает
  // дальнюю плоскость (far = 2·радиус) и ближнюю (near = far/1000). При auto
  // радиус равен дистанции кадрирования, и модель пропадала бы уже в четырёх
  // своих габаритах от камеры. Десять габаритов дают запас на облёт, а ближняя
  // плоскость при этом остаётся в паре сантиметров на метровой модели —
  // подойти вплотную к лицу по-прежнему можно.
  v.minCameraOrbit = "auto 0.5deg auto";
  v.maxCameraOrbit = `auto 179.5deg ${(fly.span * 10).toFixed(4)}m`;
  // Сглаживание камеры в 50 мс на непрерывном управлении читается как
  // залипание мыши. Почти ноль: демпфер при таком времени отдаёт цель точно.
  v.interpolationDecay = 0.001;
  // Штатный обзор — кадрирующий: вьюер подбирает его так, чтобы модель
  // заполнила кадр, и выходит телеобъектив (30° на типовой модели). Внутри
  // сцены он читается как «мир прыгает при повороте» и «иду по колено в
  // воде», потому что узкий угол сжимает перспективу и убивает ощущение хода.
  // Потолок поднимается отдельно и РАНЬШЕ самого обзора: setFieldOfView
  // режет значение по max, а порядок применения свойств внутри одного цикла
  // обновления нам не подконтролен. Отсюда установка через updateComplete.
  v.maxFieldOfView = `${FLY_FOV + 25}deg`;
  v.updateComplete.then(() => { if (fly.on) v.fieldOfView = `${FLY_FOV}deg`; });

  fly.on = true;
  fly.hadLock = false;
  fly.clamped = false;
  fly.keys.clear();
  $("viewer-wrap").classList.add("fly");
  $("btn-fly").classList.add("on");
  $("btn-rotate").style.display = "none";
  $("hint").hidden = true;
  $("fly-hud").hidden = false;
  $("fly-cross").hidden = false;
  $("fly-warn").hidden = true;
  flyHud();
  flyApply();

  fly.last = performance.now();
  fly.raf = requestAnimationFrame(flyTick);
  flyLock();
}

function flyLock() {
  const wrap = $("viewer-wrap");
  try {
    const p = wrap.requestPointerLock();
    // Захват может не дать ни браузер, ни пользователь. Это не ошибка:
    // обзор тогда работает перетаскиванием, курсор остаётся видимым.
    if (p && p.catch) p.catch(() => {});
  } catch { /* см. выше */ }
}

function flyExit() {
  if (!fly.on) return;
  fly.on = false;
  cancelAnimationFrame(fly.raf);
  fly.raf = 0;
  fly.keys.clear();
  fly.dragging = false;

  const v = $("viewer"), s = fly.saved || {};
  v.minCameraOrbit = s.min; v.maxCameraOrbit = s.max;
  v.maxFieldOfView = s.maxFov; v.fieldOfView = s.fov;
  v.interpolationDecay = s.decay;
  v.interactionPrompt = s.prompt;
  v.cameraControls = s.controls;
  if (s.rotate) v.setAttribute("auto-rotate", "");
  // Возврат ровно туда, откуда взлетели. Свободная камера — временный режим,
  // и «где я вообще» после выхода хуже, чем потеря налётанного ракурса.
  if (s.orbit) { v.cameraTarget = s.target; v.cameraOrbit = s.orbit; }

  if (document.pointerLockElement) document.exitPointerLock();
  $("viewer-wrap").classList.remove("fly");
  $("btn-fly").classList.remove("on");
  $("btn-rotate").style.display = state.mode === "3d" ? "" : "none";
  $("fly-hud").hidden = true;
  $("fly-cross").hidden = true;
  scheduleGrid();
}

function initFly() {
  const wrap = $("viewer-wrap");

  $("btn-fly").onclick = () => (fly.on ? flyExit() : flyEnter());

  document.addEventListener("pointerlockchange", () => {
    if (document.pointerLockElement === wrap) { fly.hadLock = true; return; }
    fly.keys.clear();
    // Esc браузер съедает сам: keydown до нас не доходит, приходит только
    // потеря захвата. Поэтому выход из режима висит именно здесь.
    if (fly.on && fly.hadLock) flyExit();
  });

  wrap.addEventListener("pointerdown", (e) => {
    if (!fly.on || e.button !== 0) return;
    if (document.pointerLockElement === wrap) return;
    fly.dragging = true;                 // запасной обзор, когда захвата нет
    flyLock();
  });
  window.addEventListener("pointerup", () => { fly.dragging = false; });

  document.addEventListener("pointermove", (e) => {
    if (!fly.on) return;
    if (document.pointerLockElement !== wrap && !fly.dragging) return;
    flyLook(e.movementX || 0, e.movementY || 0);
  });

  // Колесо меняет скорость, а не масштаб: приближаться в свободной камере
  // надо движением, а вот «медленно у лица, быстро в облёте» нужно всегда.
  wrap.addEventListener("wheel", (e) => {
    if (!fly.on) return;
    e.preventDefault();
    fly.speed = clamp(fly.speed * (e.deltaY < 0 ? 1.2 : 1 / 1.2),
                      fly.span * 0.02, fly.span * 20);
    flyHud();
  }, { passive: false });

  document.addEventListener("keyup", (e) => {
    if (fly.on) fly.keys.delete(e.code);
  });
  // Потеря фокуса не шлёт keyup: без этого клавиша остаётся «нажатой»
  // и камера уезжает сама по себе после переключения окна.
  window.addEventListener("blur", () => fly.keys.clear());
}

function flyKeyDown(e) {
  if (e.code === "Escape" || e.code === "KeyC") { flyExit(); return; }
  if (!FLY_KEYS.has(e.code)) return;
  e.preventDefault();          // пробел иначе прокручивает страницу
  fly.keys.add(e.code);
}

// Подсказка про управление гаснет через несколько секунд, но возвращается
// при наведении: иначе про правую кнопку и колесо никто не узнает.
$("viewer-wrap").addEventListener("mouseenter", () => {
  if (fly.on) return;                                 // там своя подсказка
  if ($("hint").classList.contains("warn")) return;   // предупреждение не трогаем
  $("hint").hidden = false;
  clearTimeout(state.hintTimer);
  state.hintTimer = setTimeout(() => { $("hint").hidden = true; }, 2600);
});

document.querySelectorAll(".mode").forEach((b) => {
  b.onclick = () => setMode(b.dataset.mode);
});

// ----------------------------------------------------------------- обновления

function applyModels(models) {
  const hadNew = models.some((m) => !state.known.has(m.id));
  if (!state.first) markFresh(models.filter((m) => !state.known.has(m.id)).map((m) => m.id));
  const prevSelected = state.selectedId;
  state.models = models;

  if ($("follow").checked && hadNew && models.length) {
    select(models[0].id);           // свежая всегда сверху
  } else if (prevSelected && models.some((m) => m.id === prevSelected)) {
    select(prevSelected);           // перерисовать: модель могли перегенерировать
  } else if (!prevSelected && models.length) {
    select(models[0].id);
  } else {
    renderList();
  }
}

function setLive(stateName, text) {
  const el = $("live");
  el.dataset.state = stateName;
  el.querySelector(".live-text").textContent = text;
}

function flash() {
  const el = $("live");
  el.classList.add("flash");
  setTimeout(() => el.classList.remove("flash"), 260);
}

function connect() {
  const es = new EventSource("/api/events");
  es.addEventListener("open", () => setLive("live", "в реальном времени"));
  es.addEventListener("models", (e) => {
    setLive("live", "в реальном времени");
    const data = JSON.parse(e.data);
    if (!state.first) flash();
    applyModels(data.models);
    // Навигации нужно то же состояние целиком (в нём ещё и корзина).
    // Отдаём событием, чтобы она не открывала второе соединение SSE:
    // каждое стоит серверу отдельного обхода папок по drvfs.
    window.dispatchEvent(new CustomEvent("photo3d:state", { detail: data }));
  });
  es.addEventListener("error", () => {
    setLive("down", "соединение потеряно");
    // EventSource переподключается сам, руками не трогаем
  });
}

// ----------------------------------------------------------------- клавиатура

$("lightbox").onclick = () => { $("lightbox").hidden = true; };

// Молчаливый провал загрузки GLB выглядит как «пустой вьюер» и уводит
// диагностику не туда. Пусть говорит прямо.
$("viewer").addEventListener("error", () => {
  if (spin.frames.length) setMode("spin", true);
  else {
    const ve = $("viewer-empty");
    ve.hidden = false;
    ve.textContent = "не удалось загрузить GLB";
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("lightbox").hidden = true;
  if (e.target.tagName === "INPUT") return;

  // В свободной камере клавиатура целиком её: WASD не должны попасть
  // в листание моделей стрелками и прочие общие сочетания.
  if (fly.on) { flyKeyDown(e); return; }
  if (e.code === "KeyC") { flyEnter(); return; }

  if (state.mode === "spin" && spin.frames.length) {
    if (e.key === "ArrowLeft") { setSpinFrame(spin.i + 1); return; }
    if (e.key === "ArrowRight") { setSpinFrame(spin.i - 1); return; }
  }
  if (e.key === "+" || e.key === "=") { zoom3d(0.8); return; }
  if (e.key === "-") { zoom3d(1.25); return; }
  if (e.key === "f") { $("btn-full").click(); return; }

  if (!state.models.length) return;
  const i = state.models.findIndex((m) => m.id === state.selectedId);
  if (e.key === "ArrowDown" && i < state.models.length - 1) select(state.models[i + 1].id);
  if (e.key === "ArrowUp" && i > 0) select(state.models[i - 1].id);
});

// Вьюер - веб-компонент из вендоренного бандла. Если он не загрузился,
// молчаливо показывать пустоту нельзя: это выглядит как «модель сломана».
window.addEventListener("load", () => {
  setTimeout(() => {
    if (!customElements.get("model-viewer")) {
      document.querySelector('.mode[data-mode="3d"]').disabled = true;
      if (spin.frames.length) setMode("spin", true);
      else {
        $("viewer-empty").hidden = false;
        $("viewer-empty").innerHTML =
          "3D-вьюер не загрузился.<br>Прогони scripts/fetch-vendor.sh";
      }
    }
  }, 1500);
});

initSpin();
initGrid();
initFly();
setMode("3d");

fetch("/api/models")
  .then((r) => r.json())
  .then((d) => {
    applyModels(d.models);
    window.dispatchEvent(new CustomEvent("photo3d:state", { detail: d }));
  })
  .catch(() => setLive("down", "сервер не отвечает"));

connect();
