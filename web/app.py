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
import base64
import json
import mimetypes
import os
import secrets
from pathlib import Path

import anyio
import uvicorn
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from server import config
from server.store import ModelStore

from . import library

mimetypes.add_type("model/gltf-binary", ".glb")

STATIC = Path(__file__).parent / "static"
store = ModelStore()

POLL_SEC = 0.8


def _read_meta(d: Path) -> dict:
    """Читаем meta.json сами, а не через store: store умеет только data/output,
    а те же карточки нужны и для корзины. Плюс генерация может писать сюда
    прямо сейчас - недописанный JSON не должен ронять весь список."""
    f = d / "meta.json"
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _stamp(d: Path) -> str:
    """Дешёвый отпечаток одной модели: четыре stat.

    Раньше здесь перебирались views/*.png. На drvfs это дорого - каталог
    лежит на NTFS через переходник, и один stat стоит пару миллисекунд, а
    кадров два десятка. Замер: перебор 19 папок - 51 мс, по одному stat на
    папку - 17 мс.

    Замена корректна, потому что mtime каталога на drvfs меняется при
    создании и удалении файла (проверено, не выведено). Правка файла на
    месте его не меняет - но кадры только дописываются, а перерендер под
    теми же именами всё равно виден по meta.json, который переписывается
    следом. Прежний подсчёт количества, к слову, такой перерендер тоже
    не замечал.
    """
    def ns(p: Path) -> int:
        try:
            return p.stat().st_mtime_ns
        except OSError:
            return 0
    return f"{ns(d)}.{ns(d / 'meta.json')}.{ns(d / 'ui.json')}.{ns(d / 'views')}"


# Карточка модели пересобирается только когда её отпечаток изменился.
# Без этого каждое изменение любой модели стоило бы полного перебора кадров
# по всем остальным - на drvfs это была почти секунда на ровном месте.
_payload_cache: dict[str, tuple[str, dict]] = {}


def _payload(model_id: str, root: Path, stamp: str) -> dict:
    key = str(root / model_id)
    hit = _payload_cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    data = _build_payload(model_id, root)
    _payload_cache[key] = (stamp, data)
    return data


def _build_payload(model_id: str, root: Path) -> dict:
    d = root / model_id
    meta = _read_meta(d)
    ui = library.read_ui(d)
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
        # Откуда сделана: для генерации это имя файла, для производных -
        # ссылки на модели. Панель показывает и то и другое, поэтому строка
        # уходит как есть, а разобранные ссылки - отдельным полем.
        "origin": Path(str(meta.get("source", ""))).name or None,
        # Без отсева по существующим: он зависит от состава папки, а карточка
        # кэшируется по своему отпечатку. Отсеиваем в _models, где состав
        # известен целиком и стоит это ничего.
        "parents": library.parents_of(meta),
        "glb": glb.exists(),
        "glb_size": glb.stat().st_size if glb.exists() else 0,
        "size": library.folder_size(d),
        "fresh": library.is_fresh(d),
        # Правится человеком через интерфейс, лежит в отдельном ui.json
        "title": ui.get("title") or "",
        "note": ui.get("note") or "",
        "star": bool(ui.get("star")),
        "deleted_at": ui.get("deleted_at") or 0,
    }


def _collect(root: Path) -> list[dict]:
    ids = library.list_ids(root)
    return [_payload(mid, root, _stamp(root / mid)) for mid in ids]


def _models() -> list[dict]:
    """Модели библиотеки со связями в обе стороны.

    Обратные связи считаются здесь, а не в браузере: список приходит целиком
    на каждое изменение, и пересобирать граф в каждой вкладке незачем.

    Карточки из кэша менять на месте нельзя - это те же объекты, что лежат
    в _payload_cache. Поэтому связи кладутся в поверхностную копию.
    """
    items = _collect(config.OUTPUT_DIR)
    known = {m["id"] for m in items}
    out = [{**m, "parents": [p for p in m["parents"] if p in known]}
           for m in items]

    children: dict[str, list[str]] = {}
    for m in out:
        for p in m["parents"]:
            children.setdefault(p, []).append(m["id"])
    for m in out:
        m["children"] = children.get(m["id"], [])
    return out


def _signature() -> str:
    """Дешёвый отпечаток состояния папок. Меняется ровно тогда, когда есть
    что показать заново.

    Отпечаток модели тот же, что и у её карточки (_stamp), поэтому опрос
    и пересборка списка не делают одну и ту же работу дважды: изменившиеся
    карточки пересобираются, остальные берутся из кэша.

    ui.json входит в отпечаток наравне с meta.json: переименование в одной
    вкладке должно доехать до остальных, а meta.json оно не трогает.
    """
    parts = []
    if config.OUTPUT_DIR.is_dir():
        for p in sorted(config.OUTPUT_DIR.iterdir()):
            if p.is_dir() and library.valid_id(p.name):
                parts.append(f"{p.name}:{_stamp(p)}")

    # Корзина - один stat на всю папку, а не по четыре на каждую запись.
    # Её содержимое само по себе не меняется: туда попадают и оттуда уходят
    # только по нажатию кнопки, а любое такое движение - создание или
    # удаление подпапки, от чего mtime самой корзины меняется. Внутренности
    # удалённых моделей не правятся вовсе, поэтому глубже смотреть незачем.
    try:
        parts.append(f"trash:{library.TRASH_DIR.stat().st_mtime_ns}")
    except OSError:
        parts.append("trash:0")
    return "|".join(parts)


async def index(request):
    return FileResponse(STATIC / "index.html")


def _state() -> dict:
    models = _models()
    trash = _collect(library.TRASH_DIR)
    # Кэш карточек чистим здесь: удалённые и стёртые модели иначе остались
    # бы в нём до перезапуска.
    alive = {str(config.OUTPUT_DIR / m["id"]) for m in models}
    alive |= {str(library.TRASH_DIR / m["id"]) for m in trash}
    for key in [k for k in _payload_cache if k not in alive]:
        del _payload_cache[key]
    return {"models": models, "trash": trash}


# Обход папок идёт через drvfs, где один stat стоит миллисекунды, а модели
# исчисляются десятками. В цикле событий такому не место: при опросе раз в
# 800 мс сборка списка занимала бы заметную его долю, и всё остальное -
# раздача GLB, ответы на действия - ждало бы её. Уносим в поток.
async def _in_thread(fn):
    return await anyio.to_thread.run_sync(fn)


async def api_models(request):
    return JSONResponse(await _in_thread(_state))


async def api_events(request):
    """SSE: при любом изменении в data/output отдаём список целиком.
    Список короткий, дифф не окупается."""
    async def stream():
        last = None
        while True:
            if await request.is_disconnected():
                break
            sig = await _in_thread(_signature)
            if sig != last:
                last = sig
                state = await _in_thread(_state)
                yield {"event": "models", "data": json.dumps(state)}
            await asyncio.sleep(POLL_SEC)

    return EventSourceResponse(stream())


# ------------------------------------------------------------------ действия

def _fail(reason: str, hint: str = "", code: int = 400) -> JSONResponse:
    """Ответ об ошибке в том же виде, что и ошибки пайплайна: причина и
    что делать. Пустое место вместо объяснения уводит диагностику не туда."""
    return JSONResponse({"ok": False, "error": reason, "hint": hint}, status_code=code)


def _target(request, trashed: bool = False) -> tuple[str, Path] | JSONResponse:
    """Проверить id из URL и вернуть папку. Общий вход для всех действий."""
    mid = request.path_params["mid"]
    if not library.valid_id(mid):
        return _fail(f"неподходящий идентификатор {mid!r}",
                     "ожидается вид m_a3f7", code=404)
    d = library.model_dir(mid, trashed=trashed)
    if not d.is_dir():
        where = "корзине" if trashed else "библиотеке"
        return _fail(f"модель {mid} не найдена в {where}",
                     "обнови страницу: список мог устареть", code=404)
    return mid, d


async def api_delete(request):
    """Убрать модель в корзину.

    Именно в корзину, а не rm -rf: причина та же, что записана в
    scripts/cleanup.py - место на диске есть, а вернуть передумав дешевле,
    чем восстанавливать заново шестиминутной генерацией.
    """
    got = _target(request)
    if isinstance(got, JSONResponse):
        return got
    mid, _ = got
    try:
        library.to_trash(mid)
    except FileExistsError:
        return _fail(f"в корзине уже лежит {mid}",
                     "очисти корзину или удали оттуда эту запись", code=409)
    except OSError as e:
        # Под Windows папку не отдадут, пока её файлы кто-то держит открытыми.
        # Самый частый случай - идущая прямо сейчас генерация.
        return _fail(f"не удалось убрать {mid}: {e}",
                     "возможно, по этой модели прямо сейчас идёт работа - "
                     "дождись конца и повтори", code=409)
    return JSONResponse({"ok": True, "id": mid})


async def api_restore(request):
    got = _target(request, trashed=True)
    if isinstance(got, JSONResponse):
        return got
    mid, _ = got
    try:
        library.from_trash(mid)
    except FileExistsError:
        return _fail(f"в библиотеке уже есть {mid}",
                     "переименуй или удали существующую запись", code=409)
    except OSError as e:
        return _fail(f"не удалось вернуть {mid}: {e}", "повтори через минуту",
                     code=409)
    return JSONResponse({"ok": True, "id": mid})


async def api_purge(request):
    """Стереть окончательно. Подтверждение спрашивает интерфейс."""
    got = _target(request, trashed=True)
    if isinstance(got, JSONResponse):
        return got
    mid, _ = got
    try:
        library.purge(mid)
    except OSError as e:
        return _fail(f"не удалось стереть {mid}: {e}",
                     "файл может быть открыт другой программой", code=409)
    return JSONResponse({"ok": True, "id": mid})


async def api_purge_all(request):
    try:
        n = library.purge_all()
    except OSError as e:
        return _fail(f"корзина очищена не до конца: {e}",
                     "часть файлов занята - повтори позже", code=409)
    return JSONResponse({"ok": True, "purged": n})


async def api_patch_ui(request):
    """Имя, заметка, звёздочка. Пишутся в ui.json рядом с meta.json.

    В meta.json веб не пишет принципиально: его владелец - пайплайн,
    и он может писать туда прямо сейчас из соседнего процесса.
    """
    # Только для моделей в библиотеке. Удалённые не правятся намеренно:
    # отпечаток состояния смотрит на корзину одним stat и внутрь не заходит
    # (см. _signature), так что правка там осталась бы незамеченной. Да и
    # переименовывать то, что собрался стереть, незачем.
    got = _target(request)
    if isinstance(got, JSONResponse):
        return got
    mid, d = got
    try:
        patch = await request.json()
    except ValueError:
        return _fail("тело запроса не разобрано как JSON",
                     "отправляй объект вида {\"title\": \"…\"}")
    if not isinstance(patch, dict):
        return _fail("ожидается объект JSON", "например {\"star\": true}")

    clean: dict = {}
    if "title" in patch:
        # Имя показывается в списке и в заголовке, поэтому длина ограничена
        # здесь, а не только в поле ввода: запрос может прийти и мимо формы.
        clean["title"] = str(patch["title"] or "").strip()[:80] or None
    if "note" in patch:
        clean["note"] = str(patch["note"] or "").strip()[:500] or None
    if "star" in patch:
        clean["star"] = bool(patch["star"]) or None
    if not clean:
        return _fail("нечего менять",
                     "поддерживаются поля title, note, star")
    try:
        library.patch_ui(d, clean)
    except OSError as e:
        return _fail(f"не удалось записать ui.json: {e}",
                     "проверь права на папку модели", code=500)
    return JSONResponse({"ok": True, "id": mid})


def _serve(root: Path, mid: str, rel: str):
    """Раздача файлов модели с защитой от выхода за пределы её папки."""
    # Проверяется НЕ только rel, но и сам mid. Он приходит одним сегментом,
    # поэтому косых черт в нём не бывает, но ".." - вполне: тогда base
    # уезжает на уровень выше, а нижняя проверка сравнивает уже с уехавшей
    # base и пропускает соседние папки data/. Пока сервер слушал только
    # localhost, это было безобидно; при выносе наружу - нет.
    #
    # Шаблон id отсекает то же самое ещё раньше и заодно всё остальное,
    # чего в имени папки быть не должно. Обе проверки оставлены нарочно:
    # первая объясняет себя, вторая не даст ошибиться, если шаблон когда-то
    # ослабят.
    if not library.valid_id(mid):
        return PlainTextResponse("not found", status_code=404)

    base_root = root.resolve()
    base = (root / mid).resolve()
    if not str(base).startswith(str(base_root) + os.sep):
        return PlainTextResponse("not found", status_code=404)

    try:
        target = (base / rel).resolve()
    except (OSError, ValueError):
        return PlainTextResponse("bad path", status_code=400)
    if not str(target).startswith(str(base) + os.sep) or not target.is_file():
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(target)


async def model_file(request):
    return _serve(config.OUTPUT_DIR, request.path_params["mid"],
                  request.path_params["path"])


async def trash_file(request):
    """Миниатюры для корзины. Отдельный корень, а не параметр к /files:
    так путь к удалённому нельзя получить случайно, перебирая обычные ссылки."""
    return _serve(library.TRASH_DIR, request.path_params["mid"],
                  request.path_params["path"])


class BasicAuth(BaseHTTPMiddleware):
    """Пароль на весь интерфейс. Включается только когда задан PHOTO3D_WEB_PASSWORD.

    Сравнение через compare_digest, а не ==: обычное сравнение строк
    прекращается на первом различии, и по времени ответа пароль подбирается
    посимвольно. Здесь это скорее принцип, чем реальная угроза, но делать
    правильно дешевле, чем объяснять, почему не сделал.
    """

    def __init__(self, app, password: str) -> None:
        super().__init__(app)
        self._password = password

    async def dispatch(self, request, call_next):
        header = request.headers.get("authorization", "")
        if header.startswith("Basic "):
            try:
                raw = base64.b64decode(header[6:]).decode("utf-8", "replace")
                _, _, given = raw.partition(":")
            except Exception:  # noqa: BLE001
                given = ""
            if secrets.compare_digest(given, self._password):
                return await call_next(request)
        return PlainTextResponse(
            "нужен пароль", status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="photo3d"'})


class SameOriginOnly(BaseHTTPMiddleware):
    """Изменяющие запросы принимаются только от самой страницы.

    Появилось вместе с кнопкой «удалить». До неё интерфейс только читал, и
    подделывать запросы к нему было незачем. Теперь чужая страница могла бы
    отправить POST на localhost:8765 - браузер сам приложит и куки, и
    заголовок Basic-авторизации, и модель уедет в корзину без ведома хозяина.

    Защита - требование своего заголовка. Простую форму или картинку с
    чужого сайта отправить можно, а вот fetch с нестандартным заголовком
    браузер сперва спросит предполётным OPTIONS. Мы на него не отвечаем,
    поэтому настоящий запрос так и не уйдёт. Токен в страницу класть не
    нужно: заголовок сам по себе недостижим для межсайтового запроса.
    """

    SAFE = {"GET", "HEAD", "OPTIONS"}

    async def dispatch(self, request, call_next):
        if request.method in self.SAFE:
            return await call_next(request)
        if request.headers.get("x-photo3d") != "1":
            return PlainTextResponse(
                "запрос без заголовка X-Photo3D отклонён", status_code=403)
        return await call_next(request)


def build_app() -> Starlette:
    routes = [
        Route("/", index),
        Route("/api/models", api_models),
        Route("/api/events", api_events),
        Route("/api/models/{mid}/delete", api_delete, methods=["POST"]),
        Route("/api/models/{mid}/ui", api_patch_ui, methods=["POST"]),
        Route("/api/trash/purge", api_purge_all, methods=["POST"]),
        Route("/api/trash/{mid}/restore", api_restore, methods=["POST"]),
        Route("/api/trash/{mid}/purge", api_purge, methods=["POST"]),
        Route("/files/{mid}/{path:path}", model_file),
        Route("/trash-files/{mid}/{path:path}", trash_file),
        Mount("/static", StaticFiles(directory=str(STATIC))),
    ]
    application = Starlette(routes=routes)
    application.add_middleware(SameOriginOnly)
    password = os.environ.get("PHOTO3D_WEB_PASSWORD", "")
    if password:
        application.add_middleware(BasicAuth, password=password)
    return application


app = build_app()


def main() -> None:
    port = int(os.environ.get("PHOTO3D_WEB_PORT", "8765"))
    host = os.environ.get("PHOTO3D_WEB_HOST", "127.0.0.1")
    password = os.environ.get("PHOTO3D_WEB_PASSWORD", "")

    # Слушать не только localhost можно ТОЛЬКО с паролем. Иначе интерфейс
    # уходит наружу открытым, а он отдаёт файлы моделей и исходные снимки.
    # Проверка тут, а не в напоминании в README: забыть переменную окружения
    # легко, а последствия молчаливые.
    if host not in ("127.0.0.1", "localhost", "::1") and not password:
        raise SystemExit(
            f"отказ: host={host} выставляет интерфейс за пределы машины, "
            "а PHOTO3D_WEB_PASSWORD не задан.\n"
            "Задай пароль или оставь host=127.0.0.1"
        )

    where = "с паролем" if password else "без пароля, только локально"
    print(f"photo3d web: http://{host}:{port} ({where})", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
