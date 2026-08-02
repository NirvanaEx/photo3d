"""Перенос ассета из библиотеки photo3d в проект Godot.

Библиотека и мир живут порознь: data/output - результат генерации, game/ -
сцены, которые из этого результата собираются. Мост переносит GLB, запускает
импорт и проверяет, что доехало.

Проверка обязательна, и вот почему. Импорт Godot сообщает об успехе и тогда,
когда сцена вышла пустой - ровно как операторы Blender возвращают FINISHED,
ничего не сделав. Поэтому результат меряется счётчиками: треугольники,
материалы, карты, габариты. Ноль треугольников - ошибка, а не «импортировано».

Движок исполняется виндовым .exe из WSL через interop. Так сделано потому,
что внутри WSL графика достаётся программным контекстом; здесь это ещё не
важно (импорт не рисует), но кадры снимать придётся тем же движком, и
разводить два разных запуска ради одного проекта незачем.

    python -m bridge.import_asset [model_id]
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from server import config
from server.errors import PipelineError
from server.store import ModelStore

RESULT_PREFIX = "RESULT "
MANIFEST = config.GAME_DIR / "assets.json"


def win_path(p: Path) -> str:
    """Путь в виде, понятном виндовому .exe.

    Godot запускается с Windows-стороны, а вызывающий код живёт в WSL: строку
    /mnt/d/... движок не откроет. Перевод делает wslpath, а не склейка руками -
    точек монтирования может быть несколько, и угадывать их незачем.

    Когда wslpath нет, мы уже на Windows и переводить нечего.
    """
    try:
        out = subprocess.run(["wslpath", "-w", str(p)], capture_output=True,
                             text=True, timeout=15)
    except (FileNotFoundError, subprocess.SubprocessError):
        return str(p)
    if out.returncode != 0:
        return str(p)
    return out.stdout.strip() or str(p)


def _godot(args: list[str], stage: str) -> str:
    if not config.GODOT.exists():
        raise PipelineError(
            stage,
            f"движок не найден: {config.GODOT}",
            hint=("положи портативный Godot 4.7 в C:\\Tools\\Godot или укажи "
                  "путь в PHOTO3D_GODOT. Нужна консольная сборка "
                  "(*_console.exe): обычная не отдаёт вывод"),
        )
    cmd = [str(config.GODOT), "--headless", "--path", win_path(config.GAME_DIR), *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=config.GODOT_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        raise PipelineError(
            stage,
            f"Godot не ответил за {config.GODOT_TIMEOUT_SEC} с",
            hint=("проверь, что запуск идёт с --headless: с окном движок ждёт "
                  "закрытия и висит вечно. Ручная проверка: "
                  f"{config.GODOT} --headless --path {win_path(config.GAME_DIR)} --import"),
        ) from None
    return (proc.stdout or "") + (proc.stderr or "")


def _parse(out: str, stage: str) -> dict[str, Any]:
    for line in out.splitlines():
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX):])
    tail = "\n".join(out.strip().splitlines()[-12:])
    raise PipelineError(
        stage,
        "разбор ассета не вернул результата",
        hint=("скрипт game/tools/inspect_asset.gd не отработал. Хвост вывода "
              f"движка:\n{tail}"),
    )


def _manifest_put(model_id: str, info: dict[str, Any]) -> None:
    """Список того, что уехало в игру.

    Сами ассеты в git не кладутся - они воспроизводятся из data/output, а
    весят десятки мегабайт. Манифест же нужен: по нему видно, из какой модели
    что собрано, и его не восстановить обходом папки.

    Запись через временный файл: обрыв не должен оставить огрызок JSON.
    """
    data: dict[str, Any] = {}
    if MANIFEST.exists():
        try:
            data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    data[model_id] = info
    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, MANIFEST)


def import_asset(model_id: str | None = None, gameready: bool = False,
                 faces: int = 20000, collider: int = 1500) -> dict[str, Any]:
    """Перенести модель в проект игры.

    gameready=True прогоняет её через pipeline.gameready: видимая сетка
    ужимается до бюджета, а рядом кладётся грубая оболочка столкновений с
    суффиксом -colonly, из которой импортёр Godot сам делает тело. Без этого
    по модели можно смотреть, но не ходить: 120 тысяч треугольников в физике
    неподъёмны.
    """
    store = ModelStore()
    mid = store.resolve(model_id)
    src = store.glb(mid)
    if not src.exists():
        raise PipelineError(
            "assets",
            f"у модели {mid} нет model.glb",
            hint="проверь list_models() и возьми модель, у которой есть GLB",
        )

    prep: dict[str, Any] = {}
    name = mid
    if gameready:
        # Кладём в кэш, а не в папку модели: это производное от model.glb,
        # пересобирается за секунды и в библиотеке отдельной карточкой не нужно.
        from pipeline.gameready import prepare
        name = f"{mid}_game"
        cooked = config.CACHE_DIR / "gameready" / f"{name}.glb"
        prep = prepare(src, cooked, faces=faces, collider=collider)
        prep.pop("log", None)
        src = cooked

    config.GAME_ASSETS.mkdir(parents=True, exist_ok=True)
    dst = config.GAME_ASSETS / f"{name}.glb"
    shutil.copy2(src, dst)

    t0 = time.time()
    _godot(["--import"], "assets")
    info = _parse(_godot(
        ["--script", "res://tools/inspect_asset.gd", "--", name], "assets"), "assets")
    elapsed = round(time.time() - t0, 1)

    if not info.get("ok"):
        raise PipelineError(
            "assets",
            f"{name}: {info.get('error') or 'импорт дал пустую сцену'}",
            hint=("открой GLB в любом вьюере и убедись, что в нём есть меш. "
                  "Если есть - удали game/.godot и повтори: кэш импорта мог "
                  "остаться от прежней версии файла"),
        )

    info |= {
        "id": name,
        "from": mid,
        "file": f"assets/models/{name}.glb",
        "mb": round(dst.stat().st_size / 1048576, 1),
        "elapsed_sec": elapsed,
        "imported_at": time.time(),
    }
    if prep:
        info["gameready"] = prep
    _manifest_put(name, info)
    return info


def describe(info: dict[str, Any]) -> str:
    maps = info.get("maps", {})
    have = ", ".join(k for k, v in maps.items() if v) or "нет ни одной"
    size = info.get("size", [0, 0, 0])
    return (
        f"{info['id']} -> {info['file']} ({info['mb']} МБ, {info['elapsed_sec']} с)\n"
        f"  мешей {info['meshes']}, поверхностей {info['surfaces']}, "
        f"треугольников {info['triangles']}, материалов {info['materials']}\n"
        f"  столкновения: тел {info.get('bodies', 0)}, "
        f"форм {info.get('shapes', 0)}\n"
        f"  карты: {have}\n"
        f"  габариты {size[0]} x {size[1]} x {size[2]} м"
    )


def main() -> None:
    model_id = sys.argv[1] if len(sys.argv) > 1 else "last"
    try:
        print(describe(import_asset(model_id)))
    except PipelineError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
