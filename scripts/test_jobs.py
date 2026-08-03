"""Проверка очереди заданий: не «вроде работает», а по шагам с замерами.

Гоняется на движке-заглушке: проверяется обвязка - постановка, подъём
исполнителя, взаимное исключение, отмена, ошибка с подсказкой, - а не
качество генерации. Заглушка считает секунды вместо минут, и весь прогон
укладывается в полминуты.

    /opt/photo3d/venv/bin/python scripts/test_jobs.py

Движок и стиль превью подменяются здесь же, до импорта конфига: воркер
поднимается из этого же процесса и наследует его окружение, поэтому
переменные доходят и до него.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("PHOTO3D_ENGINE", "stub")
# Постановочный оборот на Cycles стоит 45 секунд и к очереди отношения не
# имеет: проверяем обвязку, а не рендер.
os.environ.setdefault("PHOTO3D_PREVIEW_STYLE", "clay")
os.environ.setdefault("PHOTO3D_SPIN_FRAMES", "4")

from server import config, jobs  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok   ' if ok else 'ПЛОХО'} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def main() -> int:
    config.ensure_dirs()
    photo = next((p for p in sorted(config.INPUT_DIR.iterdir())
                  if p.suffix.lower() in (".jpg", ".jpeg", ".png")), None)
    if photo is None:
        print(f"нет ни одного фото в {config.INPUT_DIR} — положи любое и повтори")
        return 2

    was_alive = jobs.worker_status()
    if was_alive.get("alive") and was_alive.get("engine") != config.ENGINE:
        # Не «сейчас будет медленно», а отказ: с чужим движком воркер отклонит
        # все задания проверки (сверка в worker/main.py), и падать будет всё
        # подряд без внятной причины. Лучше сказать об этом до, чем после.
        print(f"воркер уже запущен с движком {was_alive.get('engine')}, "
              f"а проверка идёт на {config.ENGINE}.\n"
              f"Он отклонит её задания. Останови его и повтори:\n"
              f"  kill {was_alive.get('pid')}")
        return 2

    print(f"движок: {config.ENGINE}, исходник: {photo.name}\n")

    # Что за собой убрать. Проверка не должна оставлять в библиотеке заглушки:
    # человек открывает её, чтобы смотреть на свои модели, а не на следы
    # прогонов.
    made: list[str] = []
    models: list[str] = []

    print("1. постановка задания")
    job = jobs.submit("photo_to_3d", {"image": str(photo), "mode": "fast"},
                      by="human", title=photo.name)
    made.append(job["id"])
    check("файл задания появился", (jobs.JOBS_DIR / f"{job['id']}.json").exists(),
          job["id"])
    check("состояние queued", jobs.read(job["id"])["state"] == jobs.QUEUED)

    print("2. подъём исполнителя")
    t0 = time.time()
    st = jobs.ensure_worker()
    check("воркер жив", bool(st.get("alive")),
          f"pid {st.get('pid')}, поднялся за {time.time() - t0:.1f} c")

    print("3. второй воркер не встаёт")
    r = subprocess.run([sys.executable, "-m", "worker.main"],
                       cwd=str(config.ROOT), capture_output=True, text=True,
                       timeout=60)
    last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "нет вывода"
    check("второй экземпляр ушёл сам", "уже работает" in r.stdout, last)

    print("4. задание проходит цикл")
    t0 = time.time()
    done = jobs.wait(job["id"], timeout=900)
    elapsed = time.time() - t0
    check("состояние done", done.get("state") == jobs.DONE,
          f"{done.get('state')} / {done.get('stage')} за {elapsed:.1f} c")
    if done.get("state") == jobs.FAILED:
        print(f"       ошибка: {done['error']}")
    mid = (done.get("result") or {}).get("model_id", "")
    if mid:
        models.append(mid)
    mdir = config.OUTPUT_DIR / mid if mid else None
    views = len(list((mdir / "views").glob("*.png"))) if mdir else 0
    check("модель создана", bool(mid) and mdir.is_dir(), mid)
    check("GLB на месте", bool(mid) and (mdir / "model.glb").exists())
    check("превью отрисованы", views > 0, f"{views} кадров")
    check("этапы записаны", len(done.get("progress", [])) >= 2,
          " → ".join(s["text"] for s in done.get("progress", [])))
    check("id модели проставлен в задании", bool(done.get("model_id")),
          "карточка задания ведёт в папку модели, не дожидаясь конца")

    print("5. отмена задания, до которого ещё не дошли")
    # Два задания подряд: первое займёт исполнителя, второе отменяем, пока оно
    # стоит в очереди. Отменять единственное задание было бы гонкой - воркер
    # успевает взять его за полсекунды.
    busy = jobs.submit("photo_to_3d", {"image": str(photo), "mode": "fast"}, by="human")
    doomed = jobs.submit("photo_to_3d", {"image": str(photo), "mode": "fast"}, by="human")
    made += [busy["id"], doomed["id"]]
    jobs.cancel(doomed["id"])
    got = jobs.wait(doomed["id"], timeout=900)
    check("отменённое не считалось", got.get("state") == jobs.CANCELLED,
          f"{got.get('state')} / {got.get('stage')}")
    busy_done = jobs.wait(busy["id"], timeout=900)
    if (busy_done.get("result") or {}).get("model_id"):
        models.append(busy_done["result"]["model_id"])

    print("6. ошибка несёт подсказку")
    bad = jobs.submit("несуществующий_вид", {}, by="agent")
    made.append(bad["id"])
    got = jobs.wait(bad["id"], timeout=60)
    err = got.get("error", {})
    check("состояние failed", got.get("state") == jobs.FAILED, got.get("state", "?"))
    check("в ошибке есть что делать", bool(err.get("hint")), err.get("hint", ""))

    print("7. очередь видна снаружи")
    lst = jobs.listing(limit=10)
    check("задания перечисляются", len(lst) >= 4, f"{len(lst)} шт.")
    s1 = jobs.stamp()
    # Заведомо неизвестный вид: отпечаток проверяется появлением задания, а
    # платить за ещё одну генерацию ради этого незачем.
    made.append(jobs.submit("проверка_отпечатка", {}, by="agent")["id"])
    check("отпечаток меняется при новом задании", jobs.stamp() != s1)

    print("8. два задания не считаются одновременно")
    # Ради этого всё и затевалось. Человек и агент кладут задания в одну
    # очередь, а видеокарта одна: 9.13 ГБ весов и 10 ГБ на всю WSL не дают
    # двум генерациям идти рядом. Проверяется не «вроде по очереди», а
    # непересечением отрезков работы.
    a = jobs.submit("photo_to_3d", {"image": str(photo)}, by="human")
    b = jobs.submit("photo_to_3d", {"image": str(photo)}, by="agent")
    made += [a["id"], b["id"]]
    ra, rb = jobs.wait(a["id"], 900), jobs.wait(b["id"], 900)
    for job in (ra, rb):
        mid = (job.get("result") or {}).get("model_id")
        if mid:
            models.append(mid)
    first, second = sorted((ra, rb), key=lambda j: j.get("started", 0))
    gap = second.get("started", 0) - first.get("finished", 0)
    check("второе началось после конца первого", gap >= 0,
          f"зазор {gap:+.2f} c "
          f"(первое {first['id']} {first.get('finished', 0) - first.get('started', 0):.1f} c)")
    check("оба доделаны",
          ra.get("state") == jobs.DONE and rb.get("state") == jobs.DONE,
          f"{ra.get('state')}, {rb.get('state')}")

    print("9. чужой движок у исполнителя - отказ, а не тихая заглушка")
    # Тот же приём, что с отменой: первое задание занимает исполнителя на
    # секунду с лишним, и правка второго заведомо успевает лечь до того, как
    # до него дойдут. Проверять на единственном задании было бы гонкой.
    hold = jobs.submit("photo_to_3d", {"image": str(photo)}, by="human")
    alien = jobs.submit("photo_to_3d", {"image": str(photo)}, by="agent")
    made += [hold["id"], alien["id"]]
    jobs.update(alien["id"], engine="движок_которого_нет")
    got = jobs.wait(alien["id"], timeout=900)
    err = got.get("error", {})
    check("задание отклонено", got.get("state") == jobs.FAILED, got.get("state", "?"))
    check("сказано, чей движок и что делать",
          "движок_которого_нет" in err.get("reason", "") and "kill" in err.get("hint", ""),
          err.get("reason", ""))
    held = jobs.wait(hold["id"], timeout=900)
    if (held.get("result") or {}).get("model_id"):
        models.append(held["result"]["model_id"])
    check("отказ не сбил исполнителя", jobs.worker_status().get("alive"),
          "соседнее задание доехало: " + str(held.get("state")))

    print()
    print(f"убираю за собой: {len(models)} моделей-заглушек, {len(made)} заданий")
    for mid in models:
        shutil.rmtree(config.OUTPUT_DIR / mid, ignore_errors=True)
    for jid in made:
        for p in (jobs.JOBS_DIR / f"{jid}.json", jobs.JOBS_DIR / f"{jid}.cancel"):
            p.unlink(missing_ok=True)

    # Своего воркера гасим. Он поднят с PHOTO3D_ENGINE=stub и наследует это
    # окружение, пока живёт; оставленный работать, он встретил бы настоящий
    # вызов заглушкой. Отказ по движку это ловит (см. worker/main.py), но
    # правильнее не создавать положения, которое приходится ловить.
    now = jobs.worker_status()
    if not was_alive.get("alive") and now.get("alive"):
        pid = int(now["pid"])
        os.kill(pid, signal.SIGTERM)
        for _ in range(40):
            if not jobs.worker_status().get("alive"):
                break
            time.sleep(0.25)
        print(f"воркер проверки остановлен (pid {pid})")

    print()
    if FAILED:
        print(f"НЕ ПРОШЛО: {len(FAILED)} — {', '.join(FAILED)}")
        return 1
    print("всё прошло")
    return 0


if __name__ == "__main__":
    sys.exit(main())
