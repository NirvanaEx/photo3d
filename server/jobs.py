"""Очередь заданий: как человек и агент делят одну видеокарту.

До неё исполнителем был только агент. Веб-интерфейс намеренно держался в
стороне от пайплайна - чтобы страницу можно было ронять и перезапускать, не
роняя генерацию, - и побочным следствием этого решения человек оказался
отрезан от создания вовсе: он мог смотреть, переименовывать и удалять, но не
делать.

Очередь снимает следствие, не отменяя причины. Веб по-прежнему не исполняет
ничего: он кладёт задание в папку. Исполняет третий процесс - воркер, который
живёт отдельно от обоих и переживает перезапуск любого из них.

Почему файлы на диске, а не очередь в памяти или sqlite:

- у веба уже написана доставка. Он следит за data/output опросом mtime (на
  drvfs события файловой системы приходят ненадёжно, см. web/app.py) и толкает
  изменения в открытую страницу по SSE. Задание - такая же папка под
  наблюдением, и прогресс приезжает на страницу тем же путём, каким приезжает
  готовая модель. Ничего нового писать не надо;
- задание переживает падение всех трёх процессов. Воркер убили посреди
  генерации - файл остался, и видно, на чём встало;
- задание читается глазами: cat data/jobs/j_a3f7.json.

Очередь здесь не про пропускную способность, а про **взаимное исключение**.
Видеокарта одна, WSL ограничена 10 ГБ, веса TRELLIS - 9.13 ГБ на каждый вызов.
Две генерации разом не идут ни при каком раскладе, и до очереди это
предотвращалось только тем, что запускать умел один участник. Теперь их двое,
и «кто сейчас занял GPU» решается постановкой, а не удачей.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from . import config

JOBS_DIR = config.JOBS_DIR

# Замок воркера и его вывод лежат в ОТДЕЛЬНОЙ подпапке, а не рядом с
# заданиями, и это не наведение порядка. Воркер бьётся раз в три секунды, то
# есть переписывает свой файл; запись идёт через временный файл и os.replace,
# а появление и исчезновение файла меняет mtime папки. Лежи замок среди
# заданий - и mtime data/jobs дёргался бы постоянно, обесценив дешёвую
# проверку «появилось ли что-то новое», на которой стоят и воркер, и веб.
WORKER_DIR = JOBS_DIR / "worker"
WORKER_FILE = WORKER_DIR / "state.json"
WORKER_LOG = WORKER_DIR / "log.txt"

JOB_RE = re.compile(r"^j_[0-9a-f]{6}$")

QUEUED, RUNNING, DONE, FAILED, CANCELLED = (
    "queued", "running", "done", "failed", "cancelled")
FINAL = (DONE, FAILED, CANCELLED)

# Насколько свежим должно быть сердцебиение, чтобы воркер считался живым.
# Он бьётся раз в 3 с; 20 взято с запасом на drvfs, где запись файла иногда
# занимает десятки миллисекунд, и на секундные паузы под нагрузкой.
BEAT_SEC = 3.0
STALE_SEC = 20.0


def valid_id(job_id: str) -> bool:
    """Шаблон целиком, а не «начинается с j_»: идентификатор подставляется в
    путь, и `..` внутри увёл бы запись в соседние папки data/. Та же причина,
    по которой так же проверяется id модели (web/library.py)."""
    return bool(JOB_RE.match(job_id or ""))


def _path(job_id: str) -> Path:
    if not valid_id(job_id):
        raise ValueError(f"неподходящий идентификатор задания: {job_id!r}")
    return JOBS_DIR / f"{job_id}.json"


def _write(path: Path, data: dict[str, Any]) -> None:
    """Запись через временный файл и os.replace.

    Тот же приём, что у ui.json: файл читают из двух других процессов прямо
    сейчас, и обрыв записи не должен оставить им огрызок JSON вместо задания.

    Имя временного файла СВОЁ у каждой записи, а не `<файл>.tmp`. Общее имя
    даёт гонку: первый процесс создаёт tmp, второй его перезаписывает и
    переименовывает, а первый падает на своём os.replace с FileNotFoundError -
    файла уже нет. Писателей у задания трое (веб, MCP, воркер), и такой
    FileNotFoundError один раз уже вылез в логе.

    Уникальное имя оставляет ровно то поведение, которое и нужно: выигрывает
    последний записавший, а не тот, кто первым дошёл до переименования.
    Проверено на трёх процессах по 40 правок в одно задание: ошибок ноль,
    задание читается целиком, временных файлов не остаётся.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _read_file(path: Path) -> dict[str, Any]:
    """Недописанный или исчезнувший файл - не повод падать: его пишет соседний
    процесс, и гонка здесь обычное дело, а не поломка."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# ------------------------------------------------------------------ задания

def submit(kind: str, args: dict[str, Any], by: str = "agent",
           title: str = "") -> dict[str, Any]:
    """Поставить задание в очередь. Возвращает его целиком.

    by - кто поставил: "human" или "agent". Поле не украшение: агент должен
    видеть, что человек прямо сейчас что-то запустил, иначе он запустит своё
    поверх и оба упрутся в память.
    """
    job_id = "j_" + uuid.uuid4().hex[:6]
    now = time.time()
    job = {
        "id": job_id,
        "kind": kind,
        "args": args,
        "by": by,
        # Движок, которого ждёт заказчик. Воркер сверит его со своим и
        # откажется, если они разошлись. Иначе живучий воркер, поднятый
        # когда-то с заглушкой (например, проверкой из scripts/test_jobs.py),
        # молча отдал бы надутый силуэт вместо настоящей генерации - а по
        # карточке модели это видно только строкой «движок stub», которую
        # никто не читает, пока не станет поздно.
        "engine": config.ENGINE,
        "title": title or kind,
        "state": QUEUED,
        "stage": "в очереди",
        "created": now,
        "started": 0.0,
        "finished": 0.0,
        "progress": [],
        "result": {},
        "error": {},
    }
    _write(_path(job_id), job)
    return job


def read(job_id: str) -> dict[str, Any]:
    return _read_file(_path(job_id))


def update(job_id: str, **fields: Any) -> dict[str, Any]:
    """Дописать поля в задание.

    Читаем-меняем-пишем, и это безопасно ровно потому, что пишет задание один
    воркер. Единственное, что меняют посторонние, - отмена, и она нарочно
    сделана отдельным файлом, а не полем здесь (см. cancel).
    """
    job = read(job_id)
    if not job:
        return {}
    job.update(fields)
    _write(_path(job_id), job)
    return job


def listing(limit: int = 50, states: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Задания, свежие сверху."""
    if not JOBS_DIR.is_dir():
        return []
    out = []
    for p in JOBS_DIR.glob("j_*.json"):
        job = _read_file(p)
        if not job:
            continue
        if states and job.get("state") not in states:
            continue
        out.append(job)
    out.sort(key=lambda j: j.get("created", 0), reverse=True)
    return out[:limit]


def active() -> list[dict[str, Any]]:
    return listing(limit=100, states=(QUEUED, RUNNING))


# ------------------------------------------------------------------- отмена

def cancel(job_id: str) -> bool:
    """Пометить задание отменённым.

    Маркер отдельным файлом, а не полем в JSON, и это не мелочь. Отменяет
    посторонний процесс - веб или агент, - а задание в это же время пишет
    воркер. Два читающих-меняющих-пишущих в один файл теряют правки друг
    друга; существование файла потерять нельзя.

    Уже идущее задание маркер не прерывает: генерация сидит внутри docker run
    и на полпути не останавливается. Он снимает задание из очереди и
    останавливает воркера между этапами - большего честно не обещаем.
    """
    if not valid_id(job_id) or not _path(job_id).exists():
        return False
    (JOBS_DIR / f"{job_id}.cancel").touch()
    return True


def is_cancelled(job_id: str) -> bool:
    return (JOBS_DIR / f"{job_id}.cancel").exists()


# -------------------------------------------------------------- исполнение

def claim_next(worker: str) -> dict[str, Any] | None:
    """Взять самое старое задание из очереди.

    Гонки за задание здесь нет и не предусмотрено: воркер один, и это
    обеспечивается замком (см. take_lock), а не хитростями с атомарным
    переименованием. Заводить второго воркера бессмысленно - видеокарта одна.
    """
    queued = [j for j in listing(limit=200, states=(QUEUED,))
              if not is_cancelled(j["id"])]
    if not queued:
        return None
    job = min(queued, key=lambda j: j.get("created", 0))
    return update(job["id"], state=RUNNING, started=time.time(),
                  stage="начато", worker=worker)


def finish(job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return update(job_id, state=DONE, finished=time.time(), stage="готово",
                  result=result)


def fail(job_id: str, stage: str, reason: str, hint: str = "") -> dict[str, Any]:
    """Ошибка задания той же формы, что и ошибки пайплайна: этап, причина и
    что делать. Третья часть обязательна - см. server/errors.py."""
    return update(job_id, state=FAILED, finished=time.time(), stage="ошибка",
                  error={"stage": stage, "reason": reason, "hint": hint})


def mark_cancelled(job_id: str) -> dict[str, Any]:
    return update(job_id, state=CANCELLED, finished=time.time(),
                  stage="отменено")


class Progress:
    """Ручка, которой обработчик рассказывает о себе.

    Этапы крупные - «генерация», «рендер превью», - и это честно: внутри
    engine.generate сидит docker run, который своей доли времени наружу не
    отдаёт. Мелкий прогресс здесь был бы выдумкой.
    """

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id

    def stage(self, text: str) -> None:
        job = read(self.job_id)
        if not job:
            return
        log = list(job.get("progress", []))
        log.append({"at": time.time(), "text": text})
        # Хвост, а не вся история: задание живёт минуты, а строк за это время
        # накопиться может сколько угодно, если обработчик разговорчив.
        update(self.job_id, stage=text, progress=log[-40:])

    def set(self, **fields: Any) -> None:
        """Дописать поля к заданию по ходу дела.

        Нужно прежде всего для model_id: папка модели заводится в начале
        работы, и связать с ней карточку задания надо сразу, а не в конце.
        Иначе четыре минуты человек смотрит на строку без ссылки на то, что
        уже создаётся.
        """
        update(self.job_id, **fields)

    def cancelled(self) -> bool:
        return is_cancelled(self.job_id)


# ------------------------------------------------------------------- воркер

def take_lock(pid: int) -> dict[str, Any] | None:
    """Занять место воркера. None - место занято живым процессом.

    Замок нужен не от толпы, а от повторного запуска: воркер поднимается и
    руками, и сам собой из ensure_worker, и второй экземпляр означал бы две
    генерации разом - то самое, ради чего очередь и заводилась.
    """
    WORKER_DIR.mkdir(parents=True, exist_ok=True)
    cur = worker_status()
    if cur.get("alive") and cur.get("pid") != pid:
        return None
    data = {"pid": pid, "started": time.time(), "seen": time.time(), "job": "",
            "engine": config.ENGINE}
    _write(WORKER_FILE, data)
    return data


def beat(pid: int, job_id: str = "") -> None:
    data = _read_file(WORKER_FILE)
    if data.get("pid") != pid:
        # Место перехвачено кем-то другим. Молчать нельзя: воркер обязан это
        # заметить и уйти, иначе исполнителей окажется два.
        return
    data["seen"] = time.time()
    data["job"] = job_id
    _write(WORKER_FILE, data)


def holds_lock(pid: int) -> bool:
    return _read_file(WORKER_FILE).get("pid") == pid


def release_lock(pid: int) -> None:
    if holds_lock(pid):
        try:
            WORKER_FILE.unlink()
        except OSError:
            pass


def worker_status() -> dict[str, Any]:
    """Живой ли воркер.

    Две проверки, и обе нужны. Сердцебиение ловит зависший процесс, который
    жив, но ничего не делает; проверка pid ловит убитый, чей файл остался
    лежать - без неё после kill -9 очередь считалась бы обслуживаемой ещё
    двадцать секунд, а после перезагрузки - ровно до первого чтения.
    """
    data = _read_file(WORKER_FILE)
    pid = data.get("pid")
    if not pid:
        return {"alive": False}
    fresh = (time.time() - data.get("seen", 0)) < STALE_SEC
    running = True
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        running = False
    return {**data, "alive": bool(fresh and running), "fresh": fresh,
            "running": running}


# Повторный запуск не чаще раза в полминуты. Воркер, падающий на импорте,
# иначе поднимался бы на каждый вызов и заваливал бы лог одинаковыми
# трассировками вместо того, чтобы дать себя заметить.
_SPAWN_EVERY_SEC = 30.0
_last_spawn = 0.0


def ensure_worker(timeout: float = 20.0) -> dict[str, Any]:
    """Убедиться, что исполнитель есть, и поднять его, если нет.

    Автозапуск, а не «запусти сам, потом приходи», по простой причине: до
    очереди агент генерировал одним вызовом, и требование заранее поднять
    посторонний процесс сломало бы всё, что уже работает. Воркер отвязывается
    от родителя (start_new_session), поэтому переживает и перезапуск
    MCP-сервера, и закрытие вкладки.
    """
    global _last_spawn
    st = worker_status()
    if st.get("alive"):
        return st

    if time.time() - _last_spawn < _SPAWN_EVERY_SEC:
        return {**st, "alive": False,
                "note": "недавняя попытка запуска не удалась, жду"}
    _last_spawn = time.time()

    WORKER_DIR.mkdir(parents=True, exist_ok=True)
    with WORKER_LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n=== запуск {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        log.flush()
        subprocess.Popen(
            [sys.executable, "-m", "worker.main"],
            cwd=str(config.ROOT), stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )

    deadline = time.time() + timeout
    while time.time() < deadline:
        st = worker_status()
        if st.get("alive"):
            return st
        time.sleep(0.3)
    return {**worker_status(), "alive": False}


def worker_hint() -> str:
    """Что сказать человеку, когда исполнителя нет."""
    tail = ""
    try:
        tail = "\n".join(WORKER_LOG.read_text(encoding="utf-8",
                                              errors="replace").splitlines()[-8:])
    except OSError:
        pass
    hint = (f"запусти воркер вручную и посмотри, что он пишет:\n"
            f"  cd {config.ROOT} && {sys.executable} -m worker.main")
    if tail.strip():
        hint += f"\nпоследнее в {WORKER_LOG}:\n{tail}"
    return hint


# -------------------------------------------------------------- ожидание

def wait(job_id: str, timeout: float, poll: float = 0.4) -> dict[str, Any]:
    """Дождаться конца задания. Синхронно - для скриптов и проверок."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = read(job_id)
        if job.get("state") in FINAL:
            return job
        time.sleep(poll)
    return read(job_id)


async def wait_async(job_id: str, timeout: float, poll: float = 0.4) -> dict[str, Any]:
    """То же для MCP: ждём, не занимая поток.

    Чтение задания - один stat и мелкий файл, поэтому уносить его в поток не
    стоит: на drvfs это доли миллисекунды, а лишний переход между потоками
    раз в 400 мс дороже самого чтения.
    """
    import anyio

    deadline = time.time() + timeout
    while time.time() < deadline:
        job = read(job_id)
        if job.get("state") in FINAL:
            return job
        await anyio.sleep(poll)
    return read(job_id)


# ------------------------------------------------- отпечаток и уборка

def stamp() -> str:
    """Дешёвый отпечаток очереди для SSE: ОДИН stat на всю папку.

    Первый вариант брал stat с каждого задания - и это была ровно та ошибка,
    на которой уже обжигались со списком моделей (docs/PITFALLS.md, «сборка
    списка подвешивает сервер на своём же опросе»). Замер на drvfs: 40
    заданий - 23.3 мс на вызов, а вызов идёт раз в 800 мс в каждом
    соединении. Один stat папки стоит 0.166 мс, то есть в 140 раз дешевле.

    Замена корректна, потому что mtime папки на drvfs меняется при любом
    движении внутри - и при появлении файла, и при os.replace поверх
    существующего (замерено, не выведено: 1785735492114293600 ->
    1785735492122457700 на обычной правке этапа). Через _write проходит
    каждая запись задания, отмена - тоже отдельный файл в этой же папке.
    Сердцебиение воркера сюда не попадает намеренно: оно живёт в подпапке,
    иначе отпечаток менялся бы каждые три секунды сам по себе.
    """
    if not JOBS_DIR.is_dir():
        return "jobs:0"
    parts = []
    try:
        parts.append(f"jobs:{JOBS_DIR.stat().st_mtime_ns}")
    except OSError:
        parts.append("jobs:0")
    # Живость воркера входит в отпечаток: пропажа исполнителя должна доехать
    # до страницы так же быстро, как появление задания - иначе человек жмёт
    # кнопку и смотрит на очередь, которую некому разобрать.
    #
    # Именно признак «жив», а не mtime замка: замок переписывается каждые три
    # секунды, и по нему отпечаток менялся бы постоянно, заставляя все
    # открытые вкладки пересобирать состояние впустую.
    parts.append(f"worker:{int(worker_status().get('alive', False))}")
    return "|".join(parts)


def prune(keep: int = 200, older_than_sec: float = 7 * 24 * 3600) -> int:
    """Убрать старые завершённые задания.

    Модели уезжают в корзину, а задания стираются насовсем: восстанавливать
    в них нечего, вся ценность - в модели, на которую они ссылаются.
    """
    done = [j for j in listing(limit=10_000) if j.get("state") in FINAL]
    done.sort(key=lambda j: j.get("created", 0), reverse=True)
    now = time.time()
    killed = 0
    for i, job in enumerate(done):
        if i < keep and (now - job.get("created", 0)) < older_than_sec:
            continue
        for p in (_path(job["id"]), JOBS_DIR / f"{job['id']}.cancel"):
            try:
                p.unlink()
            except OSError:
                pass
        killed += 1
    return killed


Handler = Callable[[dict[str, Any], Progress], dict[str, Any]]
