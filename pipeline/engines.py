"""Движки генерации.

Интерфейс один, реализаций несколько. Сейчас есть только StubEngine - он не
трогает GPU и нужен, чтобы отладить всю обвязку до скачивания весов TRELLIS.
Позже рядом встанет TrellisEngine с тем же generate(), и подмена будет
переключателем PHOTO3D_ENGINE, без правок в MCP-слое.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import numpy as np
import trimesh
from PIL import Image


class Engine(Protocol):
    name: str
    needs_gpu: bool

    def generate(
        self, image_path: Path, out_glb: Path, seed: int, mode: str
    ) -> dict[str, Any]: ...


# --------------------------------------------------------------------------- #
# Заглушка
# --------------------------------------------------------------------------- #

def _foreground_mask(rgba: np.ndarray) -> np.ndarray:
    """Силуэт объекта. Если есть альфа - берём её, иначе отделяем фон
    по отличию от медианной яркости рамки кадра."""
    alpha = rgba[..., 3]
    if alpha.min() < 0.99:
        return alpha > 0.5
    lum = rgba[..., :3].mean(axis=2)
    border = np.concatenate([lum[0], lum[-1], lum[:, 0], lum[:, -1]])
    bg = float(np.median(border))
    mask = np.abs(lum - bg) > 0.12
    if mask.sum() < 16:  # фон неотличим - берём кадр целиком
        mask[:] = True
    return mask


def _edge_distance(mask: np.ndarray) -> np.ndarray:
    """Расстояние до края силуэта через последовательные эрозии.
    Обходимся без scipy: сетка маленькая, цикл дешёвый."""
    dist = np.zeros(mask.shape, np.float32)
    cur = mask.copy()
    step = 0
    while cur.any() and step < max(mask.shape):
        step += 1
        dist[cur] = step
        e = cur.copy()
        e[1:, :] &= cur[:-1, :]
        e[:-1, :] &= cur[1:, :]
        e[:, 1:] &= cur[:, :-1]
        e[:, :-1] &= cur[:, 1:]
        cur = e
    return dist


class StubEngine:
    """Надувает силуэт фотографии в объём: две зеркальные поверхности,
    сшитые по контуру. Настоящей реконструкции здесь нет и не задумано -
    задача в том, чтобы форма явно зависела от входного кадра. Тогда,
    посмотрев на турнтейбл, сразу видно, что цепочка отработала на моём
    файле, а не отрендерила случайную заглушку.
    """

    name = "stub"
    needs_gpu = False

    def generate(
        self, image_path: Path, out_glb: Path, seed: int = 0, mode: str = "fast"
    ) -> dict[str, Any]:
        grid = 72 if mode == "fast" else 128
        img = Image.open(image_path).convert("RGBA").resize((grid, grid), Image.LANCZOS)
        rgba = np.asarray(img).astype(np.float32) / 255.0

        mask = _foreground_mask(rgba)
        dist = _edge_distance(mask)
        dmax = float(dist.max())
        if dmax <= 1.0:
            dist = mask.astype(np.float32)
            dmax = 1.0

        # На контуре высота ровно 0 - там передняя и задняя половины
        # смыкаются и сварятся в merge_vertices, давая замкнутую оболочку.
        # Порог 2, а не 1: квад строится только когда в силуэте все четыре
        # угла, поэтому фактический край сетки лежит на пиксель внутрь от
        # границы маски. С порогом 1 этот край повисал бы на ненулевой
        # высоте и оболочка оставалась бы открытой.
        flat = 2.0
        norm = np.clip((dist - flat) / max(dmax - flat, 1e-6), 0.0, 1.0)
        height = 0.35 * np.power(norm, 0.6)

        h, w = mask.shape
        idx = -np.ones(mask.shape, np.int64)
        ys, xs = np.nonzero(mask)
        idx[ys, xs] = np.arange(len(ys))

        px = xs / (w - 1) - 0.5
        py = -(ys / (h - 1) - 0.5)  # ось Y изображения смотрит вниз
        pz = height[ys, xs]

        front = np.stack([px, py, pz], axis=1)
        back = np.stack([px, py, -pz], axis=1)
        verts = np.concatenate([front, back], axis=0)
        n = len(front)

        # Квад строим только там, где все четыре угла внутри силуэта
        a, b = idx[:-1, :-1], idx[:-1, 1:]
        c, d = idx[1:, 1:], idx[1:, :-1]
        ok = (a >= 0) & (b >= 0) & (c >= 0) & (d >= 0)
        a, b, c, d = a[ok], b[ok], c[ok], d[ok]

        faces = np.concatenate([
            np.stack([a, b, c], axis=1),
            np.stack([a, c, d], axis=1),
            np.stack([a + n, c + n, b + n], axis=1),  # обратная намотка
            np.stack([a + n, d + n, c + n], axis=1),
        ], axis=0)

        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        mesh.merge_vertices()
        mesh.remove_unreferenced_vertices()
        mesh.fix_normals()

        # Нормируем габарит в единицу - камера потом кадрирует одинаково
        extent = float(max(mesh.extents))
        if extent > 0:
            mesh.apply_scale(1.0 / extent)
        mesh.apply_translation(-mesh.centroid)

        out_glb.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(out_glb)

        return {
            "engine": self.name,
            "mode": mode,
            "seed": seed,
            "vertices": int(len(mesh.vertices)),
            "faces": int(len(mesh.faces)),
            "watertight": bool(mesh.is_watertight),
            "grid": grid,
        }


def get_engine(name: str) -> Engine:
    if name == "stub":
        return StubEngine()
    raise ValueError(
        f"движок {name!r} неизвестен. Сейчас доступен только 'stub'; "
        "'trellis' появится после сборки GPU-контейнера"
    )
