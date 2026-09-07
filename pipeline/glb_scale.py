"""Впечатать масштаб в GLB, не запуская Blender.

Масштаб человек подбирает глазами в прогулке (web/static/walk.js), и число
живёт в ui.json — то есть только внутри веба. В игру модель уезжает через
bridge/import_asset.py и приезжает туда исходного размера: комната величиной
с табурет. Этот модуль закрывает разрыв.

Почему правкой файла, а не прогоном через Blender: умножение на число не
стоит запуска движка на несколько секунд и пересчёта всей геометрии.
В glTF масштаб — это свойство узла, а не вершин. Достаточно добавить один
корневой узел и сложить под него прежние корни.

Формат GLB простой: заголовок 12 байт (magic, версия, длина), затем чанки
вида [длина, тип, данные]. Первый чанк — JSON, второй — двоичный буфер.
Меняется только JSON, двоичная часть не трогается вовсе.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

MAGIC = 0x46546C67          # "glTF"
CHUNK_JSON = 0x4E4F534A     # "JSON"
CHUNK_BIN = 0x004E4942      # "BIN\0"


def _read_glb(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    if len(raw) < 12:
        raise ValueError(f"{path.name}: файл короче заголовка GLB")
    magic, version, total = struct.unpack_from("<III", raw, 0)
    if magic != MAGIC:
        raise ValueError(f"{path.name}: это не GLB (сигнатура {magic:#x})")
    if version != 2:
        raise ValueError(f"{path.name}: версия glTF {version}, поддержана 2")

    gltf: dict | None = None
    binary = b""
    off = 12
    while off + 8 <= min(total, len(raw)):
        length, kind = struct.unpack_from("<II", raw, off)
        body = raw[off + 8: off + 8 + length]
        if kind == CHUNK_JSON:
            gltf = json.loads(body.decode("utf-8"))
        elif kind == CHUNK_BIN:
            binary = body
        off += 8 + length
        # Чанки выровнены по 4 байта, но длина в заголовке уже с учётом
        # набивки: отдельного выравнивания при чтении не нужно.
    if gltf is None:
        raise ValueError(f"{path.name}: в GLB нет JSON-чанка")
    return gltf, binary


def _write_glb(path: Path, gltf: dict, binary: bytes) -> None:
    # separators без пробелов: набивка до кратности четырём делается ниже
    # осознанно, а лишние байты в JSON тут ни к чему.
    js = json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # Набивка ОБЯЗАТЕЛЬНА и разная у чанков: JSON добивается пробелами,
    # двоичный — нулями. Загрузчики читают длину из заголовка и спотыкаются
    # на невыровненном смещении следующего чанка.
    js += b" " * (-len(js) % 4)
    bin_pad = binary + b"\0" * (-len(binary) % 4)

    total = 12 + 8 + len(js) + (8 + len(bin_pad) if bin_pad else 0)
    out = bytearray()
    out += struct.pack("<III", MAGIC, 2, total)
    out += struct.pack("<II", len(js), CHUNK_JSON) + js
    if bin_pad:
        out += struct.pack("<II", len(bin_pad), CHUNK_BIN) + bin_pad
    path.write_bytes(bytes(out))


def scale_glb(src: Path, dst: Path, factor: float) -> dict:
    """Записать в dst копию src, увеличенную в factor раз.

    Возвращает, что сделано: вызывающему нужно это напечатать, а не гадать,
    применился масштаб или молча пропущен.
    """
    if factor <= 0:
        raise ValueError(f"масштаб должен быть больше нуля, дано {factor}")

    gltf, binary = _read_glb(src)
    nodes = gltf.setdefault("nodes", [])
    scenes = gltf.setdefault("scenes", [{"nodes": []}])
    scene = scenes[gltf.get("scene", 0)]
    roots = list(scene.get("nodes", []))

    # Обёртка, а не правка scale у самих корней: у узла может стоять matrix,
    # и по спецификации glTF matrix и TRS в одном узле несовместимы -
    # пришлось бы разбирать матрицу на составляющие. Лишний узел дешевле.
    wrapper = {"name": "photo3d_scale", "scale": [factor, factor, factor]}
    if roots:
        wrapper["children"] = roots
    nodes.append(wrapper)
    scene["nodes"] = [len(nodes) - 1]

    dst.parent.mkdir(parents=True, exist_ok=True)
    _write_glb(dst, gltf, binary)
    return {
        "factor": round(factor, 4),
        "roots_wrapped": len(roots),
        "src_mb": round(src.stat().st_size / 1e6, 2),
        "dst_mb": round(dst.stat().st_size / 1e6, 2),
    }
