"""Проверка, что собранные CUDA-расширения действительно импортируются.

    python verify_ext.py            # при сборке образа, видеокарты нет
    python verify_ext.py --strict   # при запуске с --gpus all

Имена модулей НЕ задаются списком вручную. Первая версия так и делала - и
упала на том, что колесо зовётся flex_gemm, а написано было flexgemm, а
следом на nvdiffrec, который ставится как nvdiffrec_render. Здесь имена
берутся из метаданных самих пакетов, поэтому угадывать нечего.

Про два режима. Во время `docker build` видеокарты в контейнере нет: флаг
--gpus существует только у `docker run`. Расширения, поднимающие контекст
CUDA прямо при импорте, там обязаны падать с «0 active drivers» - это не
поломка сборки, а отсутствие железа. Поэтому при сборке такая ошибка
считается отложенной проверкой, а строгий режим применяется уже в рантайме,
где драйвер на месте. Всё остальное - несовпадение ABI, недостающие символы,
кривая линковка - ловится и без видеокарты, ради чего проверка и нужна.
"""
from __future__ import annotations

import importlib
import importlib.metadata as md
import sys
import traceback


def norm(name: str) -> str:
    return name.lower().replace("-", "").replace("_", "").replace(".", "")


# Что именно мы собирали. Сверка по нормализованному имени: pip, setup.py и
# оператор import пишут его каждый на свой лад.
BUILT = {norm(x) for x in ("nvdiffrast", "nvdiffrec_render", "cumesh",
                           "flex_gemm", "o_voxel", "flash_attn")}

# По этим признакам видно, что упало из-за отсутствия видеокарты, а не из-за
# плохой сборки.
NO_DRIVER = (
    "0 active drivers",
    "no cuda-capable device",
    "found no nvidia driver",
    "cuda driver version is insufficient",
    "libcuda.so",
    "cuda_error_no_device",
)


def is_driver_absence(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(m in text for m in NO_DRIVER)


def top_levels(dist: md.Distribution) -> list[str]:
    """Модули верхнего уровня пакета: сначала метаданные, и только если их
    нет - выводим из состава файлов."""
    txt = dist.read_text("top_level.txt")
    if txt:
        return [ln.strip() for ln in txt.splitlines() if ln.strip()]
    files = dist.files or []
    roots = {f.parts[0] for f in files
             if len(f.parts) > 1 and not f.parts[0].endswith((".dist-info", ".data"))}
    return sorted(roots) or [(dist.metadata["Name"] or "?").replace("-", "_")]


def try_import(label: str, mod: str, strict: bool) -> bool:
    try:
        importlib.import_module(mod)
        print(f"  ok        {label:18} -> {mod}")
        return True
    except Exception as exc:  # noqa: BLE001
        if not strict and is_driver_absence(exc):
            print(f"  отложено  {label:18} -> {mod}  (нет GPU при сборке)")
            return True
        print(f"  СБОЙ      {label:18} -> {mod}")
        traceback.print_exc(limit=3)
        return False


def main() -> int:
    strict = "--strict" in sys.argv
    print(f"режим: {'строгий, с видеокартой' if strict else 'сборка, без видеокарты'}")

    found: dict[str, list[str]] = {}
    for dist in md.distributions():
        name = dist.metadata["Name"]
        if name and norm(name) in BUILT:
            found[name] = top_levels(dist)

    ok = True
    for name, mods in sorted(found.items()):
        for mod in mods:
            ok &= try_import(name, mod, strict)

    # nvdiffrast интересен именно подмодулем torch - там лежит расширение,
    # а сам пакет импортируется и без него
    ok &= try_import("nvdiffrast", "nvdiffrast.torch", strict)

    missing = BUILT - {norm(n) for n in found}
    if missing:
        print(f"  НЕ УСТАНОВЛЕНЫ: {sorted(missing)}")
        ok = False

    import torch

    print(f"\n  torch {torch.__version__}, CUDA {torch.version.cuda}, "
          f"ABI CXX11={torch._C._GLIBCXX_USE_CXX11_ABI}")
    if strict:
        print(f"  видеокарта: {torch.cuda.is_available()} "
              f"{torch.cuda.get_device_name(0) if torch.cuda.is_available() else ''}")
        if not torch.cuda.is_available():
            print("  СБОЙ: строгий режим, а видеокарта недоступна")
            ok = False

    print("ВСЕ РАСШИРЕНИЯ НА МЕСТЕ" if ok else "ЕСТЬ ПРОБЛЕМЫ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
