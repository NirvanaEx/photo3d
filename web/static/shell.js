// Оболочка: ширины доков, сворачивание панели разделов, подсказка в строке
// состояния. О моделях, генерации и вьюере не знает ничего — только о
// раскладке. Поэтому и лежит отдельно: правки раскладки не должны заезжать
// в файлы, где живёт состояние.

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;

  // Раскладка хранится отдельно от ui.json на сервере. Причина: ui.json везёт
  // то, что относится к моделям (масштаб прогулки, последний ракурс), и его
  // читает генератор. Ширина панели — свойство этого браузера на этом экране,
  // ей на сервере делать нечего.
  const KEY = "photo3d.shell";
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { /* мусор — начнём с чистого */ }

  const save = () => {
    try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch { /* приватный режим */ }
  };

  // --------------------------------------------------------------- доки

  // Границы подобраны по содержимому, а не «на глаз с запасом»: слева
  // карточка модели с миниатюрой 54px и двумя строками текста, ниже 190px
  // текст начинает рваться; справа строка свойства «полигонов 296 470» —
  // ниже 230px она переносится, и таблица перестаёт читаться колонками.
  const DOCKS = {
    sidebar: { css: "--dock-l", min: 190, max: 460, def: 260, edge: "right" },
    inspector: { css: "--dock-r", min: 230, max: 520, def: 300, edge: "left" },
  };

  function setDock(name, px) {
    const d = DOCKS[name];
    const v = Math.round(Math.min(d.max, Math.max(d.min, px)));
    root.style.setProperty(d.css, v + "px");
    saved[name] = v;
  }

  for (const name of Object.keys(DOCKS)) {
    setDock(name, saved[name] || DOCKS[name].def);
  }
  save();

  for (const split of document.querySelectorAll(".dock-split")) {
    const name = split.dataset.split;
    const d = DOCKS[name];
    if (!d) continue;

    split.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      // Захват указателя обязателен: без него быстрый рывок мышью уводит
      // курсор за пределы полосы в 5px, события уходят вьюпорту, и панель
      // «отцепляется» на середине движения.
      split.setPointerCapture(e.pointerId);
      split.classList.add("drag");
      document.body.classList.add("resizing");

      const box = split.parentElement.getBoundingClientRect();

      const move = (ev) => {
        // Ширина считается от края раздела, а не приращением от начала
        // перетаскивания: приращение накапливает ошибку об ограничители —
        // упёрся в минимум, повёл обратно, и панель трогается не сразу.
        const px = d.edge === "right" ? ev.clientX - box.left : box.right - ev.clientX;
        setDock(name, px);
      };
      const up = () => {
        split.classList.remove("drag");
        document.body.classList.remove("resizing");
        split.removeEventListener("pointermove", move);
        split.removeEventListener("pointerup", up);
        split.removeEventListener("pointercancel", up);
        save();
        // Вьюер и сетка пола считают кадр от своего размера, а его меняет
        // именно это перетаскивание. Без пинка первый кадр после отпускания
        // остаётся с прошлым аспектом.
        window.dispatchEvent(new Event("resize"));
      };
      split.addEventListener("pointermove", move);
      split.addEventListener("pointerup", up);
      split.addEventListener("pointercancel", up);
    });

    split.addEventListener("dblclick", () => {
      setDock(name, d.def);
      save();
      window.dispatchEvent(new Event("resize"));
    });
  }

  // Вьюпорт узнаёт о новом размере и во время перетаскивания, а не только
  // после: иначе модель прыгает в конце движения вместо того, чтобы ехать
  // вместе с границей. ResizeObserver, а не событие resize окна, — окно-то
  // не меняется.
  const stage = $("stage");
  if (stage && window.ResizeObserver) {
    let tick = 0;
    new ResizeObserver(() => {
      cancelAnimationFrame(tick);
      tick = requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    }).observe(stage);
  }

  // -------------------------------------------------- панель разделов

  const applyRail = () => {
    document.body.classList.toggle("rail-min", !!saved.railMin);
    const b = $("rail-toggle");
    if (b) b.title = saved.railMin ? "Развернуть панель разделов" : "Свернуть панель разделов";
  };
  applyRail();

  const toggle = $("rail-toggle");
  if (toggle) {
    toggle.onclick = () => {
      saved.railMin = !saved.railMin;
      applyRail();
      save();
      window.dispatchEvent(new Event("resize"));
    };
  }

  // ------------------------------------------------- строка состояния

  // Правая часть строки состояния показывает клавиши текущего раздела.
  // Сочетания здесь не выдуманы под красивую строку, а взяты из фактических
  // обработчиков: цифры — nav.js, стрелки и камера — app.js. Подсказка,
  // расходящаяся с кодом, хуже её отсутствия.
  const HINTS = {
    home: "<kbd>1</kbd><kbd>2</kbd><kbd>3</kbd> разделы",
    viewer: "<kbd>↑</kbd><kbd>↓</kbd> модели · <kbd>+</kbd><kbd>−</kbd> масштаб" +
            " · <kbd>C</kbd> камера · <kbd>F</kbd> во весь экран",
    create: "<kbd>1</kbd><kbd>2</kbd><kbd>3</kbd> разделы",
    trash: "<kbd>1</kbd><kbd>2</kbd><kbd>3</kbd> разделы",
  };

  function routeName() {
    const h = location.hash || "#/";
    if (/^#\/m\//.test(h)) return "viewer";
    if (h.startsWith("#/trash")) return "trash";
    if (h.startsWith("#/new")) return "create";
    return "home";
  }

  function paintHint() {
    const box = $("status-hint");
    if (box) box.innerHTML = HINTS[routeName()] || "";
  }

  window.addEventListener("hashchange", paintHint);
  paintHint();
})();
