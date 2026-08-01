"""Независимая проверка самодельного RGBE-файла: читает его Blender.

Кодировщик в make_studio_hdr.py написан вручную, и проверять его собственным
декодером бессмысленно — ошибка сошлась бы сама с собой. Blender использует
чужую реализацию, поэтому его вердикт что-то значит.

    blender -b --factory-startup -noaudio -P check_hdr.py
"""
import bpy

PATH = "/mnt/d/Develop/photo3d/web/static/studio.hdr"

img = bpy.data.images.load(PATH)
w, h = img.size
print(f"РАЗМЕР: {w}x{h}, каналов {img.channels}, float={img.is_float}")

px = list(img.pixels)
rgb = [px[i:i + 3] for i in range(0, len(px), img.channels)]
flat = [c for p in rgb for c in p]
mx = max(flat)
mn = min(flat)
avg = sum(flat) / len(flat)
bright = sum(1 for c in flat if c > 1.0)

print(f"ЯРКОСТЬ: мин {mn:.4f}, макс {mx:.2f}, среднее {avg:.3f}")
print(f"пикселей ярче единицы: {bright} ({100*bright/len(flat):.1f}%)")

ok = w == 1024 and h == 512 and mx > 10 and mn >= 0
print("ВЕРДИКТ:", "файл корректен, диапазон HDR настоящий" if ok else "ЧТО-ТО НЕ ТАК")
