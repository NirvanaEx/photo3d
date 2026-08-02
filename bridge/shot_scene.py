"""Кадры из сцены Godot - глаза агента в собранном мире.

Без картинок мир собирается вслепую: по тексту .tscn нельзя понять, стоит ли
предмет на полу или висит в воздухе, не съел ли туман дальнюю стену, не
пересвечено ли солнце. Ровно та же причина, по которой photo_to_3d возвращает
рендеры, а не одни цифры.

Съёмка идёт С ОКНОМ. В --headless драйвер отрисовки пустой, кадров не
рисуется вовсе, и ожидание отрисовки не разрешается никогда - см.
docs/PITFALLS.md. Окно живёт две-четыре секунды и закрывается само.

Вместе с кадрами возвращаются ОШИБКИ СКРИПТОВ из вывода движка. Красивый
кадр не означает работающую сцену: скрипт может падать каждый кадр, а
картинка при этом выйдет нормальной.

    python -m bridge.shot_scene [сцена] [сколько кадров]
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from server import config
from server.errors import PipelineError

from .import_asset import RESULT_PREFIX, win_path

# Кадры кладутся в кэш, а не в game/: это производное, и его не жалко потерять.
SHOTS_DIR = config.CACHE_DIR / "shots"

# Строки, по которым движок сообщает о поломке. Godot печатает их в stderr
# вперемешку с прочим, поэтому ловим по началу строки.
_ERROR_MARKS = ("ERROR:", "SCRIPT ERROR:", "USER ERROR:")
_AT_LINE = re.compile(r"^\s+at: ")

# Своё ограничение, короче импортного: съёмка идёт секунды, и висящее окно
# должно оборваться быстро - вызов MCP блокирующий, за ним ждёт агент.
SHOT_TIMEOUT_SEC = int(os.environ.get("PHOTO3D_SHOT_TIMEOUT", "120"))


def resolve_scene(raw: str) -> str:
    """Путь к сцене в любом виде -> res://...

    Принимаются: 'main', 'scenes/main', 'scenes/main.tscn',
    'res://scenes/main.tscn' и абсолютный путь внутри game/. Мы уже приняли
    это правило для фотографий (windows-путь, POSIX-путь, просто имя) - у
    сцен ровно та же беда, называть их будут с обеих сторон.
    """
    s = (raw or "main").strip().replace("\\", "/")
    if s.startswith("res://"):
        return s if s.endswith(".tscn") else s + ".tscn"

    p = Path(s)
    if p.is_absolute():
        try:
            s = str(p.resolve().relative_to(config.GAME_DIR.resolve())).replace("\\", "/")
        except ValueError:
            raise PipelineError(
                "shot",
                f"сцена {raw!r} лежит вне проекта игры",
                hint=f"сцены живут внутри {config.GAME_DIR}/scenes",
            ) from None

    if not s.endswith(".tscn"):
        s += ".tscn"
    if "/" not in s:
        s = "scenes/" + s

    # Проверяем здесь, а не внутри движка: отсюда видно, какие сцены есть, и
    # ошибка получается с готовым списком вместо «нет такого файла». То же
    # правило, что у ModelNotFound.
    if not (config.GAME_DIR / s).is_file():
        known = sorted(p.stem for p in (config.GAME_DIR / "scenes").glob("*.tscn"))
        raise PipelineError(
            "shot",
            f"сцены {raw!r} нет",
            hint=("доступны: " + ", ".join(known) if known
                  else "в game/scenes нет ни одной сцены - создай .tscn текстом"),
        )
    return "res://" + s


def _errors(out: str) -> list[str]:
    found: list[str] = []
    keep_next = False
    for line in out.splitlines():
        if line.startswith(_ERROR_MARKS):
            found.append(line.strip())
            keep_next = True
        elif keep_next and _AT_LINE.match(line):
            found[-1] += "  " + line.strip()
            keep_next = False
        else:
            keep_next = False
    # Одна и та же ошибка печатается каждый кадр - показывать её десять раз
    # значит утопить в ней всё остальное.
    seen: dict[str, int] = {}
    for e in found:
        seen[e] = seen.get(e, 0) + 1
    return [e if n == 1 else f"{e}  (×{n})" for e, n in seen.items()][:8]


def shot_scene(scene: str = "main", views: int = 1, azimuth: float | None = None,
               elevation: float = 15.0, distance: float = 1.1,
               fov: float = 65.0, res: int = 1024,
               unshaded: bool = False) -> dict[str, Any]:
    res_path = resolve_scene(scene)
    if not config.GODOT.exists():
        raise PipelineError(
            "shot", f"движок не найден: {config.GODOT}",
            hint=("положи Godot 4.7 в C:\\Tools\\Godot или укажи путь в "
                  "PHOTO3D_GODOT (нужна консольная сборка)"))

    name = res_path[len("res://"):].removesuffix(".tscn").replace("/", "_")
    out_dir = SHOTS_DIR / name
    if out_dir.exists():
        # Кадры прошлого вызова стираются: иначе при views=1 рядом останутся
        # ракурсы прошлого облёта, и агент увидит смесь двух прогонов.
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = {
        "scene": res_path,
        "out": win_path(out_dir),
        "views": max(int(views), 1),
        "azimuth": azimuth,
        "elevation": elevation,
        "distance": distance,
        "fov": fov,
        "unshaded": bool(unshaded),
    }
    cmd = [
        str(config.GODOT),
        "--path", win_path(config.GAME_DIR),
        "res://tools/shot.tscn",
        "--resolution", f"{int(res)}x{int(round(int(res) * 9 / 16))}",
        "--", json.dumps(cfg, ensure_ascii=False),
    ]

    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=SHOT_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        raise PipelineError(
            "shot",
            f"Godot не ответил за {SHOT_TIMEOUT_SEC} с",
            hint=("самая частая причина - запуск без окна: в --headless кадров "
                  "не рисуется вовсе и ожидание отрисовки висит вечно "
                  "(docs/PITFALLS.md). Проверь, что --headless не подмешался "
                  "в PHOTO3D_GODOT"),
        ) from None

    out = (proc.stdout or "") + (proc.stderr or "")
    errors = _errors(out)

    payload = None
    for line in out.splitlines():
        if line.startswith(RESULT_PREFIX):
            payload = json.loads(line[len(RESULT_PREFIX):])
            break
    if payload is None:
        tail = "\n".join(out.strip().splitlines()[-12:])
        raise PipelineError(
            "shot", "съёмка не вернула результата",
            hint=("скрипт game/tools/shot.gd не отработал. Ошибки движка:\n"
                  + ("\n".join(errors) if errors else tail)))
    if not payload.get("ok"):
        raise PipelineError(
            "shot", payload.get("error") or "кадры не сняты",
            hint=("проверь путь сцены и то, что в ней есть геометрия: "
                  f"снимали {res_path}"))

    shots = []
    for s in payload.get("shots", []):
        f = out_dir / f"{s['name']}.png"
        if f.exists():
            shots.append({"name": s["name"], "path": f, "spread": s.get("spread", 0)})

    blank = [s["name"] for s in shots if s["spread"] < 0.01]
    return {
        "scene": res_path,
        "shots": shots,
        "blank": blank,
        "stats": payload.get("stats", {}),
        "errors": errors,
        "elapsed_sec": round(time.time() - t0, 1),
    }


def describe(r: dict[str, Any]) -> str:
    st = r["stats"]
    size = st.get("size", [0, 0, 0])
    lines = [
        f"{r['scene']}: {st.get('kind', '?')}, "
        f"{st.get('meshes', 0)} мешей, {st.get('triangles', 0)} треугольников, "
        f"{st.get('lights', 0)} источников света",
        f"габариты {size[0]} x {size[1]} x {size[2]} м; "
        f"кадров {len(r['shots'])} за {r['elapsed_sec']} с",
    ]
    for l in st.get("light_energy", []):
        lines.append(f"  свет {l['node']} ({l['class']}): яркость {l['energy']}")
    if r["blank"]:
        lines.append("ПУСТЫЕ КАДРЫ: " + ", ".join(r["blank"])
                     + " - камера смотрит мимо сцены или свет выключен")
    if r["errors"]:
        lines.append("ошибки движка:")
        lines += ["  " + e for e in r["errors"]]
    return "\n".join(lines)


def main() -> None:
    scene = sys.argv[1] if len(sys.argv) > 1 else "main"
    views = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    try:
        r = shot_scene(scene, views=views)
    except PipelineError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1) from None
    print(describe(r))
    for s in r["shots"]:
        print(f"  {s['path']}  разброс {s['spread']}")


if __name__ == "__main__":
    main()
