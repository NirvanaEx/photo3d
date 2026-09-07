"""Reduce the CC0 Poly Haven tree once, keeping its leaf/trunk materials."""
from pathlib import Path
import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(ROOT/'data/assets/school_tree/tree_small_02_1k.gltf'))
obj=next(o for o in bpy.context.scene.objects if o.type=='MESH')
bpy.context.view_layer.objects.active=obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT');bpy.ops.mesh.separate(type='MATERIAL');bpy.ops.object.mode_set(mode='OBJECT')
for ob in list(bpy.context.scene.objects):
    if ob.type!='MESH':continue
    material=ob.data.materials[0].name
    bpy.context.view_layer.objects.active=ob
    target=85000 if 'leaves' in material else (22000 if 'branches' in material else 14000)
    have=len(ob.data.polygons)
    if have>target:
        dec=ob.modifiers.new('Game foliage reduction','DECIMATE');dec.ratio=target/have;dec.use_collapse_triangulate=True
        bpy.ops.object.modifier_apply(modifier=dec.name)
    ob.name='SchoolTree '+material
    print('TREE_REDUCED',material,have,len(ob.data.polygons),flush=True)
objects=[o for o in bpy.context.scene.objects if o.type=='MESH']
bpy.context.view_layer.update()
points=[o.matrix_world@Vector(c) for o in objects for c in o.bound_box]
z0=min(p.z for p in points);z1=max(p.z for p in points)
height=z1-z0
for ob in objects:
    mw=ob.matrix_world.copy()
    for vertex in ob.data.vertices:vertex.co=(mw@vertex.co-Vector((0,0,z0)))/height
    ob.matrix_world.identity()
    ob.data.update()
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'data/assets/school_tree/school_tree_game.blend'))
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=str(ROOT/'game/assets/models/school_tree.glb'),export_format='GLB',use_selection=True,export_cameras=False,export_lights=False)
print('SCHOOL_TREE_READY',flush=True)
