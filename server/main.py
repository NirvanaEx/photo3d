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

from bridge import shot_scene as shots
from pipeline import bake
from pipeline import paint as paint_mod
from pipeline import smooth as smooth_mod
from pipeline import preprocess, render, sculpt
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


def _frames_for(spin: bool, views: int = config.DEFAULT_VIEWS) -> int:
    """Сколько кадров рисовать на диск.

    Полный оборот нужен веб-интерфейсу, чтобы модель крутилась перетаскиванием,
    и стоит он около 45 секунд на Cycles. Агенту же в контекст уходит четыре
    картинки. Пока идёт подбор - покраска, сглаживание, - платить сорок пять
    секунд за каждую попытку незачем: рисуем ровно то, что уйдёт в ответ,
    и говорим, что оборот теперь неполный.
    """
    if spin:
        return config.SPIN_FRAMES
    return max(1, min(views, config.SPIN_FRAMES))


def _spin_note(count: int) -> str:
    """Предупреждение о неполном обороте. Молчать нельзя: человек за экраном
    увидит рваное вращение и пойдёт искать поломку там, где её нет."""
    if count >= config.SPIN_FRAMES:
        return ""
    return (f"\nна диске {count} кадра вместо {config.SPIN_FRAMES} — вращение "
            f"в веб-интерфейсе будет рваным. Вернуть: render_model(spin=True)")


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

@mcp.tool(annotations=READ_ONLY)
async def check_photo(image: str) -> list:
    """Посмотреть, что получится из кадра, НЕ занимая видеокарту.

    Снимает фон и показывает силуэт, который уйдёт в генератор, вместе с
    замерами и предупреждениями. Идёт секунду-две на процессоре, тогда как
    неудачная генерация стоит четырёх минут работы GPU — если кадр вызывает
    сомнения, дешевле сначала спросить здесь.

    Смотри на возвращённую картинку, а не только на числа. Часть свойств
    кадра числами не ловится: плоский предмет — фрагмент стены, панно,
    вывеска — по силуэту неотличим от объёмного, а модель всегда сворачивает
    его в замкнутую оболочку, то есть в бочку. Это свойство задачи, а не сбой:
    по одному снимку глубину взять неоткуда. Видно это только глазом.

    image: имя файла в data/input либо полный путь, в том числе D:\\папка\\фото.jpg
    """
    src = _resolve_input(image)
    started = time.time()

    def _work():
        m = preprocess.measure(src)
        shot = preprocess.preview(
            m.pop("_rgba"), config.CACHE_DIR / "checks" / f"{src.stem}.png")
        return m, shot

    m, shot = await anyio.to_thread.run_sync(_work)
    warns = preprocess.verdict(m)

    lines = [
        f"{src.name}: кадр {m['кадр'][0]}×{m['кадр'][1]}, "
        f"маска — {m['источник_маски']}",
        f"предмет занимает {m['доля_кадра']:.1%} кадра, силуэт "
        f"{m['габарит_силуэта'][0]}×{m['габарит_силуэта'][1]} точек, "
        f"заполняет свою рамку на {m['заполнение_рамки']:.0%}",
        # Справочно, порога тут нет: величина говорит о мелкой фактуре, а не
        # о резкости, и ровная заливка даёт низкое значение при отличном снимке.
        f"мелкой фактуры: {m['фактура']:.0f} "
        f"(у примеров, вышедших хорошо, от 384 до 7251)",
    ]
    if warns:
        lines.append("")
        lines.append("на что обратить внимание:")
        lines += [f"  • {w}" for w in warns]
    else:
        lines.append("")
        lines.append("замеры не возражают — решай по картинке силуэта")
    lines.append(f"\n{time.time() - started:.1f} c, видеокарта не занималась")

    return ["\n".join(lines), Image(path=str(shot))]


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

    Идёт около четырёх с половиной минут вместе с постановочным рендером
    оборота. Вызов
    блокирующий, опрашивать статус не надо.

    image: имя файла в data/input, либо полный путь (в том числе D:\\папка\\фото.jpg)
           Фон снимать заранее не нужно, но если у картинки уже есть
           альфа-канал, он будет использован как есть - готовая маска обычно
           точнее автоматической
    mode:  draft   - черновик за ~2 мин: 6 шагов сэмплера вместо 12,
                     текстура 1024, сетка 15 тысяч граней. Форму и ракурс
                     видно, текстура грубая. Нужен, чтобы понять, тот ли
                     вообще вышел предмет, и сменить seed НЕ дожидаясь
                     полного прогона
           fast    - ~4.5 мин: текстура 2048, сетка 40 тысяч
           quality - ~5 мин: текстура 4096, сетка 80 тысяч

           Порядок работы, который экономит больше всего: сначала draft,
           посмотреть на силуэт, при нужде сменить seed ещё раз-два, и уже
           понравившийся seed прогнать в fast или quality
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
                       style: str = "", spin: bool = True) -> list:
    """Перерендерить превью модели и показать картинки.

    style задаёт, что именно смотрим:
      beauty - полноценная сцена: три источника света, подложка с тенью.
               Идёт по умолчанию: у моделей TRELLIS настоящие PBR-материалы,
               и показывать их надо со светом
      clay   - серая глина с подчёркиванием впадин, без света. Для оценки ФОРМЫ:
               настоящее освещение прячет дыры и складки за бликами
      color  - материал и текстура без света, вдвое быстрее beauty

    res:  0 - размер по умолчанию (512). Больше - подробнее, но тяжелее контекст.
    spin: рисовать полный оборот (24 кадра, ~45 c на beauty) или только те
          views, что уйдут в ответ (~7 c). Оборот нужен веб-интерфейсу для
          вращения перетаскиванием; для быстрого взгляда он лишний.
    """
    style = style or config.PREVIEW_STYLE
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

    count = _frames_for(spin, views)
    started = time.time()

    def _work():
        return render.render_turntable(
            glb, store.dir(mid) / "views",
            views=count, res=res or config.PREVIEW_RES, style=style,
        )

    frames, rengine, blog = await anyio.to_thread.run_sync(_work)
    store.log(mid, blog)
    meta = store.meta(mid)
    meta.update({"render_engine": rengine, "views": len(frames), "style": style})
    store.write_meta(mid, meta)
    what = "полный оборот" if spin else "быстрый набор"
    return [f"{mid}: {what} из {len(frames)} кадров, стиль {style}, {rengine}, "
            f"{time.time() - started:.1f} c" + _spin_note(len(frames)),
            *_view_images(mid, limit=views)]


@mcp.tool(annotations=READ_ONLY)
async def look_at(
    model_id: str = "last",
    azimuth: float = 0,
    elevation: float | None = None,
    zoom: float = 1.0,
    focus: float | None = None,
    res: int = 768,
    style: str = "",
) -> list:
    """Снять модель с одного заданного ракурса, при желании крупным планом.

    Превью показывает фигуру целиком в 512 точках, и на голову там приходится
    десятков шесть - судить по такой картинке о лице нельзя. Этот инструмент
    снимает ОДИН кадр (~3 c против ~45 c за оборот) и позволяет подойти ближе
    к тому месту, где что-то не так.

    azimuth:   поворот модели в градусах. Совпадает с номерами кадров превью:
               0 - тот же ракурс, что первый кадр, 180 - вид сзади
    elevation: наклон камеры в градусах. Пусто - как на превью (около 20°),
               0 - строго сбоку, 80 - почти сверху, отрицательный - снизу
    zoom:      увеличение. 1 - модель целиком, 3-4 - голова фигуры в кадре.
               Приближает длинный фокус, а не подъезд камеры: перспектива не
               искажается и ближние части не срезаются
    focus:     на какой высоте модели держать центр кадра: 0 - низ, 0.5 -
               середина (по умолчанию), 1 - самый верх. Лицо обычно 0.85-0.95
    res:       размер кадра. 768 по умолчанию; для мелких деталей 1024-1536,
               но контекст тяжелеет квадратично
    style:     beauty / clay / color. Пусто - стиль этой модели. Для оценки
               ФОРМЫ бери clay: свет прячет дыры и складки за бликами

    Лицо фигуры целиком: zoom=3.5, focus=0.9. Затылок: azimuth=180 к тому же.
    """
    mid = store.resolve(model_id)
    glb = store.glb(mid)
    if not glb.exists():
        raise PipelineError("look", f"у модели {mid} нет model.glb",
                            hint="сгенерируй её заново через photo_to_3d")

    meta = store.meta(mid)
    use_style = style or meta.get("style") or config.PREVIEW_STYLE
    if use_style not in render.STYLE_ENGINES:
        raise PipelineError("look", f"стиль {use_style!r} неизвестен",
                            hint="доступны: " + ", ".join(render.STYLE_ENGINES))

    # Имя собирается из параметров: одинаковые кадры перезаписывают себя,
    # разные лежат рядом и их можно сравнить. Кладём в looks/, а не в views/ -
    # там оборот, по которому крутится модель в вебе, и крупный план в этом
    # ряду сломал бы вращение.
    # Точка заменяется на "p", а не выбрасывается: иначе увеличение 3.5 и 35
    # дали бы одно имя "z35" и молча затирали друг друга. Точку в имени файла
    # не оставляем - Blender дописывает расширение сам, и хвост вида ".5_f0"
    # ему лучше не показывать.
    def _tag(prefix: str, value: float | None) -> str:
        return "" if value is None else f"_{prefix}{value:g}".replace(".", "p")

    name = (f"az{int(round(azimuth)) % 360:03d}"
            + _tag("el", elevation) + _tag("z", zoom if zoom != 1.0 else None)
            + _tag("f", focus) + f"_{use_style}")
    out_png = store.dir(mid) / "looks" / f"{name}.png"
    started = time.time()

    def _work():
        return render.render_view(
            glb, out_png, azimuth=azimuth, elevation=elevation,
            zoom=zoom, focus=focus, res=res, style=use_style,
        )

    path, rengine, rlog = await anyio.to_thread.run_sync(_work)
    store.log(mid, rlog)

    where = f"азимут {azimuth:g}°"
    if elevation is not None:
        where += f", наклон {elevation:g}°"
    if zoom != 1.0:
        where += f", увеличение {zoom:g}×"
    if focus is not None:
        where += f", центр на высоте {focus:g}"
    return [f"{mid}: {where}; стиль {use_style} ({rengine}), {res} px, "
            f"{time.time() - started:.1f} c\n{path}",
            Image(path=str(path))]


@mcp.tool(annotations=GENERATES)
async def paint_model(
    model_id: str = "last",
    color: str = "",
    from_photo: bool = False,
    metallic: float = 0.0,
    roughness: float = 0.5,
    style: str = "beauty",
    spin: bool = False,
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
    spin:       перерисовать полный оборот из 24 кадров (~45 c) вместо четырёх
                (~7 c). По умолчанию НЕ рисуется: цвет подбирают итерациями,
                и платить сорок пять секунд за каждую пробу незачем.
                Включи на последней, удачной покраске — тогда и в вебе
                будет крутиться правильная
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
    count = _frames_for(spin)

    def _work():
        plog = paint_mod.paint(glb, glb, color=color, photo=photo,
                               metallic=metallic, roughness=roughness)
        frames, rengine, rlog = render.render_turntable(
            glb, mdir / "views", views=count,
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
        f"{len(frames)} кадров за {time.time() - started:.1f} c"
        + _spin_note(len(frames)),
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
async def smooth_model(
    model_id: str = "last",
    strength: float = 0.6,
    iterations: int = 12,
    subdivide: int = 0,
    method: str = "preserve",
    style: str = "",
    spin: bool = False,
) -> list:
    """Сгладить модель и показать результат.

    Убирает гранёность, ступеньки и рваный контур. Меняет модель НА МЕСТЕ,
    материал и покраска сохраняются — открытый веб-интерфейс перерисует
    именно её.

    strength:   0..1, сила сглаживания
    iterations: сколько проходов; больше — глаже и медленнее
    subdivide:  0..3 уровня подразделения ПЕРЕД сглаживанием. Делает силуэт
                по-настоящему круглым, но каждый уровень учетверяет число
                граней — на плотной сетке лучше оставить 0
    method:     preserve — бережно, силуэт почти не «сдувается»;
                simple — сильнее, но модель немного усыхает
    style:      чем перерисовать превью; пусто — оставить прежний стиль модели
    spin:       перерисовать полный оборот (~45 c) вместо четырёх кадров (~7 c).
                Силу сглаживания подбирают в несколько заходов, поэтому по
                умолчанию оборот не рисуется — включи на последнем
    """
    mid = store.resolve(model_id)
    mdir = store.dir(mid)
    glb = store.glb(mid)
    if not glb.exists():
        raise PipelineError("smooth", f"у модели {mid} нет model.glb",
                            hint="сгенерируй её заново через photo_to_3d")

    meta = store.meta(mid)
    use_style = style or meta.get("style") or config.PREVIEW_STYLE
    if use_style not in render.STYLE_ENGINES:
        raise PipelineError("smooth", f"стиль {use_style!r} неизвестен",
                            hint="доступны: " + ", ".join(render.STYLE_ENGINES))
    started = time.time()
    count = _frames_for(spin)

    def _work():
        st = smooth_mod.smooth(glb, glb, strength=strength, iterations=iterations,
                               subdivide=subdivide, method=method)
        frames, rengine, rlog = render.render_turntable(
            glb, mdir / "views", views=count,
            res=config.PREVIEW_RES, style=use_style,
        )
        return st, frames, rengine, rlog

    st, frames, rengine, rlog = await anyio.to_thread.run_sync(_work)
    store.log(mid, st.get("log", ""))
    store.log(mid, rlog)

    stats = meta.get("stats", {})
    stats.update({"vertices": st["after"]["vertices"], "faces": st["after"]["faces"]})
    meta.update({"stats": stats, "render_engine": rengine,
                 "views": len(frames), "style": use_style,
                 "smooth": {"strength": strength, "iterations": iterations,
                            "subdivide": subdivide, "method": method}})
    store.write_meta(mid, meta)

    shrink = st.get("shrink_percent", [0, 0, 0])
    return [
        f"{mid} сглажена на месте: {method}, сила {strength}, "
        f"проходов {iterations}, подразделений {subdivide}\n"
        f"геометрия: {st['before']['faces']} → {st['after']['faces']} граней, "
        f"{st['before']['vertices']} → {st['after']['vertices']} вершин\n"
        f"усадка габаритов: {shrink[0]}% / {shrink[1]}% / {shrink[2]}% по осям\n"
        f"превью перерисовано стилем {use_style} ({rengine}) за "
        f"{time.time() - started:.1f} c" + _spin_note(len(frames)),
        *_view_images(mid),
    ]


@mcp.tool(annotations=GENERATES)
async def prepare_for_sculpting(
    model_id: str = "last",
    target_faces: int = 5000,
    keep_texture: bool = True,
    style: str = "",
) -> list:
    """Превратить модель в базовую сетку, пригодную для лепки, и показать её.

    Сырая модель после генератора для скульптинга не годится: треугольный суп,
    разрывы, неманифолдная геометрия — подразделение по такой ломается.
    Инструмент чинит меш (pymeshlab) и перестраивает оболочку вокселями
    (Blender): на выходе замкнутая поверхность равномерной плотности,
    целиком из четырёхугольников.

    Результат сохраняется отдельной моделью, исходная остаётся нетронутой —
    их удобно сравнивать рядом.

    target_faces:  плотность базовой сетки. 3000–8000 — типичный диапазон:
                   достаточно грубо, чтобы подразделять вверх при лепке.
    keep_texture:  перенести внешний вид с исходной модели. Перестройка даёт
                   новую сетку, к которой старая развёртка не относится, так
                   что без переноса покраска и текстура теряются. Однородный
                   материал копируется мгновенно, текстурный запекается.
    style:         чем перерисовать превью. Пусто — унаследовать стиль
                   исходной модели: иначе перенесённая покраска показывалась бы
                   глиняной, и было бы неясно, уцелела она или нет.
    """
    src_id = store.resolve(model_id)
    src_glb = store.glb(src_id)
    if not src_glb.exists():
        raise PipelineError("sculpt", f"у модели {src_id} нет model.glb",
                            hint="сгенерируй её заново через photo_to_3d")

    src_meta = store.meta(src_id)
    use_style = style or src_meta.get("style") or config.PREVIEW_STYLE
    if use_style not in render.STYLE_ENGINES:
        raise PipelineError("sculpt", f"стиль {use_style!r} неизвестен",
                            hint="доступны: " + ", ".join(render.STYLE_ENGINES))

    new_id, mdir = store.create()
    started = time.time()
    for p in store.dir(src_id).glob("input.*"):
        shutil.copy2(p, mdir / p.name)

    def _work():
        result, info = sculpt.prepare(src_glb, mdir, target_faces=target_faces)
        if keep_texture:
            info["bake"] = bake.transfer(src_glb, result, mdir / "model.glb")
        else:
            shutil.move(str(result), str(mdir / "model.glb"))
        frames, rengine, rlog = render.render_turntable(
            mdir / "model.glb", mdir / "views",
            views=config.SPIN_FRAMES, res=config.PREVIEW_RES, style=use_style,
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
        "style": use_style,
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

    bk = info.get("bake")
    if bk:
        mode = {"material-copy": "материал перенесён без запекания",
                "bake": "текстура запечена на новую развёртку",
                "none": "переносить было нечего"}.get(bk.get("mode"), bk.get("mode"))
        line = f"внешний вид: {mode}"
        if bk.get("mode") == "bake":
            line += (f", {bk.get('device', '?')}, "
                     f"{'непустая' if bk.get('looks_baked') else 'ПУСТАЯ — проверь'}")
        lines.append(line)
        if bk.get("note"):
            lines.append(f"  {bk['note']}")
    elif not keep_texture:
        lines.append("внешний вид НЕ переносился (keep_texture=False)")

    return ["\n".join(lines), *_view_images(new_id)]


def _trellis_status() -> list[str]:
    """Готовность генератора по частям.

    Одной строкой «движок trellis» не обойтись: сломаться может образ, веса,
    кодировщик или конфиг, и лечится каждое по-своему. Проверяется наличие
    файлов, а не запуск: status обязан отвечать мгновенно и не занимать
    видеокарту.
    """
    import json
    import subprocess

    out: list[str] = ["TRELLIS.2:"]
    main = config.TRELLIS_WEIGHTS / "TRELLIS.2-4B"
    cfg_path = main / "pipeline.json"

    try:
        r = subprocess.run(["docker", "image", "inspect", config.TRELLIS_IMAGE,
                            "--format", "{{.Size}}"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            out.append(f"  образ:      {config.TRELLIS_IMAGE}, "
                       f"{_fmt_bytes(int(r.stdout.strip()))}")
        else:
            out.append(f"  образ:      НЕТ ({config.TRELLIS_IMAGE}). "
                       "Собрать: docker build -t photo3d/trellis:1 docker/")
    except Exception as exc:  # noqa: BLE001
        out.append(f"  образ:      проверить не удалось ({type(exc).__name__})")

    if cfg_path.exists():
        try:
            args = json.loads(cfg_path.read_text(encoding="utf-8"))["args"]
            models = args["models"]
            missing = [k for k, v in models.items()
                       if not (main / f"{v}.safetensors").exists()]
            # Считаем только то, что реально грузится. На диске могут лежать
            # и веса других разрешений - они скачаны, но конфигу не нужны, и
            # включать их в цифру значило бы врать о расходе.
            used = sum((main / f"{v}.safetensors").stat().st_size
                       for v in models.values()
                       if (main / f"{v}.safetensors").exists())
            spare = sum(f.stat().st_size for f in main.rglob("*.safetensors")) - used
            out.append(f"  веса:       {len(models)} моделей, {_fmt_bytes(used)}"
                       + (f" (+{_fmt_bytes(spare)} про запас)" if spare > 1e8 else "")
                       + (f", НЕ ХВАТАЕТ: {missing}" if missing else ""))
            out.append(f"  режим:      {args.get('default_pipeline_type')}, "
                       f"low_vram={args.get('low_vram')}")
            dino = Path(args["image_cond_model"]["args"]["model_name"])
            # в конфиге путь контейнерный (/weights/...), на хосте он другой
            host_dino = config.TRELLIS_WEIGHTS / dino.name
            out.append(f"  кодировщик: {dino} "
                       f"({'на месте' if host_dino.exists() else 'НЕ НАЙДЕН НА ХОСТЕ'})")
        except Exception as exc:  # noqa: BLE001
            out.append(f"  конфиг:     повреждён ({type(exc).__name__}: {exc})")
    else:
        out.append(f"  веса:       НЕТ конфига {cfg_path}. "
                   "Прогнать: scripts/fetch_trellis.py")
    return out


@mcp.tool(annotations=READ_ONLY)
async def shot_scene(
    scene: str = "main",
    views: int = 1,
    azimuth: float | None = None,
    elevation: float = 15,
    res: int = 1024,
    unshaded: bool = False,
    reference: str = "",
) -> list:
    """Снять кадры из сцены Godot - глаза в собранном мире.

    По тексту .tscn нельзя понять, стоит ли предмет на полу или висит в
    воздухе, не съел ли туман дальнюю стену, не выгорела ли картинка от
    пересвета. Инструмент запускает сцену, снимает её и возвращает кадры
    сюда - 3-5 секунд на вызов, несколько ракурсов за один запуск движка.

    Вместе с кадрами приходят замеры сцены и ОШИБКИ СКРИПТОВ из вывода
    движка: красивый кадр не значит работающую сцену. Там же яркость каждого
    источника света - первое, что объясняет белую картинку.

    scene:     имя сцены: 'main', 'corridor', 'scenes/corridor.tscn' или
               res://-путь. Пусто - главная сцена мира
    views:     сколько ракурсов. 1 - один кадр; больше - равномерно по кругу.
               Предмет облетается снаружи, локация осматривается ИЗНУТРИ,
               с высоты глаз - так же, как в режиме прогулки
    azimuth:   с какого угла смотреть, градусы. Пусто - взять камеру самой
               сцены, ту, что поставил автор. Задан - завести свою
    elevation: наклон камеры для предмета, градусы. Локация смотрит
               горизонтально: под потолок и в пол там глядеть незачем
    res:       ширина кадра, высота считается как 16:9
    unshaded:  снять ДОПОЛНИТЕЛЬНЫЙ кадр без единой лампы, только альбедо.
               Это способ отличить «текстура не доехала» от «сцена
               пересвечена» - на обычном кадре они выглядят одинаково белыми
    reference: путь к эталонной картинке (имя в data/input, POSIX или
               D:\\...). Каждый кадр вернётся склейкой: сверху движок, снизу
               референс. Так атмосфера сводится глазами и итерациями - тем же
               способом, каким оцениваются рендеры photo_to_3d

    Сцены пишутся текстом: правь .tscn и снимай снова. Свет, туман и
    тонмаппинг - обычные свойства WorldEnvironment, менять их правкой файла.
    """
    def _work():
        return shots.shot_scene(scene, views=views, azimuth=azimuth,
                                elevation=elevation, res=res, unshaded=unshaded,
                                reference=reference or None)

    r = await anyio.to_thread.run_sync(_work)
    return [shots.describe(r), *[Image(path=str(s["path"])) for s in r["shots"]]]


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
        f"стиль превью:     {config.PREVIEW_STYLE}",
        f"моделей в базе:   {len(store.ids())}",
        f"Godot:            {config.GODOT} "
        f"({'найден' if config.GODOT.exists() else 'НЕ НАЙДЕН'})",
    ]

    if config.ENGINE == "trellis":
        lines.append("")
        lines.extend(_trellis_status())

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
