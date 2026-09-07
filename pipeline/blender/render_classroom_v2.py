"""Re-light, render and export the editable v2 without rebuilding its geometry."""
import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0,str(Path(__file__).parent))
import classroom_v2 as v2

args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
preview='--preview' in args
blend=v2.OUT/'classroom_v2.blend'
bpy.ops.wm.open_mainfile(filepath=str(blend))
v2.refine_board()
v2.refine_fittings()
scene=bpy.context.scene
scene.world.node_tree.nodes['Background'].inputs[1].default_value=.26
for ob in scene.objects:
    if ob.type=='LIGHT':
        if ob.data.type=='SUN':
            ob.data.energy=7.5;ob.data.color=(1,.57,.27)
        elif ob.data.type=='AREA':
            ob.data.energy=42;ob.data.color=(.93,.82,.67)
v2.base.setup_cycles(scene,32 if preview else 96)
scene.render.resolution_percentage=60 if preview else 100
scene.render.resolution_x=1600;scene.render.resolution_y=1000
scene.camera.location=(2.86,.79,1.65)
v2.aim(scene.camera,(-.58,7.5,1.22));scene.camera.data.lens=23.5
scene.camera.data.dof.use_dof=False
scene.render.filepath=str(v2.OUT/'classroom_v2.png')
bpy.ops.file.pack_all()
if not preview:
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
bpy.ops.render.render(write_still=True)
if not preview:
    cam=scene.camera
    cam.location=(-1.55,1.06,1.21);v2.aim(cam,(-2.51,3.1,.92));cam.data.lens=39
    cam.data.dof.use_dof=True;cam.data.dof.focus_distance=2.0;cam.data.dof.aperture_fstop=5.6
    scene.render.filepath=str(v2.OUT/'classroom_v2_detail.png')
    bpy.ops.render.render(write_still=True)
    if '--export' in args:
        result=v2.export_game()
        result.update({'blend':str(blend),'render':str(v2.OUT/'classroom_v2.png'),'detail':str(v2.OUT/'classroom_v2_detail.png')})
        (v2.OUT/'build.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('CLASSROOM_V2_DONE '+json.dumps(result,ensure_ascii=False))
