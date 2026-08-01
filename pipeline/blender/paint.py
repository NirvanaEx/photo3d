"""Покраска модели. Исполняется внутри Blender.

    blender -b --factory-startup -noaudio -P paint.py -- \
        --in model.glb --out model.glb --color 0.8,0.2,0.2 --roughness 0.4

    blender -b --factory-startup -noaudio -P paint.py -- \
        --in model.glb --out model.glb --from-photo input.png

Два способа:

  --color       сплошной PBR-материал: базовый цвет, металличность, шероховатость
  --from-photo  проекция исходного кадра на модель спереди

Проекция считается напрямую из координат вершин, без оператора
project_from_view: тот требует контекста 3D-вида, которого в фоновом режиме
нет. Ось проекции - Y, потому что glTF хранит Y вверх, и его импортёр
разворачивает сцену так, что «лицо» модели смотрит в -Y. Та же ось, вдоль
которой снимает камера турнтейбла, поэтому фото ложится ровно на тот ракурс,
с которого модель и была сделана.

У проекции есть честное ограничение: бока и задняя сторона получают
растянутый по краям цвет. Это неизбежно для одного кадра и уйдёт вместе
с приходом TRELLIS.2, который отдаёт настоящие PBR-карты.
"""
import argparse
import sys

import bpy


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--out", dest="dst", required=True)
    p.add_argument("--color", default="")           # "r,g,b" в 0..1
    p.add_argument("--from-photo", dest="photo", default="")
    p.add_argument("--metallic", type=float, default=0.0)
    p.add_argument("--roughness", type=float, default=0.5)
    return p.parse_args(argv)


def front_projection_uv(obj):
    """UV из координат вершин: X -> U, Z -> V. Ось проекции - Y."""
    mesh = obj.data
    verts = [obj.matrix_world @ v.co for v in mesh.vertices]
    xs = [v.x for v in verts]
    zs = [v.z for v in verts]
    minx, maxx = min(xs), max(xs)
    minz, maxz = min(zs), max(zs)
    w = max(maxx - minx, 1e-6)
    h = max(maxz - minz, 1e-6)

    uv = mesh.uv_layers.new(name="front_projection")
    for loop in mesh.loops:
        v = verts[loop.vertex_index]
        uv.data[loop.index].uv = ((v.x - minx) / w, (v.z - minz) / h)
    mesh.uv_layers.active = uv
    return uv


def make_material(name, base_color, metallic, roughness, image=None, uv_name=None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness

    if image is not None:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.location = (-380, 240)
        if uv_name:
            uvmap = nt.nodes.new("ShaderNodeUVMap")
            uvmap.uv_map = uv_name
            uvmap.location = (-600, 240)
            nt.links.new(uvmap.outputs["UV"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

    # Viewport-цвет отдельно: по нему Workbench рисует модель в режиме color,
    # и без него быстрый предпросмотр остался бы серым.
    mat.diffuse_color = (*base_color, 1.0)
    return mat


def main():
    a = parse_args()
    if not a.color and not a.photo:
        print("PAINT_ERROR: нужен --color или --from-photo")
        sys.exit(1)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.src)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        print("PAINT_ERROR: после импорта нет мешей")
        sys.exit(1)

    base = (0.8, 0.8, 0.8)
    if a.color:
        try:
            parts = [float(x) for x in a.color.split(",")]
            if len(parts) != 3:
                raise ValueError
            base = tuple(min(max(p, 0.0), 1.0) for p in parts)
        except ValueError:
            print(f"PAINT_ERROR: не разобрать цвет {a.color!r}, нужно 'r,g,b' в 0..1")
            sys.exit(1)

    image = None
    if a.photo:
        image = bpy.data.images.load(a.photo)
        image.pack()   # иначе текстура не уедет внутрь GLB

    for obj in meshes:
        bpy.context.view_layer.objects.active = obj
        uv_name = None
        if image is not None:
            uv_name = front_projection_uv(obj).name
        mat = make_material("painted", base, a.metallic, a.roughness, image, uv_name)
        obj.data.materials.clear()
        obj.data.materials.append(mat)

    bpy.ops.export_scene.gltf(filepath=a.dst, export_format="GLB")
    mode = "фото" if a.photo else "цвет " + ",".join(f"{c:.2f}" for c in base)
    print(f"PAINT_OK {mode} metallic={a.metallic} roughness={a.roughness} "
          f"мешей={len(meshes)}")
    print("PAINT_DONE")


if __name__ == "__main__":
    main()
