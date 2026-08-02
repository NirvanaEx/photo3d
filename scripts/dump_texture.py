"""Достать текстуры из GLB и посмотреть на них.

    python dump_texture.py m_cee258

Рендер показывает, КАК выглядит модель, но не отвечает, где именно сломалось:
в развёртке, в самой карте или в материале. Карта, вынутая и разложенная
рядом, отвечает.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/mnt/d/Develop/photo3d")

from PIL import Image  # noqa: E402

from server import config  # noqa: E402


def main() -> int:
    mid = sys.argv[1]
    glb = config.OUTPUT_DIR / mid / "model.glb"
    if not glb.exists():
        print(f"нет {glb}")
        return 1

    import trimesh

    scene = trimesh.load(glb)
    out_dir = config.OUTPUT_DIR / mid / "textures"
    out_dir.mkdir(parents=True, exist_ok=True)

    found = 0
    geoms = scene.geometry.values() if hasattr(scene, "geometry") else [scene]
    for gi, geom in enumerate(geoms):
        mat = getattr(getattr(geom, "visual", None), "material", None)
        if mat is None:
            continue
        for attr in ("baseColorTexture", "image", "emissiveTexture",
                     "metallicRoughnessTexture", "normalTexture"):
            im = getattr(mat, attr, None)
            if not isinstance(im, Image.Image):
                continue
            dst = out_dir / f"{gi}_{attr}.png"
            im.save(dst)
            print(f"  {attr}: {im.size} {im.mode} -> {dst.name}")
            found += 1

    if not found:
        print("текстур в материале не нашлось")
        return 1
    print(f"\nпапка: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
