"""Что воркер умеет делать.

Обработчик - обычная функция (args, progress) -> результат. Никаких картинок и
никакого форматирования для агента: он делает работу и возвращает числа. Как
это показать - дело вызывающей стороны, а их две и они разные. MCP собирает из
результата текст и рендеры в контекст, веб - карточку на странице.

Сюда переезжает ровно та работа, которая занимает видеокарту. Быстрые вещи
остаются на месте: check_photo идёт секунду на процессоре, и, встань он в
очередь позади четырёхминутной генерации, человек перестал бы проверять кадры
вовсе - а это единственный дешёвый способ отсеять половину неудач.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from pipeline import render
from pipeline.engines import get_engine
from server import config
from server.jobs import Progress
from server.store import ModelStore

store = ModelStore()


def photo_to_3d(args: dict[str, Any], p: Progress) -> dict[str, Any]:
    """Фото -> GLB + полный оборот превью.

    Тело переехало из MCP-инструмента без изменений по существу: те же вызовы
    в том же порядке. Разница в том, кто их делает и кто в это время ждёт.

    Путь к исходнику приходит уже разобранным. Разбор («имя в data/input,
    POSIX-путь или D:\\папка\\фото.jpg») остаётся на стороне вызывающего
    нарочно: ошибку «файла нет» человек должен получить сразу при нажатии
    кнопки, а не через две минуты ожидания в очереди.
    """
    src = Path(args["image"])
    if not src.is_file():
        raise FileNotFoundError(f"исходник исчез: {src}")

    mode = args.get("mode", "fast")
    seed = int(args.get("seed", 0))
    started = time.time()

    model_id, mdir = store.create()
    # Связь с моделью проставляется СРАЗУ, до генерации: карточка задания на
    # странице должна вести в папку, которая уже создаётся, а не появляться
    # ссылкой через четыре минуты.
    p.set(model_id=model_id)

    shutil.copy2(src, mdir / f"input{src.suffix.lower()}")
    store.log(model_id, f"источник: {src}")

    engine = get_engine(config.ENGINE)
    glb = mdir / "model.glb"

    p.stage(f"генерация ({engine.name}, {mode})")
    stats = engine.generate(src, glb, seed=seed, mode=mode)

    p.stage("рендер превью")
    frames, rengine, blog = render.render_turntable(
        glb, mdir / "views", views=config.SPIN_FRAMES, res=config.PREVIEW_RES)
    store.log(model_id, blog)

    store.write_meta(model_id, {
        "source": str(src),
        "stats": stats,
        "elapsed_sec": time.time() - started,
        "render_engine": rengine,
        "views": len(frames),
        # Кто заказал. В meta.json это единственное поле не от пайплайна, и
        # оно там уместно: происхождение модели - такая же её характеристика,
        # как движок и seed, и переживать очистку очереди оно должно.
        "by": args.get("by", "agent"),
    })

    return {
        "model_id": model_id,
        "stats": stats,
        "views": len(frames),
        "render_engine": rengine,
        "elapsed_sec": round(time.time() - started, 1),
    }


# Реестр. Добавить умение - дописать сюда функцию, а не править цикл воркера.
HANDLERS: dict[str, Any] = {
    "photo_to_3d": photo_to_3d,
}
