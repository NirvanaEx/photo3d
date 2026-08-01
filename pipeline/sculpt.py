"""Подготовка меша под скульптинг.

Сырой результат генератора - треугольный суп после marching cubes: неманифолдный,
в дырах, с мусорными ошмётками. Лепить по такому нельзя: подразделение ломается,
кисти ведут себя непредсказуемо. Нужна замкнутая оболочка с равномерной
четырёхугольной сеткой.

Цепочка из трёх шагов, и порядок здесь принципиален:

1. pymeshlab  - убрать дубли и вырожденные грани, развести неманифолдные рёбра,
                выбросить мелкие несвязные куски, закрыть дыры
2. Blender    - Voxel Remesh: перестроить оболочку целиком. Точечный ремонт
                не спасает меш с десятками разрывов, а воксели дают
                гарантированно замкнутый результат, сразу в квадах
3. Blender    - QuadriFlow: переложить в квады с ровными петлями под нужное
                число граней. Капризен и на плохом входе молча отказывается,
                поэтому результат проверяется по счётчику граней, а не по
                коду возврата. Если отказался - остаётся воксельная сетка,
                она тоже целиком из квадов и для лепки пригодна
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from server import config
from server.errors import PipelineError

BLENDER_SCRIPT = config.BLENDER_SCRIPTS / "sculpt_prep.py"

# Фильтры, которых может не оказаться в конкретной сборке pymeshlab.
# Их отсутствие - не повод падать, но повод сказать об этом вслух.
_OPTIONAL = (
    "meshing_remove_connected_component_by_face_number",
    "meshing_close_holes",
    "meshing_re_orient_faces_coherently",
)


def _measures(ms) -> dict[str, Any]:
    m = ms.current_mesh()
    out = {"vertices": m.vertex_number(), "faces": m.face_number()}
    try:
        t = ms.get_topological_measures()
        out.update({
            "non_manifold_edges": int(t.get("non_two_manifold_edges", -1)),
            "boundary_edges": int(t.get("boundary_edges", -1)),
            "components": int(t.get("connected_components_number", -1)),
            "holes": int(t.get("number_holes", -1)),
            "two_manifold": bool(t.get("is_mesh_two_manifold", False)),
        })
    except Exception:  # noqa: BLE001
        pass
    return out


def repair(src: Path, dst: Path, min_component_faces: int = 25) -> dict[str, Any]:
    """Ремонт средствами pymeshlab. Возвращает замеры до и после."""
    import pymeshlab

    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(str(src))
    before = _measures(ms)
    skipped: list[str] = []

    ms.meshing_remove_duplicate_vertices()
    ms.meshing_remove_duplicate_faces()
    ms.meshing_remove_null_faces()
    ms.meshing_remove_unreferenced_vertices()
    ms.meshing_repair_non_manifold_edges()
    ms.meshing_repair_non_manifold_vertices()

    # Мелкие ошмётки после разведения неманифолдных рёбер только мешают
    # вокселизации: они дают паразитные оболочки внутри объёма.
    if hasattr(ms, "meshing_remove_connected_component_by_face_number"):
        try:
            ms.meshing_remove_connected_component_by_face_number(
                mincomponentsize=min_component_faces
            )
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"remove_small_components ({type(exc).__name__})")
    else:
        skipped.append("remove_small_components (нет в сборке)")

    for name, kw in (
        ("meshing_close_holes", {"maxholesize": 1000}),
        ("meshing_re_orient_faces_coherently", {}),
    ):
        if not hasattr(ms, name):
            skipped.append(f"{name} (нет в сборке)")
            continue
        try:
            getattr(ms, name)(**kw)
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"{name} ({type(exc).__name__})")

    dst.parent.mkdir(parents=True, exist_ok=True)
    ms.save_current_mesh(str(dst))
    return {"before": before, "after": _measures(ms), "skipped": skipped}


def remesh(src: Path, dst: Path, target_faces: int = 5000,
           try_quadriflow: bool = False) -> dict[str, Any]:
    """Voxel Remesh внутри Blender до заданного числа граней."""
    if not config.BLENDER.exists():
        raise PipelineError("sculpt", f"Blender не найден: {config.BLENDER}",
                            hint="прогони scripts/setup-host.sh из-под root")

    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(config.BLENDER), "-b", "--factory-startup", "-noaudio",
        "-P", str(BLENDER_SCRIPT), "--",
        "--in", str(src), "--out", str(dst),
        "--target-faces", str(target_faces),
    ]
    if try_quadriflow:
        cmd.append("--try-quadriflow")
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=config.RENDER_TIMEOUT_SEC)
    out = (proc.stdout or "") + (proc.stderr or "")

    stats: dict[str, Any] = {}
    for line in out.splitlines():
        if line.startswith("SCULPT_STATS "):
            stats = json.loads(line[len("SCULPT_STATS "):])
    if proc.returncode != 0 or not stats or not dst.exists():
        raise PipelineError(
            "sculpt", "Blender не построил сетку под скульптинг",
            hint="полный вывод в log.txt папки модели",
        )
    stats["log"] = out
    return stats


def prepare(src_glb: Path, workdir: Path, target_faces: int = 5000,
            try_quadriflow: bool = False) -> tuple[Path, dict[str, Any]]:
    """Полный путь: ремонт -> перестройка -> готовый к лепке GLB."""
    repaired = workdir / "repaired.ply"
    result = workdir / "sculpt.glb"
    rep = repair(src_glb, repaired)
    rem = remesh(repaired, result, target_faces, try_quadriflow)
    return result, {"repair": rep, "remesh": {k: v for k, v in rem.items() if k != "log"},
                    "log": rem.get("log", "")}
