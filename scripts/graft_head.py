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

# Доля высоты сверху, по которой ВЫРАВНИВАЕМ. Берётся большой и совпадает с
# долей, по которой резался снимок: чем больше общей поверхности, тем
# устойчивее ICP.
HEAD_SHARE = 0.40

# Доля высоты сверху, по которой СШИВАЕМ. Это другое число, и разделение
# принципиально. Сшивать по груди нельзя: там бюст и тело разной ширины, и
# оболочки не сходятся - между ними остаётся щель, которую не закрыть ни
# нахлёстом, ни объединением. Шея - самое узкое место, сечения там совпадают.
JOIN_SHARE = 0.30

# Порог качества. Средняя невязка считается в долях высоты головы: 5% - это
# примерно сантиметр на человеческой голове, ещё терпимо.
MAX_ERROR = 0.05


def resolve(spec: str) -> Path:
    """Принимает m_xxx или m_xxx:другой_файл.glb.

    Второй вид нужен, когда рядом с основной моделью лежит вариант с иными
    настройками экспорта, а заводить под него отдельную запись незачем.
    """
    mid, _, fname = spec.partition(":")
    return config.OUTPUT_DIR / mid / (fname or "model.glb")


def load(spec: str) -> trimesh.Trimesh:
    glb = resolve(spec)
    if not glb.exists():
        raise SystemExit(f"нет модели {glb}")
    mesh = trimesh.load(glb, force="mesh")
    print(f"  {spec}: {len(mesh.vertices)} вершин, габарит {mesh.extents.round(3)}")
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

    # --------------------------------------------------------------------- #
    # Совмещение
    # --------------------------------------------------------------------- #
    # Свободный поиск поворота здесь ВРЕДЕН. mesh_other начинает с главных
    # осей, а у головы с распущенными волосами масса спереди и сзади похожа -
    # и алгоритм разворачивает её на 180 градусов. Невязка при этом выходит
    # прекрасная (3%), потому что силуэт совпадает; лицо просто оказывается
    # на затылке.
    #
    # Между тем поворот искать не нужно вовсе: обе модели сделаны одним
    # генератором с фронтальных снимков и уже смотрят в одну сторону.
    # Достаточно масштаба и сдвига, то есть совмещения габаритов.
    def bbox_transform(src, dst):
        s = float(np.mean(dst.extents / np.maximum(src.extents, 1e-9)))
        m = np.eye(4)
        m[:3, :3] *= s
        m[:3, 3] = dst.bounds.mean(axis=0) - s * src.bounds.mean(axis=0)
        return m

    # Но и совсем без поворота нельзя: две генерации выбирают каноническую
    # ориентацию каждая свою, и голова приезжает повёрнутой вокруг вертикали.
    # Поэтому угол ПЕРЕБИРАЕТСЯ, а не ищется градиентно: перебор по всему
    # кругу не застревает в ложном минимуме, а мы вдобавок видим всю кривую
    # и можем судить, есть ли однозначный ответ.
    def yaw(deg):
        m = np.eye(4)
        c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
        i, j = [k for k in range(3) if k != axis]
        m[i, i], m[i, j], m[j, i], m[j, j] = c, -s, s, c
        return m

    center = head.bounds.mean(axis=0)
    to_center = np.eye(4); to_center[:3, 3] = -center
    from_center = np.eye(4); from_center[:3, 3] = center

    probe = head.sample(1500)
    curve = []
    for deg in range(0, 360, 15):
        turned = head.copy()
        turned.apply_transform(from_center @ yaw(deg) @ to_center)
        m = bbox_transform(turned, target)
        pts = trimesh.transform_points(
            trimesh.transform_points(probe, from_center @ yaw(deg) @ to_center), m)
        d = np.abs(trimesh.proximity.signed_distance(target, pts))
        curve.append((float(np.mean(d)), deg, m @ from_center @ yaw(deg) @ to_center))

    curve.sort()
    print("\n  перебор поворота (лучшие шесть):")
    for err, deg, _ in curve[:6]:
        print(f"     {deg:3d}°  невязка {err:.4f}")
    best_err, best_deg, matrix = curve[0]

    # Сравнивать надо с ДАЛЁКИМ углом, а не со следующим в списке: соседние
    # 15 градусов дают почти ту же невязку всегда, и такая проверка кричала
    # бы о двусмысленности на каждом запуске. Опасен другой случай - когда
    # похоже сидит поворот на 90 или 180 градусов.
    def far(deg):
        d = abs(deg - best_deg) % 360
        return min(d, 360 - d) > 45

    rivals = [e for e, d, _ in curve if far(d)]
    ratio = (rivals[0] / max(best_err, 1e-9)) if rivals else float("inf")
    print(f"  выбран {best_deg}°; лучший из далёких углов хуже в {ratio:.2f} раза")
    if ratio < 1.3:
        print("  ВНИМАНИЕ: другой поворот сидит почти так же, ориентация "
              "ненадёжна - посмотри на результат внимательно")

    # Уточняем ICP от найденного угла - он уже в правильной окрестности
    head_pts = head.sample(4000)
    target_pts = target.sample(4000)
    matrix, _, cost = trimesh.registration.icp(
        head_pts, target_pts, initial=matrix, scale=True, max_iterations=60)

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

    join_share = float(sys.argv[4]) if len(sys.argv) > 4 else JOIN_SHARE
    join = hi - (hi - lo) * join_share
    print(f"выравнивание по верхним {share:.0%}, сшивка по {join_share:.0%} "
          f"(уровень {join:.4f})")

    tag = f"{body_id}_{head_id}".replace(":", "-").replace(".glb", "")
    out = config.CACHE_DIR / f"graft_{tag}.json"
    out.write_text(json.dumps({
        "body": str(resolve(body_id)),
        "head": str(resolve(head_id)),
        "matrix": matrix.tolist(),
        "up_axis": axis,
        "cut": float(join),
        "align_cut": float(cut),
        "error": err,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nпреобразование: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
