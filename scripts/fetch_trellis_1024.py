"""Докачать веса 1024 и переключить конвейер на каскадный режим.

Изначально они были пропущены осознанно: официально TRELLIS.2 требует 24 ГБ
видеопамяти, у нас 12, и 5.2 ГБ казались выброшенными.

Замер это опроверг. На 512 пик составил 2.62 ГБ из 12 - потому что стадии
идут последовательно и режим low_vram возвращает каждый блок на CPU сразу
после использования. Запас девятикратный, и каскад 1024 имеет все шансы
пройти.

Скрипт только качает и пересобирает конфиг. Влезет ли режим на самом деле -
покажет замер, а не эти рассуждения.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

WEIGHTS = Path("/opt/photo3d/weights")
MAIN = WEIGHTS / "TRELLIS.2-4B"
REPO = "microsoft/TRELLIS.2-4B"

os.environ["HF_HOME"] = str(WEIGHTS / "hf")

sys.path.insert(0, str(Path(__file__).parent))


def main() -> int:
    from huggingface_hub import snapshot_download

    before = sum(f.stat().st_size for f in MAIN.rglob("*") if f.is_file())
    print(f"было на диске: {before / 1e9:.2f} ГБ")
    print("качаю два файла по 2.58 ГБ...")

    snapshot_download(repo_id=REPO, local_dir=str(MAIN),
                      allow_patterns=["*_1024_*"], max_workers=4)

    after = sum(f.stat().st_size for f in MAIN.rglob("*") if f.is_file())
    print(f"стало: {after / 1e9:.2f} ГБ (+{(after - before) / 1e9:.2f})")

    from sync_config import build

    return build("1024_cascade")


if __name__ == "__main__":
    raise SystemExit(main())
