"""MCP-сервер photo3d.

API спроектирован под работу агента, а не человека за GUI. Отсюда правила:

1. Один вызов - законченный результат. photo_to_3d сам делает препроцесс,
   генерацию, постобработку и рендер превью. Не нужно цеплять пять вызовов
   ради обычного сценария.
2. Инструмент возвращает картинки прямо в контекст. Без этого агент слеп и
   может только пересказывать чужие цифры вместо оценки результата.
3. Адресация короткими id, а по умолчанию - "last". Чаще всего речь о той
   модели, что только что сделали.
4. Вызов блокирующий, без очередей и опроса статуса. Подождать 60 секунд
   дешевле, чем жечь ходы на polling.
5. Ошибка несёт подсказку, что делать дальше, а не traceback.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

import anyio
from mcp.server.mcpserver import Image, MCPServer
from mcp.types import ToolAnnotations

from pipeline import paint as paint_mod
from pipeline import render, sculpt
from pipeline.engines import get_engine
from server import config
from server.errors import InputNotFound, PipelineError
from server.store import ModelStore

config.ensure_dirs()
store = ModelStore()

mcp = MCPServer(
    name="photo3d",
    version="0.1.0",
    instructions=(
        "Превращает фотографию в 3D-модель. Главный инструмент - photo_to_3d: "
        "он возвращает готовый GLB и рендеры с четырёх сторон прямо в контекст. "
        "Посмотри на эти рендеры и оцени результат сам: поехавшая геометрия, "
        "дыры и срезанные края видны глазом. Не устраивает - перезапусти с "
        "другим seed или mode='quality'. Модели адресуются коротким id, "
        "по умолчанию берётся последняя."
    ),
)

_WIN_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$")

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
GENERATES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False)


def _resolve_input(raw: str) -> Path:
    """Принимает имя файла в data/input, POSIX-путь или windows-путь D:\\...

    Windows-пути важны: их естественно называет и пользователь, и я сам,
    работая с той стороны, а сервер живёт в WSL.
    """
    raw = raw.strip().strip('"').strip("'")
    searched: list[str] = []

    m = _WIN_PATH.match(raw)
    if m:
        p = Path(f"/mnt/{m.group(1).lower()}/{m.group(2).replace(chr(92), '/')}")
        searched.append(str(p))
        if p.is_file():
            return p

    p = Path(raw)
    if p.is_absolute():
        searched.append(str(p))
        if p.is_file():
            return p

    for cand in (config.INPUT_DIR / raw, config.INPUT_DIR / p.name):
        searched.append(str(cand))
        if cand.is_file():
            return cand

    raise InputNotFound(raw, searched)


def _fmt_bytes(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} ГБ"


def _summary(model_id: str) -> str:
    m = store.meta(model_id)
    g = store.glb(model_id)
    stats = m.get("stats", {})
    lines = [
        f"{model_id} | движок {stats.get('engine', '?')}/{stats.get('mode', '?')} "
        f"seed={stats.get('seed', '?')} | {m.get('elapsed_sec', 0):.1f} c",
        f"геометрия: {stats.get('vertices', '?')} вершин, {stats.get('faces', '?')} полигонов, "
        f"замкнутая оболочка: {'да' if stats.get('watertight') else 'нет'}",
        f"GLB: {g} ({_fmt_bytes(g.stat().st_size) if g.exists() else 'нет файла'})",
    ]
    if m.get("source"):
        lines.append(f"исходник: {m['source']}")
    if m.get("render_engine"):
        lines.append(f"превью: {m.get('views', 0)} ракурсов, {m['render_engine']}")
    return "\n".join(lines)


def _view_images(model_id: str, limit: int = config.DEFAULT_VIEWS) -> list[Image]:
    """Равномерная выборка из полного оборота.

    На диске лежит два десятка кадров для веб-интерфейса, но агенту нужны
    ракурсы с разных сторон, а не плотная последовательность почти одинаковых
    картинок - они только раздувают контекст.
    """
    frames = store.views(model_id)
    if not frames:
        return []
    if len(frames) <= limit:
        picked = frames
    else:
        step = len(frames) / limit
        picked = [frames[int(i * step)] for i in range(limit)]
    return [Image(path=str(p)) for p in picked]


# --------------------------------------------------------------------------- #
# Инструменты
# --------------------------------------------------------------------------- #

@mcp.tool(annotations=GENERATES)
async def photo_to_3d(
    image: str,
    mode: str = "fast",
    seed: int = 0,
    views: int = 4,
) -> list:
    """Сделать 3D-модель из фотографии и показать результат.

    Делает всё за один вызов: читает фото, строит меш, экспортирует GLB и
    рендерит превью с нескольких сторон. Рендеры возвращаются картинками -
    посмотри на них и реши, годится ли результат.

    image: имя файла в data/input, либо полный путь (в том числе D:\\папка\\фото.jpg)
    mode:  fast - быстро и грубо, quality - плотнее сетка и дольше
    seed:  для повторяемости; меняй, если результат не понравился
    views: сколько ракурсов вернуть в контекст. Полный оборот на диск
           пишется всегда - по нему крутится модель в веб-интерфейсе
    """
    src = _resolve_input(image)
    model_id, mdir = store.create()
    started = time.time()

    shutil.copy2(src, mdir / f"input{src.suffix.lower()}")
    store.log(model_id, f"источник: {src}")

    engine = get_engine(config.ENGINE)
    glb = mdir / "model.glb"

    def _work():
        stats = engine.generate(src, glb, seed=seed, mode=mode)
        frames, rengine, log = render.render_turntable(
            glb, mdir / "views", views=config.SPIN_FRAMES, res=config.PREVIEW_RES
        )
        return stats, frames, rengine, log

    stats, frames, rengine, blog = await anyio.to_thread.run_sync(_work)
    store.log(model_id, blog)

    store.write_meta(model_id, {
        "source": str(src),
        "stats": stats,
        "elapsed_sec": time.time() - started,
        "render_engine": rengine,
        "views": len(frames),
    })

    note = ""
    if engine.needs_gpu is False and stats.get("engine") == "stub":
        note = (
            "\n\nЭто ЗАГЛУШКА: силуэт фотографии надут в объём, реальной "
            "реконструкции нет. Она нужна, чтобы проверить работу всей цепочки. "
            "Настоящая геометрия появится после подключения TRELLIS."
        )
    return [_summary(model_id) + note, *_view_images(model_id, limit=views)]


@mcp.tool(annotations=READ_ONLY)
async def render_model(model_id: str = "last", views: int = 4, res: int = 0,
                       style: str = "clay") -> list:
    """Перерендерить превью модели и показать картинки.

    style задаёт, что именно смотрим:
      clay   - серая глина с подчёркиванием впадин, без света. Для оценки ФОРМЫ:
               настоящее освещение прячет дыры и складки за бликами
      color  - показать материал и текстуру, быстро и без света
      beauty - полноценная сцена: три источника света, подложка с тенью.
               Для показа результата. Медленнее остальных

    res: 0 - размер по умолчанию (512). Больше - подробнее, но тяжелее контекст.
    """
    if style not in render.STYLE_ENGINES:
        raise PipelineError("render", f"стиль {style!r} неизвестен",
                            hint="доступны: " + ", ".join(render.STYLE_ENGINES))
    mid = store.resolve(model_id)
    glb = store.glb(mid)
    if not glb.exists():
        raise PipelineError(
            "lookup", f"у модели {mid} нет model.glb",
            hint="сгенерируй заново через photo_to_3d",
        )

    def _work():
        return render.render_turntable(
            glb, store.dir(mid) / "views",
            views=config.SPIN_FRAMES, res=res or config.PREVIEW_RES, style=style,
        )

    frames, rengine, blog = await anyio.to_thread.run_sync(_work)
    store.log(mid, blog)
    meta = store.meta(mid)
    meta.update({"render_engine": rengine, "views": len(frames), "style": style})
    store.write_meta(mid, meta)
    return [f"{mid}: полный оборот из {len(frames)} кадров, стиль {style}, {rengine}",
            *_view_images(mid, limit=views)]


@mcp.tool(annotations=GENERATES)
async def paint_model(
    model_id: str = "last",
    color: str = "",
    from_photo: bool = False,
    metallic: float = 0.0,
    roughness: float = 0.5,
    style: str = "beauty",
) -> list:
    """Покрасить модель и показать результат.

    Меняет модель НА МЕСТЕ, новой карточки не появляется: открытый
    веб-интерфейс перерисует именно её, так что человек за экраном видит
    изменение сразу.

    color:      название («красный», «золото», «терракота»…), #rrggbb
                или «r,g,b» в долях единицы
    from_photo: вместо сплошного цвета спроецировать на модель исходный кадр.
                Честное ограничение: бока и спина получат растянутый цвет —
                одного ракурса на всю поверхность не хватает
    metallic:   0 — диэлектрик (пластик, керамика), 1 — металл
    roughness:  0 — зеркало, 1 — полностью матовый
    style:      каким стилем перерисовать превью; по умолчанию beauty,
                потому что без света покраску толком не оценить
    """
    mid = store.resolve(model_id)
    mdir = store.dir(mid)
    glb = store.glb(mid)
    if not glb.exists():
        raise PipelineError("paint", f"у модели {mid} нет model.glb",
                            hint="сгенерируй её заново через photo_to_3d")

    photo = None
    if from_photo:
        photo = next(iter(sorted(mdir.glob("input.*"))), None)
        if photo is None:
            raise PipelineError(
                "paint", f"у модели {mid} не сохранён исходный кадр",
                hint="покрась сплошным цветом: color='терракота'",
            )
    if not color and not from_photo:
        raise PipelineError(
            "paint", "не указано, чем красить",
            hint="задай color (например 'терракота') либо from_photo=True. "
                 "Доступные названия: " + ", ".join(sorted(paint_mod.NAMED_COLORS)),
        )

    started = time.time()

    def _work():
        plog = paint_mod.paint(glb, glb, color=color, photo=photo,
                               metallic=metallic, roughness=roughness)
        frames, rengine, rlog = render.render_turntable(
            glb, mdir / "views", views=config.SPIN_FRAMES,
            res=config.PREVIEW_RES, style=style,
        )
        return plog, frames, rengine, rlog

    plog, frames, rengine, rlog = await anyio.to_thread.run_sync(_work)
    store.log(mid, plog)
    store.log(mid, rlog)

    meta = store.meta(mid)
    meta.update({
        "render_engine": rengine,
        "views": len(frames),
        "style": style,
        "paint": {
            "color": color or None,
            "from_photo": bool(from_photo),
            "metallic": metallic,
            "roughness": roughness,
        },
    })
    store.write_meta(mid, meta)

    what = "исходное фото проекцией" if from_photo else f"цвет {color!r}"
    return [
        f"{mid} покрашена на месте: {what}, "
        f"металличность {metallic}, шероховатость {roughness}\n"
        f"превью перерисовано стилем {style} ({rengine}), "
        f"{len(frames)} кадров за {time.time() - started:.1f} c",
        *_view_images(mid),
    ]


@mcp.tool(annotations=READ_ONLY)
def inspect_model(model_id: str = "last") -> str:
    """Числа по модели: полигоны, габариты, замкнутость, размер файла, пути.

    Текст без картинок - когда нужны факты, а не визуальная оценка.
    """
    mid = store.resolve(model_id)
    import trimesh  # локальный импорт: тяжёлый, а нужен не всегда

    out = [_summary(mid)]
    glb = store.glb(mid)
    if glb.exists():
        mesh = trimesh.load(glb, force="mesh")
        ex = mesh.extents
        out.append(
            f"габариты: {ex[0]:.3f} x {ex[1]:.3f} x {ex[2]:.3f} "
            f"(объём оболочки {mesh.volume:.4f})"
        )
        out.append(f"вырожденных граней: {int((mesh.area_faces == 0).sum())}")
    out.append(f"папка: {store.dir(mid)}")
    return "\n".join(out)


@mcp.tool(annotations=READ_ONLY)
def list_models(limit: int = 10) -> str:
    """Последние сделанные модели, свежие сверху."""
    ids = store.ids()[:limit]
    if not ids:
        return "моделей пока нет - начни с photo_to_3d"
    rows = []
    for mid in ids:
        m = store.meta(mid)
        s = m.get("stats", {})
        src = Path(m.get("source", "?")).name
        rows.append(
            f"{mid}  {s.get('engine', '?'):8s} {s.get('faces', '?'):>8} полиг.  {src}"
        )
    return f"всего моделей: {len(store.ids())}\n" + "\n".join(rows)


@mcp.tool(annotations=GENERATES)
def export_model(model_id: str = "last", dest: str = "") -> str:
    """Положить GLB туда, где его заберёт пользователь.

    dest: путь назначения; принимает и windows-путь. Пустой - положит в
    data/output/exported/<id>.glb
    """
    mid = store.resolve(model_id)
    glb = store.glb(mid)
    if not glb.exists():
        raise PipelineError("export", f"у {mid} нет model.glb", hint="сгенерируй заново")

    if dest:
        m = _WIN_PATH.match(dest.strip().strip('"'))
        target = Path(f"/mnt/{m.group(1).lower()}/{m.group(2).replace(chr(92), '/')}") if m else Path(dest)
        if target.is_dir() or not target.suffix:
            target = target / f"{mid}.glb"
    else:
        target = config.OUTPUT_DIR / "exported" / f"{mid}.glb"

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(glb, target)
    return f"{mid} -> {target} ({_fmt_bytes(target.stat().st_size)})"


@mcp.tool(annotations=GENERATES)
async def prepare_for_sculpting(
    model_id: str = "last",
    target_faces: int = 5000,
) -> list:
    """Превратить модель в базовую сетку, пригодную для лепки, и показать её.

    Сырая модель после генератора для скульптинга не годится: треугольный суп,
    разрывы, неманифолдная геометрия — подразделение по такой ломается.
    Инструмент чинит меш (pymeshlab) и перестраивает оболочку вокселями
    (Blender): на выходе замкнутая поверхность равномерной плотности,
    целиком из четырёхугольников.

    Результат сохраняется отдельной моделью, исходная остаётся нетронутой —
    их удобно сравнивать рядом.

    target_faces: плотность базовой сетки. 3000–8000 — типичный диапазон:
                  достаточно грубо, чтобы подразделять вверх при лепке.
    """
    src_id = store.resolve(model_id)
    src_glb = store.glb(src_id)
    if not src_glb.exists():
        raise PipelineError("sculpt", f"у модели {src_id} нет model.glb",
                            hint="сгенерируй её заново через photo_to_3d")

    new_id, mdir = store.create()
    started = time.time()
    for p in store.dir(src_id).glob("input.*"):
        shutil.copy2(p, mdir / p.name)

    def _work():
        result, info = sculpt.prepare(src_glb, mdir, target_faces=target_faces)
        shutil.move(str(result), str(mdir / "model.glb"))
        frames, rengine, rlog = render.render_turntable(
            mdir / "model.glb", mdir / "views",
            views=config.SPIN_FRAMES, res=config.PREVIEW_RES,
        )
        return info, frames, rengine, rlog

    info, frames, rengine, rlog = await anyio.to_thread.run_sync(_work)
    store.log(new_id, info.get("log", ""))
    store.log(new_id, rlog)

    rep, rem = info["repair"], info["remesh"]
    final = rem.get("final", {})
    health = rem.get("health", {})
    store.write_meta(new_id, {
        "source": str(src_glb),
        "derived_from": src_id,
        "stats": {
            "engine": "sculpt-prep",
            "mode": f"{target_faces} граней",
            "seed": 0,
            "vertices": final.get("vertices"),
            "faces": final.get("faces"),
            "watertight": health.get("watertight", False),
        },
        "elapsed_sec": time.time() - started,
        "render_engine": rengine,
        "views": len(frames),
    })

    lines = [
        f"{new_id} — базовая сетка из {src_id}",
        f"ремонт: неманифолдных рёбер {rep['before'].get('non_manifold_edges')} → "
        f"{rep['after'].get('non_manifold_edges')}, "
        f"кусков {rep['before'].get('components')} → {rep['after'].get('components')}, "
        f"дыр {rep['after'].get('holes')}",
        f"сетка: {final.get('faces')} граней "
        f"(квадов {final.get('quads')}, треугольников {final.get('tris')}, "
        f"n-гонов {final.get('ngons')}), запрошено {target_faces}",
        f"замкнутая оболочка: {'да' if health.get('watertight') else 'нет'}, "
        f"граничных рёбер {health.get('boundary_edges')}",
        f"GLB: {mdir / 'model.glb'} | {time.time() - started:.1f} c",
    ]
    if rep["skipped"]:
        lines.append("пропущенные фильтры: " + "; ".join(rep["skipped"]))
    return ["\n".join(lines), *_view_images(new_id)]


@mcp.tool(annotations=READ_ONLY)
def status() -> str:
    """Состояние сервера: движок, Blender, GPU, диск, число моделей.

    Первое, что стоит вызвать, если что-то ведёт себя странно.
    """
    import subprocess

    lines = [
        f"движок генерации: {config.ENGINE}",
        f"корень проекта:   {config.ROOT}",
        f"Blender:          {config.BLENDER} "
        f"({'найден' if config.BLENDER.exists() else 'НЕ НАЙДЕН'})",
        f"моделей в базе:   {len(store.ids())}",
    ]
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
        )
        lines.append(f"GPU:              {r.stdout.strip() or 'нет ответа'}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"GPU:              недоступна ({type(exc).__name__})")

    try:
        st = os.statvfs(config.DATA)
        free = st.f_bavail * st.f_frsize
        lines.append(f"свободно на диске: {_fmt_bytes(free)}")
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines)


def run() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run()
