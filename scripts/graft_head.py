"""Посадить подробную голову на тело: вычисление преобразования.

    python graft_head.py m_750ef9 m_XXXXXX [доля_головы]

Зачем всё это. Объём считается сеткой 512^3, и в неё помещается вся фигура,
поэтому на лицо приходится две-три ячейки - выходит каша. Если сгенерировать
голову отдельно по обрезанному снимку, те же 512^3 достанутся ей одной, и
подробностей станет втрое больше по каждой оси. Остаётся посадить её обратно.

Сложность именно в посадке: обе модели нормируются каждая в свой единичный
куб, поэтому голова приходит в чужом масштабе и своём повороте.

Порядок:
  1. отрезать у тела верхнюю долю - это его собственная голова, она и служит
     мишенью;
  2. совместить с ней подробную голову: сперва по габаритам, затем ICP;
  3. проверить качество совмещения ЧИСЛОМ, а не на глаз, и отказаться,
     если сошлось плохо - криво посаженная голова хуже, чем никакой.

Преобразование сохраняется в JSON и применяется уже в Blender, где есть
материалы. Здесь работа только с геометрией.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

from server import config  # noqa: E402

# Доля высоты фигуры сверху, которую занимает голова с шеей. Совпадает с той,
# по которой резался снимок в crop_part.py - иначе мишень и источник были бы
# про разные части тела.
HEAD_SHARE = 0.40

# Порог качества. Средняя невязка считается в долях высоты головы: 5% - это
# примерно сантиметр на человеческой голове, ещё терпимо.
MAX_ERROR = 0.05


def load(mid: str) -> trimesh.Trimesh:
    glb = config.OUTPUT_DIR / mid / "model.glb"
    if not glb.exists():
        raise SystemExit(f"нет модели {glb}")
    mesh = trimesh.load(glb, force="mesh")
    print(f"  {mid}: {len(mesh.vertices)} вершин, габарит {mesh.extents.round(3)}")
    return mesh


def up_axis(mesh: trimesh.Trimesh) -> int:
    """Вертикаль - ось наибольшего размера. У стоящей фигуры это верно
    всегда, а угадывать соглашение об осях по формату мы уже обжигались."""
    return int(np.argmax(mesh.extents))


def main() -> int:
    body_id = sys.argv[1]
    head_id = sys.argv[2]
    share = float(sys.argv[3]) if len(sys.argv) > 3 else HEAD_SHARE

    print("загрузка:")
    body = load(body_id)
    head = load(head_id)

    axis = up_axis(body)
    print(f"вертикаль тела: ось {'XYZ'[axis]}")

    lo = body.bounds[0][axis]
    hi = body.bounds[1][axis]
    cut = hi - (hi - lo) * share

    normal = np.zeros(3)
    normal[axis] = 1.0
    target = body.slice_plane(plane_origin=normal * cut, plane_normal=normal)
    if target.is_empty or len(target.vertices) < 100:
        print("не удалось выделить голову у тела")
        return 1
    print(f"мишень (верхние {share:.0%} тела): {len(target.vertices)} вершин, "
          f"габарит {target.extents.round(3)}")

    # reflection=False обязательно: с отражением алгоритм охотно "совместит"
    # голову зеркально, и получится левое ухо справа
    # возвращает ровно два значения: матрицу и среднюю квадратичную невязку
    matrix, cost = trimesh.registration.mesh_other(
        head, target, samples=2000, scale=True,
        icp_first=20, icp_final=100, reflection=False)

    moved = head.copy()
    moved.apply_transform(matrix)

    # Невязку меряем честно: расстояние от точек переставленной головы до
    # поверхности мишени, в долях её высоты
    pts = moved.sample(3000)
    dist = np.abs(trimesh.proximity.signed_distance(target, pts))
    scale_ref = float(target.extents[axis])
    err = float(np.mean(dist) / scale_ref)

    print(f"\nсовмещение: невязка {err:.3f} ({err * 100:.1f}% высоты головы), "
          f"cost={cost:.5f}")
    print(f"масштаб головы: {np.linalg.norm(matrix[:3, 0]):.3f}")
    print(f"габарит после посадки: {moved.extents.round(3)}")

    if err > MAX_ERROR:
        print(f"\nОТКАЗ: невязка выше порога {MAX_ERROR:.0%}. "
              "Криво посаженная голова хуже, чем никакой.")
        print("Причиной обычно бывает другой поворот или сильно разный обрез.")
        return 1

    out = config.CACHE_DIR / f"graft_{body_id}_{head_id}.json"
    out.write_text(json.dumps({
        "body": body_id,
        "head": head_id,
        "matrix": matrix.tolist(),
        "up_axis": axis,
        "cut": float(cut),
        "error": err,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nпреобразование: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
