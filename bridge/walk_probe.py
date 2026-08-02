"""Пошаговый прогон физики: можно ли по сцене ходить.

«Побегал - вроде нормально» проверкой не является. Здесь игрок ведётся
программно заданное число шагов, а на выходе - где встал на опору, сколько
прошёл, где упёрся и из чего вообще состоят столкновения сцены.

Работает в --headless, и это не спорит с граблей про снятие кадров: физика
идёт своим циклом и отрисовки не требует. Не рисуется только картинка.

Первый же прогон окупил себя: игрок падал двести метров вниз, потому что
точка появления стояла за торцом коридора. По кадру это выглядело бы как
«чёрный экран», и искать причину пришлось бы в свете.

    python -m bridge.walk_probe [сцена] [шагов]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Any

from server import config
from server.errors import PipelineError

from .import_asset import RESULT_PREFIX, win_path
from .shot_scene import SHOT_TIMEOUT_SEC, resolve_scene

# Шагов физики в секунде - столько же, сколько у Godot по умолчанию. Нужно,
# чтобы переводить шаги в секунды: 300 шагов это пять секунд ходьбы.
PHYSICS_HZ = 60


def probe_walk(scene: str = "walk", steps: int = 300,
               move: tuple[float, float] = (0.0, -1.0),
               start: tuple[float, float, float] | None = None) -> dict[str, Any]:
    res_path = resolve_scene(scene)
    cfg: dict[str, Any] = {"scene": res_path, "steps": int(steps),
                           "move": [move[0], move[1]]}
    if start is not None:
        cfg["start"] = list(start)

    cmd = [
        str(config.GODOT), "--headless",
        "--path", win_path(config.GAME_DIR),
        "res://tools/walk_probe.tscn",
        "--", json.dumps(cfg, ensure_ascii=False),
    ]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=SHOT_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        raise PipelineError(
            "walk", f"прогон не кончился за {SHOT_TIMEOUT_SEC} с",
            hint="уменьши steps: 300 шагов это пять секунд игрового времени",
        ) from None

    out = (proc.stdout or "") + (proc.stderr or "")
    payload = None
    for line in out.splitlines():
        if line.startswith(RESULT_PREFIX):
            payload = json.loads(line[len(RESULT_PREFIX):])
            break
    if payload is None:
        raise PipelineError(
            "walk", "прогон не вернул результата",
            hint="хвост вывода:\n" + "\n".join(out.strip().splitlines()[-10:]))

    payload["elapsed_sec"] = round(time.time() - t0, 1)
    payload["sim_sec"] = round(int(steps) / PHYSICS_HZ, 1)
    return payload


def describe(r: dict[str, Any]) -> str:
    lines = [
        f"старт {r['start']} -> {r['end']}, прошёл {r['walked_m']} м "
        f"за {r['sim_sec']} с игрового времени ({r['elapsed_sec']} с настоящего)",
    ]
    if r.get("floor_at_step", -1) > 0:
        lines.append(f"опора найдена на шаге {r['floor_at_step']}")
    else:
        lines.append("ОПОРЫ НЕТ: игрок проваливается. Проверь, что точка "
                     "появления внутри локации и что у ассета есть коллайдер")
    for c in r.get("collision", []):
        extra = ""
        if "faces" in c:
            extra = (f", {c['faces']} граней, от {c['low']} до {c['high']}")
        lines.append(f"  тело {c['body']}: {c['shape']}{extra}")
    return "\n".join(lines)


def main() -> None:
    scene = sys.argv[1] if len(sys.argv) > 1 else "walk"
    steps = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    try:
        print(describe(probe_walk(scene, steps=steps)))
    except PipelineError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
