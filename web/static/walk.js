// Прогулка по сцене: ходьба от первого лица со столкновениями и тяжестью.
//
// Отдельный рендерер на three.js, а не ещё один режим внутри model-viewer.
// Причина в CLAUDE.md: model-viewer показывает ПРЕДМЕТ — его камера всегда
// орбитальная, наружу он её не отдаёт и переписывает каждый кадр из своих
// сферических координат. Ходьбы там нет и быть не может, а в three.js она
// есть готовой: PointerLockControls для обзора, Octree и Capsule из
// официального примера games/fps для столкновений. Своё здесь — только
// склейка с интерфейсом и показания отладочной панели.
//
// Модуль общается с app.js через window.walk: тот классический скрипт,
// этот модульный, импортировать друг друга они не могут.

import * as THREE from "three";
import { PointerLockControls } from "three/addons/controls/PointerLockControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { HDRLoader } from "three/addons/loaders/HDRLoader.js";
import { Octree } from "three/addons/math/Octree.js";
import { Capsule } from "three/addons/math/Capsule.js";

// Человеческий масштаб, метры. Модели приходят предметами около метра, и
// смотреть на них с человеческого роста — правильное умолчание для панели
// разработки: ровно так предмет будет виден в игре.
const EYE = 1.65;
const FEET = 0.32;          // низ капсулы = её радиус
const SPEED = 4.2;          // м/с — предельная скорость шага, не ускорение
const SPRINT = 2.2;         // множитель по Shift
const GRAVITY = 24;         // не 9.8: игровая тяжесть читается как отзывчивая,
                            // настоящая ощущается прыжком на Луне
const JUMP = 7.2;
// Сопротивление задаёт и разгон: ускорение считается как SPEED·DRAG, поэтому
// предельная скорость равна ровно SPEED, а не «сколько получится». Иначе
// подбор двух чисел вслепую даёт то ватный ход, то разгон до сотни.
const DRAG_GROUND = 9;      // 1/с
const DRAG_AIR = 1.2;
const AIR_CONTROL = 0.25;   // управляемость в прыжке — доля земной
const SUBSTEPS = 5;         // подшагов физики на кадр: капсула не должна
                            // проскакивать сквозь стену за один большой шаг
const FALL_LIMIT = -30;     // провалился ниже — вернуть на старт

// Порог, за которым столкновения считаются по габаритному ящику, а не по
// самой геометрии. Число не из головы, а из замера сборки октодерева:
//
//   ровная сфера     16 000 тр →   199 мс   (12 мкс на треугольник)
//   скан TRELLIS     40 000 тр →  3943 мс   (98 мкс на треугольник)
//   скан TRELLIS    296 000 тр →  больше двух минут, вкладка не отвечает
//
// То есть линейной цены нет: на плотной сканированной сетке треугольники
// попадают сразу во много узлов, и дерево дробится куда глубже. Отсюда запас
// вниз. Практически это означает: рукотворные лёгкие сцены (та же локация
// из pipeline/blender/corridor.py) получают честные столкновения, а
// трёхсоттысячные сканы — коробку, и об этом написано в панели.
const OCTREE_TRI_LIMIT = 12000;

const bus = {
  el: {},                   // ссылки на разметку, заполняются при первом входе
  ready: false,
  active: false,
  url: null,                // какой GLB показывать
  loadedUrl: null,
};

// Слой столкновений. Октодерево собирает треугольники ПО СЛОЮ, а не по
// видимости (см. Octree.fromGraphNode: там layers.test, и только он), поэтому
// «спрятать пол» недостаточно — его надо снять со слоя. Заодно это решает
// подмену тяжёлой модели коробкой: коробка невидима, но столкновения даёт.
const COLLIDE = 1;

let renderer, scene, camera, controls, octree, world, model, envTexture;
let ground, grid, keyLight;
let isLocation = false;     // сцена, внутри которой стоят, а не предмет
let raf = 0, last = 0, fpsAcc = 0, fpsFrames = 0, fps = 0;
const keys = new Set();
const velocity = new THREE.Vector3();
const dirF = new THREE.Vector3();
const dirR = new THREE.Vector3();
const scratch = new THREE.Vector3();
const collider = new Capsule(new THREE.Vector3(0, FEET, 0),
                             new THREE.Vector3(0, EYE, 0), FEET);
let onFloor = false;
let colliderNote = "";       // чем считаются столкновения — показывается в панели
let startPoint = new THREE.Vector3(0, 0, 3);
let lastTris = 0, lastSize = new THREE.Vector3(1, 1, 1);

const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------- сцена

function build() {
  const canvas = $("walk-canvas");
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  // Тонмаппинг и экспозиция те же, что у model-viewer: два режима не должны
  // выглядеть как два разных продукта.
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.95;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0e0f12);
  // Туман вместо ручного гашения дальних линий: в вьюере край сетки прятали
  // двумя градиентами поверх холста, здесь это одна строка и работает в 3D.
  scene.fog = new THREE.Fog(0x0e0f12, 18, 90);

  camera = new THREE.PerspectiveCamera(70, 1, 0.05, 400);
  camera.rotation.order = "YXZ";

  world = new THREE.Group();
  scene.add(world);

  // Пол-подставка. Он же — опора для столкновений, поэтому настоящий меш,
  // а не только помощник-сетка. У локации свой пол, и тогда этот убирается:
  // два пола на одной высоте дают мерцание и лишние треугольники в дереве.
  ground = new THREE.Mesh(
    new THREE.PlaneGeometry(140, 140),
    new THREE.MeshStandardMaterial({ color: 0x23272f, roughness: 0.96, metalness: 0 }));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  ground.layers.enable(COLLIDE);
  scene.add(ground);

  grid = new THREE.GridHelper(140, 140, 0x9fb0c6, 0x39414e);
  grid.material.transparent = true;
  grid.material.opacity = 0.35;
  grid.position.y = 0.002;      // чуть выше пола, иначе z-fighting
  scene.add(grid);              // на слой столкновений не ставим: это линии

  keyLight = new THREE.DirectionalLight(0xffffff, 2.2);
  keyLight.position.set(4, 8, 5);
  keyLight.castShadow = true;
  keyLight.shadow.mapSize.set(1024, 1024);
  keyLight.shadow.camera.left = -6; keyLight.shadow.camera.right = 6;
  keyLight.shadow.camera.top = 6; keyLight.shadow.camera.bottom = -6;
  keyLight.shadow.camera.far = 30;
  keyLight.shadow.bias = -0.0015;
  scene.add(keyLight);
  scene.add(new THREE.AmbientLight(0xffffff, 0.15));

  controls = new PointerLockControls(camera, $("walk-stage"));
  controls.addEventListener("lock", () => { $("walk-lock").hidden = true; });
  controls.addEventListener("unlock", () => {
    keys.clear();                       // иначе клавиша остаётся «нажатой»
    if (bus.active) $("walk-lock").hidden = false;
  });
  $("walk-lock").addEventListener("click", () => controls.lock());

  octree = new Octree();

  // Тот же studio.hdr, что и у вьюера: свет собран в scripts/make_studio_hdr.py
  // по схеме из Blender, и повторять его вторым набором ламп незачем.
  new HDRLoader().load("/static/studio.hdr", (hdr) => {
    const pmrem = new THREE.PMREMGenerator(renderer);
    envTexture = pmrem.fromEquirectangular(hdr).texture;
    scene.environment = envTexture;
    hdr.dispose();
    pmrem.dispose();
  }, undefined, () => {
    // Молчать нельзя: сцена без окружения выглядит плоской, и причина
    // неочевидна. Свет от направленной лампы останется, но скажем прямо.
    note("студийная HDR-панорама не загрузилась — освещение неполное");
  });

  new ResizeObserver(resize).observe($("walk-stage"));
  document.addEventListener("keydown", onKey);
  document.addEventListener("keyup", onKey);
  window.addEventListener("blur", () => keys.clear());

  bus.ready = true;
  resize();
}

function resize() {
  if (!renderer) return;
  const el = $("walk-stage");
  const w = el.clientWidth || 1, h = el.clientHeight || 1;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

function note(text) {
  const el = $("walk-note");
  el.textContent = text || "";
  el.classList.toggle("warn", !!text);
}

// ------------------------------------------------------------------ модель

function disposeModel() {
  if (!model) return;
  world.remove(model);
  model.traverse((o) => {
    if (!o.isMesh) return;
    o.geometry.dispose();
    for (const m of [].concat(o.material)) {
      for (const k of ["map", "normalMap", "roughnessMap", "metalnessMap", "aoMap", "emissiveMap"]) {
        if (m[k]) m[k].dispose();
      }
      m.dispose();
    }
  });
  model = null;
}

async function loadModel(url) {
  disposeModel();
  if (!url) {
    // Пустой пол без объяснения читается как «режим сломался». У локации
    // GLB может не быть вовсе: corridor.py оставляет .blend и кадры Cycles.
    setLocation(false);
    rebuildOctree(0);
    $("walk-model").textContent = "нет GLB";
    note("у этой модели нет GLB — ходить не по чему. Локацию сначала выгружают: "
       + "blender -b СЦЕНА.blend -P pipeline/blender/export_glb.py -- --out .../model.glb");
    return;
  }
  note("");

  const gltf = await new GLTFLoader().loadAsync(url);
  model = gltf.scene;

  // Модель ставится НА пол и по центру: GLB приходят с началом координат где
  // попало, и без этого предмет оказывается либо вкопанным, либо висящим.
  const box = new THREE.Box3().setFromObject(model);
  const size = new THREE.Vector3(), centre = new THREE.Vector3();
  box.getSize(size); box.getCenter(centre);
  model.position.set(-centre.x, -box.min.y, -centre.z);

  let tris = 0;
  model.traverse((o) => {
    if (o.isLight) {
      // Свет из GLB (KHR_lights_punctual). У локации он свой и главный:
      // в коридоре светит одно солнце снаружи, и внутрь попадает только
      // через окна. Тени включаем сами — загрузчик их не ставит, а без них
      // свет проходит сквозь стены и коридор освещён как чистое поле.
      o.castShadow = true;
      if (o.shadow) {
        o.shadow.mapSize.set(2048, 2048);
        o.shadow.bias = -0.002;
        // Рамку тени обязательно под габарит сцены. По умолчанию у
        // направленного источника она ±5 м, и всё, что дальше, считается
        // затенённым: пятнадцатиметровый коридор был тёмным целиком, и
        // яркость не менялась от интенсивности солнца вовсе.
        const reach = Math.max(size.x, size.y, size.z);
        Object.assign(o.shadow.camera, {
          left: -reach, right: reach, top: reach, bottom: -reach,
          near: 0.5, far: reach * 6,
        });
        o.shadow.camera.updateProjectionMatrix();
      }
      // Интенсивность НЕ трогаем: в glTF она в люксах, и three начиная с
      // r155 считает направленный свет в тех же люксах — 28686 у солнца
      // коридора не ошибка экспорта, а его 42 Вт/м² в единицах формата.
      return;
    }
    if (!o.isMesh) return;
    // Прозрачное не отбрасывает тень: карта теней не знает про прозрачность,
    // и стёкла в окнах перекрывали единственный источник света наглухо.
    const clear = [].concat(o.material).some(
      (m) => m.transparent || (m.transmission || 0) > 0 || (m.opacity ?? 1) < 1);
    o.castShadow = !clear;
    o.receiveShadow = true;
    const g = o.geometry;
    tris += (g.index ? g.index.count : g.attributes.position.count) / 3;
  });

  world.add(model);
  lastTris = tris;
  lastSize = size;

  // Локация — то, внутрь чего входят, а не то, что обходят кругом. Отличаем
  // по габаритам: в человеческий рост и шире четырёх метров. Ошибиться тут
  // дёшево, а разница принципиальная — где поставить игрока.
  setLocation(size.y > 2.2 && Math.max(size.x, size.z) > 4, size);
  rebuildOctree(tris, size);

  if (isLocation) {
    // Внутрь, в середину пола, лицом вдоль длинной оси — иначе игрок
    // оказывается снаружи закрытой коробки и видит её глухую спину.
    startPoint.set(0, 0, 0);
    respawn();
    camera.rotation.set(0, size.x > size.z ? Math.PI / 2 : 0, 0, "YXZ");
  } else {
    // Предмет обходят: встаём на полтора его габарита и лицом к нему.
    startPoint.set(0, 0, Math.max(size.x, size.z) / 2 + Math.max(1.6, size.y * 1.5));
    respawn();
    camera.lookAt(0, Math.min(size.y * 0.6, EYE), 0);
  }

  $("walk-model").textContent =
    `${Math.round(tris / 1000)}k тр · ${size.x.toFixed(1)}×${size.y.toFixed(1)}×${size.z.toFixed(1)} м`
    + (isLocation ? " · локация" : "");
}

// Пол-подставка, сетка и подсветка нужны предмету и мешают локации: у той
// свой пол, свои стены и свой свет. Гасим их вместе, одним переключателем,
// чтобы не искать потом, где включилась половина.
function setLocation(on, size) {
  isLocation = on;
  ground.visible = !on;
  grid.visible = !on;
  if (on) ground.layers.disable(COLLIDE); else ground.layers.enable(COLLIDE);
  // Свою лампу не гасим совсем: если у локации света не оказалось, чёрный
  // экран объяснить нечем. Но приглушаем — главным должен быть её свет.
  keyLight.intensity = on ? 0.25 : 2.2;
  keyLight.castShadow = !on;

  // Студийная HDR внутри замкнутой локации светит СКВОЗЬ стены: карта
  // окружения затенения не знает вовсе, а в этой панораме источники ярче
  // единицы занимают 28% пикселей. Замер яркости кадра из середины коридора:
  //
  //   доля окружения   1     0.5    0.25   0.12   0.06   0.03    0
  //   яркость        0.94   0.88   0.61   0.31   0.17   0.10   0.03
  //   выжжено, %     89.2   50.0    0.3    0.1    0.1    0.1    0.1
  //   черноты, %        0      0      0      0      0   10.5   33.3
  //
  // При единице коридор — белое пятно, при нуле в нём только пятна солнца
  // из окон. 0.08 даёт среднюю яркость около 0.22 без пересветов и провалов.
  scene.environmentIntensity = on ? 0.08 : 1;
  if (on && size) {
    scene.fog.near = Math.max(6, Math.max(size.x, size.z) * 0.6);
    scene.fog.far = Math.max(size.x, size.z) * 2.5;
  } else {
    scene.fog.near = 18; scene.fog.far = 90;
  }
}

// Октодерево строится по настоящей геометрии, пока она не слишком тяжёлая.
// Тяжёлую заменяем габаритным ящиком: разбор трёхсот тысяч треугольников
// вешает вкладку на секунды, а для «не пройти сквозь предмет» ящика хватает.
// Подмена показывается в панели, а не делается молча.
function rebuildOctree(tris, size, byGeometry = tris <= OCTREE_TRI_LIMIT) {
  const t0 = performance.now();
  octree = new Octree();
  octree.layers.set(COLLIDE);      // собираем только помеченное, см. COLLIDE

  // Собирать дерево по всей сцене, а не по временной группе: перекладывание
  // объектов в новую группу в three ОТВЯЗЫВАЕТ их от прежнего родителя —
  // пол уехал бы из сцены вместе с ним. Слой решает это без перестановок.
  let proxy = null;
  if (model) {
    model.traverse((o) => {
      if (o.isMesh) byGeometry ? o.layers.enable(COLLIDE) : o.layers.disable(COLLIDE);
    });
    if (!byGeometry) {
      proxy = new THREE.Mesh(new THREE.BoxGeometry(
        Math.max(size.x, 0.05), Math.max(size.y, 0.05), Math.max(size.z, 0.05)));
      proxy.position.set(0, size.y / 2, 0);
      proxy.visible = false;       // невидимость столкновениям не мешает:
      proxy.layers.enable(COLLIDE);// октодерево смотрит на слой, не на visible
      scene.add(proxy);
    }
  }

  scene.updateMatrixWorld(true);
  octree.fromGraphNode(scene);

  if (proxy) { scene.remove(proxy); proxy.geometry.dispose(); }
  colliderNote = !model ? "только пол" : byGeometry ? "по геометрии" : "по габаритам";
  $("walk-collider").textContent = `${colliderNote} · ${Math.round(performance.now() - t0)} мс`;
}

// ------------------------------------------------------------------ физика

function onKey(e) {
  if (!bus.active) return;
  // По e.code, а не e.key: при русской раскладке key даёт «ц», «ф», «ы», «в»
  const down = e.type === "keydown";
  if (e.code === "Escape") return;                   // захват снимает браузер
  if (!/^(Key[WASDQE]|Space|Shift(Left|Right))$/.test(e.code)) return;
  if (down) e.preventDefault();
  down ? keys.add(e.code) : keys.delete(e.code);
}

function respawn() {
  collider.start.set(startPoint.x, FEET, startPoint.z);
  collider.end.set(startPoint.x, EYE, startPoint.z);
  collider.radius = FEET;
  velocity.set(0, 0, 0);
}

function collisions() {
  const hit = octree.capsuleIntersect(collider);
  onFloor = false;
  if (!hit) return;
  onFloor = hit.normal.y > 0;
  if (!onFloor) {
    // Гасим только ту часть скорости, что направлена в препятствие: иначе
    // касание стены останавливает и движение вдоль неё.
    velocity.addScaledVector(hit.normal, -hit.normal.dot(velocity));
  }
  if (hit.depth >= 1e-10) collider.translate(hit.normal.multiplyScalar(hit.depth));
}

function step(dt) {
  if (!onFloor) velocity.y -= GRAVITY * dt;
  velocity.addScaledVector(velocity, Math.exp(-(onFloor ? DRAG_GROUND : DRAG_AIR) * dt) - 1);

  const boost = keys.has("ShiftLeft") || keys.has("ShiftRight") ? SPRINT : 1;
  const gain = dt * DRAG_GROUND * SPEED * boost * (onFloor ? 1 : AIR_CONTROL);

  camera.getWorldDirection(dirF);
  dirF.y = 0;
  if (dirF.lengthSq() < 1e-8) dirF.set(0, 0, -1);
  dirF.normalize();
  dirR.copy(dirF).cross(camera.up).normalize();

  if (keys.has("KeyW")) velocity.addScaledVector(dirF, gain);
  if (keys.has("KeyS")) velocity.addScaledVector(dirF, -gain);
  if (keys.has("KeyD")) velocity.addScaledVector(dirR, gain);
  if (keys.has("KeyA")) velocity.addScaledVector(dirR, -gain);
  if (onFloor && keys.has("Space")) velocity.y = JUMP;

  collider.translate(scratch.copy(velocity).multiplyScalar(dt));
  collisions();
  camera.position.copy(collider.end);

  if (camera.position.y < FALL_LIMIT) respawn();
}

function tick(now) {
  raf = requestAnimationFrame(tick);
  const dt = Math.min((now - last) / 1000, 0.1);
  last = now;

  for (let i = 0; i < SUBSTEPS; i++) step(dt / SUBSTEPS);
  renderer.render(scene, camera);

  fpsAcc += dt; fpsFrames++;
  if (fpsAcc >= 0.4) { fps = Math.round(fpsFrames / fpsAcc); fpsAcc = 0; fpsFrames = 0; stats(); }
}

function stats() {
  const p = camera.position;
  $("walk-pos").textContent = `${p.x.toFixed(2)} ${p.y.toFixed(2)} ${p.z.toFixed(2)}`;
  $("walk-speed").textContent = `${Math.hypot(velocity.x, velocity.z).toFixed(2)} м/с`;
  $("walk-floor").textContent = onFloor ? "на полу" : "в воздухе";
  $("walk-fps").textContent = `${fps}`;
}

// -------------------------------------------------------------- наружу

async function enter(url) {
  bus.active = true;
  $("walk-stage").hidden = false;
  try {
    if (!bus.ready) build();
  } catch (e) {
    $("walk-error").hidden = false;
    $("walk-error").textContent =
      "сцена не поднялась: " + e.message +
      ". Вероятнее всего недоступен WebGL — проверь аппаратное ускорение в браузере.";
    return;
  }
  resize();

  // Сравнение без проверки на пустоту намеренно: переход на модель БЕЗ GLB
  // это тоже смена, и старую надо убрать. Иначе в сцене оставался предыдущий
  // предмет, а панель показывала его же — молча и не пойми почему.
  if (url !== bus.loadedUrl) {
    bus.loadedUrl = url;
    try {
      await loadModel(url);
    } catch (e) {
      bus.loadedUrl = null;
      note("модель не загрузилась: " + e.message);
    }
  }
  $("walk-lock").hidden = controls.isLocked;
  last = performance.now();
  if (!raf) raf = requestAnimationFrame(tick);
}

function exit() {
  bus.active = false;
  $("walk-stage").hidden = true;
  cancelAnimationFrame(raf);
  raf = 0;
  keys.clear();
  if (controls && controls.isLocked) controls.unlock();
}

function setModel(url) {
  bus.url = url;
  if (bus.active) enter(url);
}

// Наружу отдаётся не только переключение режима, но и намеренная отладочная
// ручка. Это заготовка панели разработки: ходить по состоянию сцены из
// консоли и из будущего интерфейса — рабочий сценарий, а не хак. Заодно
// это то, чего не давал model-viewer: там до камеры приходилось добираться
// через приватные символы и мириться с тем, что она переписывается сама.
window.walk = {
  enter, exit, setModel,
  debug: {
    state: () => ({
      pos: camera ? camera.position.toArray().map((n) => +n.toFixed(3)) : null,
      vel: velocity.toArray().map((n) => +n.toFixed(3)),
      speed: +Math.hypot(velocity.x, velocity.z).toFixed(3),
      onFloor, fps, keys: [...keys], collider: colliderNote, tris: lastTris,
    }),
    // Пошаговый прогон физики без кадров рендерера: так режим проверяется
    // числами, а не «на глаз побегал — вроде не проваливаюсь».
    step: (dt = 1 / 60, frames = 1) => {
      for (let f = 0; f < frames; f++) {
        for (let s = 0; s < SUBSTEPS; s++) step(dt / SUBSTEPS);
      }
    },
    press: (code, down = true) => (down ? keys.add(code) : keys.delete(code)),
    look: (yaw, pitch = 0) => { camera.rotation.set(pitch, yaw, 0, "YXZ"); },
    respawn,
    rebuild: (byGeometry) => rebuildOctree(lastTris, lastSize, byGeometry),
    // Рендерер отдаётся тоже, и это не мелочь: снимать показания чужим
    // рендерером нельзя — карта окружения принадлежит контексту того, кто её
    // создал, и в другом контексте она просто мертва. Замер яркости через
    // второй WebGLRenderer давал бессмыслицу именно поэтому.
    scene: () => ({ THREE, renderer, scene, camera, controls, octree, world, model, collider }),
  },
};
