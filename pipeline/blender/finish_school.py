"""Photogrammetry materials, shared garden trees and placed door leaves.

Run standalone after school_expansion.py, or called by its full rebuild.
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0,str(Path(__file__).parent))
import school_expansion as s
v=s.v
ROOT=s.ROOT
OUT=s.OUT
TREES=[(-9,-.8,5.0),(-10,6.1,5.8),(-10,15.2,5.4),(-6.8,22,5.9),
       (5.7,21.1,5.4),(8.4,16.9,4.6),(10.5,.3,4.4)]


def finish(doors):
    # Move the east tree and its existing trunk collider clear of the hall wall.
    collider=bpy.data.objects.get('SurfaceArchitecture-colonly')
    if collider:
        inverse=collider.matrix_world.inverted()
        for vertex in collider.data.vertices:
            point=collider.matrix_world@vertex.co
            if 9.23<point.x<9.57 and .13<point.y<.47 and -.01<point.z<2.41:
                point.x+=1.1;vertex.co=inverse@point
        collider.data.update()
    for ob in list(bpy.data.objects):
        if ob.name.startswith(('Oak trunk','Oak branch','Oak canopy')) or ob.get('school_tree_instance') or ob.get('door_placed'):
            bpy.data.objects.remove(ob,do_unlink=True)
    v.base.TEX_DIR=ROOT/'data/textures'
    materials={
        'School warm terrazzo':v.base.mat_scanned('Scanned warm terrazzo','terrazzo_tiles',1.2),
        'School living grass':v.base.mat_scanned('Scanned leafy grass','leafy_grass',2.0),
        'School limestone paving':v.base.mat_scanned('Scanned precast paving','precast_stone_paving',2.0),
    }
    for ob in bpy.context.scene.objects:
        if ob.type!='MESH' or 'collision_only' in ob:continue
        for slot in ob.material_slots:
            if slot.material and slot.material.name in materials:
                slot.material=materials[slot.material.name]
                v.base.box_uv(ob,slot.material['tile_m'])
    v.section('13 | Garden trees - shared meshes')
    with bpy.data.libraries.load(str(ROOT/'data/assets/school_tree/school_tree_game.blend'),link=False) as (src,dst):
        dst.objects=[name for name in src.objects if name.startswith('SchoolTree ')]
    prototypes=[ob for ob in dst.objects if ob]
    for index,(x,y,h) in enumerate(TREES):
        rotation=index*2.39996
        for prototype in prototypes:
            ob=prototype.copy();ob.data=prototype.data
            bpy.context.scene.collection.objects.link(ob);v.remember(ob)
            ob.name=f'Garden tree {index+1} '+prototype.name
            ob.matrix_world=Matrix.Translation((x,y,0))@Matrix.Rotation(rotation,4,'Z')@Matrix.Scale(h,4)
            ob['school_tree_instance']=True
    for prototype in prototypes:bpy.data.objects.remove(prototype,do_unlink=True)
    v.section('14 | Doors placed at their hinges')
    templates=[ob for ob in bpy.data.objects if ob.get('door_template')]
    for config in doors:
        x,z,minus_y=config['hinge']
        matrix=Matrix.Translation((x,-minus_y,z))@Matrix.Rotation(math.radians(config['closed_deg']),4,'Z')
        for template in templates:
            ob=template.copy();ob.data=template.data
            bpy.context.scene.collection.objects.link(ob);v.remember(ob)
            ob.name=config['id']+' '+template.name
            ob.matrix_world=matrix@template.matrix_world
            del ob['door_template'];ob['door_placed']=True;ob.hide_render=False
    for ob in templates:ob.hide_render=True;ob.hide_set(True)
    return [{'position':[x,0,-y],'height':h,'rotation':-i*2.39996} for i,(x,y,h) in enumerate(TREES)]


def main():
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'school_v2.blend'))
    layout=json.loads((OUT/'school_layout.json').read_text(encoding='utf-8'))
    layout['trees']=finish(layout['doors'])
    for path in [OUT/'school_layout.json',ROOT/'game/assets/school_layout.json']:
        path.write_text(json.dumps(layout,ensure_ascii=False,indent=2),encoding='utf-8')
    scene=bpy.context.scene;v.base.setup_cycles(scene,64)
    scene.render.resolution_percentage=100
    scene.render.resolution_x=1500;scene.render.resolution_y=940
    cam=scene.camera;cam.location=(-.05,.88,1.64);v.aim(cam,(-.15,7,1.5));cam.data.lens=27;cam.data.dof.use_dof=False
    bpy.ops.file.pack_all();bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'school_v2.blend'))
    for name,pos,target,lens in [('school_classroom',(-.05,.88,1.64),(-.15,7.0,1.50),27),('school_corridor',(4.80,.05,1.64),(5.8,10.5,1.45),24),('school_garden',(4.0,14.8,1.64),(-7.0,17.0,1.9),26)]:
        cam.location=pos;v.aim(cam,target);cam.data.lens=lens;scene.render.filepath=str(OUT/(name+'.png'))
        bpy.ops.render.render(write_still=True)
    templates=[ob for ob in bpy.data.objects if ob.get('door_template')]
    for ob in templates:ob.hide_render=False;ob.hide_set(False)
    report=s.export_scene(templates)
    (OUT/'school_build.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('SCHOOL_FINISH_DONE',report,flush=True)


if __name__=='__main__':main()
