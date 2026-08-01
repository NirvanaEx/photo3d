"""Перенос внешнего вида с исходной модели на перестроенную.

    blender -b --factory-startup -noaudio -P bake.py -- \
        --source painted.glb --target sculpt.glb --out result.glb --resolution 2048

Зачем. Воксельная перестройка даёт совершенно новую сетку: старая UV-развёртка
к ней не относится, поэтому покраска и текстура теряются. Без этого шага
ретопология каждый раз уничтожала бы результат генерации.

Два пути, и выбор между ними принципиален:

  материал БЕЗ картинки (сплошной цвет, металличность, шероховатость)
      -> просто переносим материал. Развёртка не нужна, потерь нет,
         занимает миллисекунды. Запекать однородный цвет в текстуру
         было бы расточительно и хуже по качеству

  материал С картинкой (настоящие PBR-карты от генератора)
      -> строим UV на новой сетке (Smart UV Project) и запекаем
         Cycles'ом «выделенное на активное»

Результат проверяется по содержимому запечённой картинки: оператор bake
возвращает FINISHED и когда запёк пустоту, поэтому смотрим на разброс
пикселей, а не на код возврата.
"""
import argparse
import json
import statistics
import sys

import bpy


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--resolution", type=int, default=2048)
    return p.parse_args(argv)


def import_glb(path):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    return [o for o in bpy.context.scene.objects if o not in before and o.type == "MESH"]


def image_textures(mat):
    if not mat or not mat.use_nodes:
        return []
    return [n for n in mat.node_tree.nodes
            if n.type == "TEX_IMAGE" and n.image is not None]


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def setup_cycles_gpu():
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 8          # для цвета много сэмплов не нужно
    scene.cycles.use_denoising = False
    device = "CPU"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = backend
            except TypeError:
                continue
            try:
                prefs.get_devices()
            except AttributeError:
                pass
            gpus = [d for d in prefs.devices if d.type == backend]
            if gpus:
                for d in prefs.devices:
                    d.use = (d.type == backend)
                scene.cycles.device = "GPU"
                device = f"{backend}/{gpus[0].name}"
                break
    except Exception as exc:  # noqa: BLE001
        print("BAKE_GPU_FAIL", exc)
    return device


def main():
    a = parse_args()
    stats = {}

    bpy.ops.wm.read_factory_settings(use_empty=True)
    targets = import_glb(a.target)
    sources = import_glb(a.source)
    if not targets or not sources:
        print("BAKE_ERROR: не удалось импортировать обе модели")
        sys.exit(1)
    target, source = targets[0], sources[0]

    src_mat = source.data.materials[0] if source.data.materials else None
    textures = image_textures(src_mat)
    stats["source_material"] = src_mat.name if src_mat else None
    stats["source_textures"] = len(textures)

    if src_mat is None:
        stats["mode"] = "none"
        stats["note"] = "у исходной модели нет материала, переносить нечего"

    elif not textures:
        # Быстрый путь: материал однородный, развёртка не нужна вовсе.
        stats["mode"] = "material-copy"
        target.data.materials.clear()
        target.data.materials.append(src_mat)
        stats["note"] = "материал перенесён без запекания: картинок в нём нет"

    else:
        stats["mode"] = "bake"
        # 1. развёртка новой сетки
        activate(target)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")
        stats["uv_layers"] = len(target.data.uv_layers)

        # 2. пустая картинка и материал-приёмник
        img = bpy.data.images.new("baked", a.resolution, a.resolution, alpha=False)
        mat = bpy.data.materials.new("baked")
        mat.use_nodes = True
        nt = mat.node_tree
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.nodes.active = tex          # именно активный узел получает запечённое
        nt.links.new(tex.outputs["Color"],
                     nt.nodes["Principled BSDF"].inputs["Base Color"])
        target.data.materials.clear()
        target.data.materials.append(mat)

        # 3. запекание «выделенное на активное»
        stats["device"] = setup_cycles_gpu()
        extrusion = max(max(target.dimensions), 1e-3) * 0.05
        bpy.ops.object.select_all(action="DESELECT")
        source.select_set(True)
        target.select_set(True)
        bpy.context.view_layer.objects.active = target
        bpy.ops.object.bake(
            type="DIFFUSE", pass_filter={"COLOR"},
            use_selected_to_active=True, cage_extrusion=extrusion,
            margin=16, use_clear=True,
        )

        # 4. проверка: оператор возвращает FINISHED и запекая пустоту
        px = list(img.pixels)
        sample = px[0:len(px):max(len(px) // 30000, 1)]
        spread = statistics.pstdev(sample) if len(sample) > 1 else 0.0
        stats["pixel_mean"] = round(sum(sample) / len(sample), 4)
        stats["pixel_spread"] = round(spread, 5)
        stats["looks_baked"] = spread > 1e-4 or stats["pixel_mean"] > 1e-3
        if not stats["looks_baked"]:
            stats["note"] = ("запечённая картинка однородно пустая - вероятно, "
                             "исходная поверхность не попала в клетку")
        img.pack()

    # исходник в выгрузку не идёт
    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    bpy.ops.object.delete()

    bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB")
    print("BAKE_STATS " + json.dumps(stats, ensure_ascii=False))
    print("BAKE_DONE")


if __name__ == "__main__":
    main()
