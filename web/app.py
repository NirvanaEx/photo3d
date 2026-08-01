"""Веб-интерфейс просмотра моделей.

Отдельный процесс от MCP-сервера: тот пишет модели на диск, этот их показывает.
Связи между ними нет вообще - только общая папка data/output. Поэтому веб можно
перезапускать и ронять как угодно, генерация не заметит.

Живое обновление сделано через SSE с опросом mtime на стороне сервера.
Именно опросом, а не inotify: папка лежит на /mnt/d (drvfs), где события
файловой системы приходят ненадёжно. Раз в 800 мс сравнить несколько stat -
дёшево и работает всегда.

    /opt/photo3d/venv/bin/python -m web.app
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from pathlib import Path

import uvicorn
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from server import config
from server.store import ModelStore

mimetypes.add_type("model/gltf-binary", ".glb")

STATIC = Path(__file__).parent / "static"
store = ModelStore()

POLL_SEC = 0.8


def _payload(model_id: str) -> dict:
    d = config.OUTPUT_DIR / model_id
    meta = store.meta(model_id)
    stats = meta.get("stats", {})
    glb = d / "model.glb"
    src = next((p.name for p in sorted(d.glob("input.*"))), None)
    return {
        "id": model_id,
        "engine": stats.get("engine"),
        "mode": stats.get("mode"),
        "seed": stats.get("seed"),
        "vertices": stats.get("vertices"),
        "faces": stats.get("faces"),
        "watertight": stats.get("watertight"),
        "elapsed": round(meta.get("elapsed_sec", 0), 1),
        "updated": meta.get("updated_at", 0),
        "render_engine": meta.get("render_engine"),
        "views": [p.name for p in sorted((d / "views").glob("*.png"))],
        "source": src,
        "glb": glb.exists(),
        "glb_size": glb.stat().st_size if glb.exists() else 0,
    }


def _models() -> list[dict]:
    return [_payload(mid) for mid in store.ids()]


def _signature() -> str:
    """Дешёвый отпечаток состояния папки: имена моделей + время правки meta.
    Меняется ровно тогда, когда есть что показать заново."""
    parts = []
    if config.OUTPUT_DIR.is_dir():
        for p in sorted(config.OUTPUT_DIR.iterdir()):
            if p.is_dir() and p.name.startswith("m_"):
                meta = p / "meta.json"
                stamp = meta.stat().st_mtime_ns if meta.exists() else 0
                views = len(list((p / "views").glob("*.png")))
                parts.append(f"{p.name}:{stamp}:{views}")
    return "|".join(parts)


async def index(request):
    return FileResponse(STATIC / "index.html")


async def api_models(request):
    return JSONResponse({"models": _models()})


async def api_events(request):
    """SSE: при любом изменении в data/output отдаём список целиком.
    Список короткий, дифф не окупается."""
    async def stream():
        last = None
        while True:
            if await request.is_disconnected():
                break
            sig = _signature()
            if sig != last:
                last = sig
                yield {"event": "models", "data": json.dumps({"models": _models()})}
            await asyncio.sleep(POLL_SEC)

    return EventSourceResponse(stream())


async def model_file(request):
    """Раздача файлов модели с защитой от выхода за пределы её папки."""
    mid = request.path_params["mid"]
    rel = request.path_params["path"]
    base = (config.OUTPUT_DIR / mid).resolve()
    try:
        target = (base / rel).resolve()
    except (OSError, ValueError):
        return PlainTextResponse("bad path", status_code=400)
    if not str(target).startswith(str(base) + os.sep) or not target.is_file():
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(target)


app = Starlette(routes=[
    Route("/", index),
    Route("/api/models", api_models),
    Route("/api/events", api_events),
    Route("/files/{mid}/{path:path}", model_file),
    Mount("/static", StaticFiles(directory=str(STATIC))),
])


def main() -> None:
    port = int(os.environ.get("PHOTO3D_WEB_PORT", "8765"))
    # 127.0.0.1, а не 0.0.0.0: интерфейс без аутентификации, наружу ему нельзя.
    # Windows достучится через localhostForwarding в WSL2.
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
