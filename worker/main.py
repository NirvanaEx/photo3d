"""Исполнитель заданий: третий процесс рядом с MCP-сервером и вебом.

Зачем он вообще. Веб не запускает пайплайн намеренно - иначе падение вкладки
станет падением генерации. До сих пор из этого следовало, что запускать умеет
только агент, и человек был отрезан от создания. Воркер снимает следствие, не
отменяя причины: и веб, и агент теперь одинаково кладут задание в папку, а
исполняет его тот, кого можно не трогать.

    /opt/photo3d/venv/bin/python -m worker.main

Руками его запускать не обязательно: ensure_worker поднимает воркера сам при
первой же постановке задания. Ручной запуск нужен, когда хочется видеть вывод
живьём, - в остальное время он пишется в data/jobs/worker.log.

Воркер один. Не потому, что так проще, а потому, что видеокарта одна и WSL
ограничена 10 ГБ: две генерации разом не идут ни при каком раскладе. Второй
экземпляр не встаёт в очередь, а сразу уходит с объяснением.
"""
from __future__ import annotations

import os
import signal
import sys
import threading
import time
import traceback

from server import config, jobs
from server.errors import PipelineError
from worker.handlers import HANDLERS

# Как часто заглядывать в очередь. Полная опись читает каждое задание - на
# drvfs это 23 мс на сорок штук, - поэтому дешёвая проверка идёт первой:
# mtime самой папки меняется при любом движении внутри, и при появлении
# файла, и при перезаписи существующего (замер в server/jobs.py, stamp).
# Полная опись раз в SCAN_EVERY_SEC - страховка на случай, если файл создан
# так, что mtime папки не двинулся.
POLL_SEC = 0.5
SCAN_EVERY_SEC = 5.0

# Простой дольше этого - выход. Воркер поднимется заново при первом же
# задании, а держать процесс сутками там, где ОЗУ и есть узкое место,
# незачем. Ноль отключает выход по простою.
IDLE_EXIT_SEC = float(os.environ.get("PHOTO3D_WORKER_IDLE", "1800"))

_stop = False


def _on_signal(signum, _frame) -> None:
    """Мягкая остановка. Идущее задание не бросаем: docker run всё равно
    досчитает, а брошенное на полпути задание оставит папку модели без
    meta.json - мусор, который потом разбирать руками."""
    global _stop
    _stop = True
    say(f"получен сигнал {signum} — доработаю текущее задание и выйду")


def say(text: str) -> None:
    """Печать с временем. Вывод уходит в worker.log, и без времени по нему
    нельзя понять, что за чем следовало."""
    print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)


class Heart(threading.Thread):
    """Сердцебиение отдельным потоком.

    Бить из главного цикла нельзя, и это не стилистика. Генерация идёт минуты
    внутри одного вызова, и всё это время цикл до строки с ударом не
    доходит. Замок протух бы через двадцать секунд, ensure_worker счёл бы
    исполнителя мёртвым и поднял бы второго - ровно поверх идущей генерации,
    то есть ровно та беда, от которой очередь и заводилась.

    Поток заодно следит, не перехватил ли замок кто-то ещё: тогда уходить
    надо нам, а не спорить.
    """

    def __init__(self, pid: int) -> None:
        super().__init__(daemon=True, name="heart")
        self.pid = pid
        self.job = ""
        self.lost = False
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            jobs.beat(self.pid, self.job)
            if not jobs.holds_lock(self.pid):
                self.lost = True
                return
            self._stop.wait(jobs.BEAT_SEC)

    def halt(self) -> None:
        self._stop.set()


def run_job(job: dict) -> None:
    job_id = job["id"]
    kind = job.get("kind", "")
    handler = HANDLERS.get(kind)
    if handler is None:
        jobs.fail(job_id, "очередь", f"неизвестный вид задания: {kind!r}",
                  f"известны: {', '.join(sorted(HANDLERS)) or 'ни одного'}")
        say(f"{job_id}: неизвестный вид {kind!r}")
        return

    # Движок сверяется, а не подразумевается. Воркер живёт дольше того, кто
    # его поднял, и наследует окружение родителя: поднятый проверкой с
    # PHOTO3D_ENGINE=stub, он потом обслужил бы настоящий вызов заглушкой.
    # Ошибка при этом тихая - модель получается, просто не та.
    want = job.get("engine")
    if want and want != config.ENGINE:
        jobs.fail(job_id, "очередь",
                  f"задание ждёт движок {want}, а исполнитель поднят с "
                  f"{config.ENGINE}",
                  f"останови воркер и дай ему подняться заново с нужным "
                  f"окружением: kill {os.getpid()}")
        say(f"{job_id}: отказ — движок {want} против моего {config.ENGINE}")
        return

    p = jobs.Progress(job_id)
    started = time.time()
    say(f"{job_id}: {kind} от {job.get('by', '?')} — начал")
    try:
        result = handler(job.get("args", {}), p)
    except PipelineError as e:
        # Ошибка пайплайна уже несёт этап, причину и что делать - переносим
        # как есть, не заворачивая в traceback.
        jobs.fail(job_id, e.stage, e.reason, e.hint)
        say(f"{job_id}: не вышло на этапе {e.stage}: {e.reason}")
        return
    except Exception as e:  # noqa: BLE001
        # Всё остальное: в задание уходит короткая причина, в лог - полный
        # разбор. Показывать человеку traceback в карточке незачем, а терять
        # его нельзя.
        jobs.fail(job_id, kind, f"{type(e).__name__}: {e}",
                  f"полный разбор в {jobs.WORKER_LOG}")
        say(f"{job_id}: упало\n{traceback.format_exc()}")
        return

    jobs.finish(job_id, result)
    say(f"{job_id}: готово за {time.time() - started:.1f} c — {result}")


def loop() -> int:
    pid = os.getpid()
    if jobs.take_lock(pid) is None:
        cur = jobs.worker_status()
        say(f"воркер уже работает (pid {cur.get('pid')}) — выхожу. "
            f"Видеокарта одна, второй исполнитель только мешал бы.")
        return 0

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    say(f"воркер поднят, pid {pid}, движок {config.ENGINE}, "
        f"умеет: {', '.join(sorted(HANDLERS))}")

    heart = Heart(pid)
    heart.start()

    idle_since = time.time()
    last_scan = 0.0
    last_dir_ns = -1
    try:
        while not _stop:
            if heart.lost:
                say("замок перехвачен другим процессом — выхожу, "
                    "чтобы не оказалось двух исполнителей")
                return 0

            try:
                dir_ns = jobs.JOBS_DIR.stat().st_mtime_ns
            except OSError:
                dir_ns = 0
            due = (dir_ns != last_dir_ns) or (time.time() - last_scan > SCAN_EVERY_SEC)
            if not due:
                time.sleep(POLL_SEC)
                continue
            last_dir_ns, last_scan = dir_ns, time.time()

            # Отменённые снимаем до того, как брать в работу: смысл отмены в
            # том, чтобы задание, до которого ещё не дошли, не пошло считаться.
            for job in jobs.listing(limit=200, states=(jobs.QUEUED,)):
                if jobs.is_cancelled(job["id"]):
                    jobs.mark_cancelled(job["id"])
                    say(f"{job['id']}: отменено до начала")

            job = jobs.claim_next(f"pid{pid}")
            if job is None:
                if IDLE_EXIT_SEC and time.time() - idle_since > IDLE_EXIT_SEC:
                    say(f"простой {IDLE_EXIT_SEC:.0f} c — выхожу. "
                        f"Следующее задание поднимет меня заново "
                        f"(ensure_worker), это занимает пару секунд.")
                    return 0
                time.sleep(POLL_SEC)
                continue

            heart.job = job["id"]
            run_job(job)
            heart.job = ""
            idle_since = time.time()
            # Уборка после работы, а не по расписанию: только что стало на
            # одно завершённое задание больше, и это единственный момент,
            # когда список действительно вырос.
            killed = jobs.prune()
            if killed:
                say(f"убрано старых заданий: {killed}")
    finally:
        heart.halt()
        jobs.release_lock(pid)
        say("воркер остановлен")
    return 0


def main() -> int:
    config.ensure_dirs()
    return loop()


if __name__ == "__main__":
    sys.exit(main())
