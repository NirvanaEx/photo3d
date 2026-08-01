"""Генерирует студийную карту освещения для 3D-вьюера в браузере.

    /opt/photo3d/venv/bin/python /mnt/d/Develop/photo3d/scripts/make_studio_hdr.py

Пишет web/static/studio.hdr - равнопрямоугольную HDR-панораму с тремя мягкими
источниками, повторяющими схему из Blender: ключевой сверху-слева-спереди,
холодный заполняющий справа, тёплый контровой сзади. Плюс подсвеченная нижняя
полусфера, чтобы модель не проваливалась в черноту снизу.

Именно HDR, а не JPEG: в LDR-картинке яркость源 упирается в единицу, и на
модели не возникает бликов - подсветка выходит плоской. Здесь источники
светят с яркостью в десятки единиц, и металл с глянцем начинают отражать.

Формат Radiance RGBE пишется вручную и без RLE-сжатия: спецификация это
допускает, читатели такое понимают, а кода нужно тридцать строк вместо
зависимости на imageio.
"""
import sys
from pathlib import Path

import numpy as np

OUT = Path("/mnt/d/Develop/photo3d/web/static/studio.hdr")
W, H = 1024, 512


def blob(theta, phi, azimuth_deg, elev_deg, size_deg, intensity, color):
    """Мягкое пятно света на сфере: спад по угловому расстоянию."""
    a = np.radians(azimuth_deg)
    e = np.radians(elev_deg)
    # направление на центр пятна и на каждый пиксель, косинус угла между ними
    cx, cy, cz = np.cos(e) * np.sin(a), np.sin(e), np.cos(e) * np.cos(a)
    px = np.cos(phi) * np.sin(theta)
    py = np.sin(phi)
    pz = np.cos(phi) * np.cos(theta)
    cosang = np.clip(px * cx + py * cy + pz * cz, -1, 1)
    ang = np.degrees(np.arccos(cosang))
    falloff = np.clip(1.0 - (ang / size_deg) ** 2, 0, 1) ** 2
    return falloff[..., None] * np.array(color, np.float32) * intensity


def main() -> int:
    u = (np.arange(W) + 0.5) / W
    v = (np.arange(H) + 0.5) / H
    theta = (u * 2 - 1) * np.pi          # азимут -pi..pi
    phi = (0.5 - v) * np.pi              # высота +pi/2 сверху до -pi/2 снизу
    theta, phi = np.meshgrid(theta, phi)

    # Фон: сверху чуть светлее, снизу тёмная подложка. Без этого нижняя
    # полусфера чёрная и модель снизу проваливается.
    sky = np.clip(np.sin(phi), 0, 1)[..., None] * np.array([0.05, 0.055, 0.07], np.float32)
    ground = np.clip(-np.sin(phi), 0, 1)[..., None] * np.array([0.10, 0.10, 0.11], np.float32)
    img = sky + ground + 0.012

    img += blob(theta, phi, -42, 38, 46, 26.0, (1.00, 0.97, 0.92))   # ключевой
    img += blob(theta, phi, 68, 12, 62, 5.0, (0.80, 0.88, 1.00))    # заполняющий
    img += blob(theta, phi, 168, 26, 40, 12.0, (1.00, 0.92, 0.82))   # контровой

    write_hdr(OUT, img.astype(np.float32))
    print(f"записано: {OUT} ({OUT.stat().st_size} байт, {W}x{H})")
    print(f"яркость: мин {img.min():.3f}, макс {img.max():.1f}, среднее {img.mean():.3f}")
    return 0


def write_hdr(path: Path, rgb: np.ndarray) -> None:
    """Radiance RGBE, плоские строки без RLE."""
    h, w, _ = rgb.shape
    m = np.max(rgb, axis=2)
    rgbe = np.zeros((h, w, 4), np.uint8)
    nz = m > 1e-32
    mant, exp = np.frexp(np.where(nz, m, 1.0))       # m = mant * 2**exp
    scale = np.where(nz, mant * 256.0 / np.where(nz, m, 1.0), 0.0)
    for c in range(3):
        rgbe[..., c] = np.clip(rgb[..., c] * scale, 0, 255).astype(np.uint8)
    rgbe[..., 3] = np.where(nz, np.clip(exp + 128, 0, 255), 0).astype(np.uint8)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(b"#?RADIANCE\n")
        f.write(b"FORMAT=32-bit_rle_rgbe\n\n")
        f.write(f"-Y {h} +X {w}\n".encode())
        f.write(rgbe.tobytes())


if __name__ == "__main__":
    sys.exit(main())
