"""Expand the saved classroom into one walkable school: classroom, hall, garden.

Blender 4.5.9: blender -b -P pipeline/blender/school_expansion.py -- --preview
The pre-expansion source is preserved so the build is deterministic.
"""
import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0,str(Path(__file__).parent))
import classroom_v2 as v

ROOT=v.ROOT
OUT=ROOT/'data/output/loc_classroom_v2'
COLLIDERS=defaultdict(list)
DOORS=[]
M={}


def box(name,pos,size,material,bevel=.004,solid=False,surface='Architecture'):
    ob=v.box(name,pos,size,material,bevel)
    if material and 'tile_m' in material:v.base.box_uv(ob,material['tile_m'])
    if solid:ob['school_collision']=surface
    return ob


def bounds(ob):
    pts=[ob.matrix_world@Vector(p) for p in ob.bound_box]
    return Vector([min(p[i] for p in pts) for i in range(3)]),Vector([max(p[i] for p in pts) for i in range(3)])


def cut(ob,name,center,size):
    cutter=v.box(name,center,size,None,0)
    mod=ob.modifiers.new(name,'BOOLEAN');mod.operation='DIFFERENCE';mod.solver='EXACT';mod.object=cutter
    bpy.context.view_layer.objects.active=ob
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter,do_unlink=True)


def image_material(name,palette,roughness=0.8,style='stone'):
    """Small tiling material images survive glTF without shader-only textures."""
    rng=np.random.default_rng(24 if style=='stone' else 36)
    n=512;x,y=np.meshgrid(np.arange(n),np.arange(n));grain=rng.normal(0,.018,(n,n))
    grain+=.014*np.sin(x/25)*np.cos(y/31)
    if style=='stone':
        for _ in range(650):
            cx,cy=rng.integers(0,n,2);r=rng.integers(1,5)
            mask=(x-cx)**2+(y-cy)**2<r*r
            grain[mask]+=rng.uniform(-.14,.11)
        grain[(x<2)|(y<2)]=-.055
    elif style=='grass':
        grain+=.035*np.sin(x*.3+y*.7)+.025*np.cos(x*.12-y*.6)
    pixels=np.ones((n,n,4),dtype=np.float32)
    for i,c in enumerate(palette):pixels[:,:,i]=np.clip(c+grain,0,1)
    im=bpy.data.images.new(name+' albedo',width=n,height=n);im.pixels.foreach_set(pixels.ravel());im.pack()
    mat=v.mat(name,palette,roughness)
    mat['tile_m']=.6 if style=='stone' else 1.4
    node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.image=im
    mat.node_tree.links.new(node.outputs['Color'],mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
    return mat


def prepare():
    bpy.ops.wm.open_mainfile(filepath=str(ROOT/'data/output/loc_classroom_v2_before_expansion/classroom_v2.blend'))
    # Remove the old second-floor backdrop and the non-working door decorations.
    for c in list(bpy.data.collections):
        if c.name.startswith('06 |'):
            for ob in list(c.objects):bpy.data.objects.remove(ob,do_unlink=True)
            bpy.data.collections.remove(c)
    prefixes=('Door wood panel','Door jamb','Door lintel','Door frosted inset','Door handle',
              'Sage lower right wall','Right dado rail','Desk rubber foot','skirt_sk_r')
    for ob in list(bpy.data.objects):
        if ob.name.startswith(prefixes):bpy.data.objects.remove(ob,do_unlink=True)
    v.materials()
    M.update(v.M)
    v.base.TEX_DIR=ROOT/'data/textures'
    M['wood']=v.base.mat_scanned('School bench oak','brown_planks_09',1.0,tint=(.94,.91,.85),rough_range=(.28,.5))
    M['wall']=bpy.data.materials['wall_plaster']
    M['trim']=bpy.data.materials['trim_wood']
    M['glass']=bpy.data.materials['glass']
    M['floor']=image_material('School warm terrazzo',(.53,.52,.47),.6)
    M['grass']=image_material('School living grass',(.245,.31,.135),.95,'grass')
    M['paving']=image_material('School limestone paving',(.49,.45,.37),.83)
    M['bark']=v.mat('School oak bark',(.115,.067,.027),.96)
    M['leaf']=v.mat('School oak foliage',(.115,.22,.037),.72)
    M['leaf_gold']=v.mat('School early autumn foliage',(.28,.31,.055),.7)
    M['brick']=v.mat('School garden brick',(.32,.16,.087),.88)
    M['metal']=v.mat('School painted iron',(.048,.08,.073),.45,.55)
    M['light']=v.mat('School warm lamp diffuser',(.80,.75,.60),.5)
    bsdf=M['light'].node_tree.nodes['Principled BSDF'];bsdf.inputs['Emission Color'].default_value=(1,.74,.43,1);bsdf.inputs['Emission Strength'].default_value=.6


def furniture_scale():
    """70x50 cm desks at 75 cm; chair seats at 45 cm. Keep room in metres."""
    desktops=[o for o in bpy.data.objects if o.name.startswith('desk_top')]
    chairs=[o for o in bpy.data.objects if o.name.startswith('chair_seat')]
    centers={}
    for group,anchors in (('desk_',desktops),('chair_',chairs)):
        positions=[]
        for anchor in anchors:
            pts=[anchor.matrix_world@p.co for p in anchor.data.vertices]
            c=sum(pts,Vector())/len(pts);axis=(pts[1]-pts[0]).normalized()
            positions.append((c,axis))
        for ob in list(bpy.data.objects):
            if not ob.name.startswith(group) or ob.type!='MESH':continue
            lo,hi=bounds(ob);center=(lo+hi)/2
            c,axis=min(positions,key=lambda p:(Vector((p[0].x,p[0].y))-Vector((center.x,center.y))).length)
            side=Vector((-axis.y,axis.x,0));sx,sy,sz=(.70/.65,.50/.45,.75/.73) if group=='desk_' else (1.05,1.07,.45/.42)
            for vert in ob.data.vertices:
                world=ob.matrix_world@vert.co;off=world-Vector((c.x,c.y,0))
                new=Vector((c.x,c.y,0))+axis*off.dot(axis)*sx+side*off.dot(side)*sy+Vector((0,0,world.z*sz))
                vert.co=ob.matrix_world.inverted()@new
            if ob.name.startswith(('desk_leg','chair_leg')):
                for vertex in ob.data.vertices:vertex.co+=vertex.normal*.002
            ob.data.update()
        centers[group]=positions
    # Raise belongings on desktops by the same 2 cm; backpacks remain on the floor.
    c=bpy.data.collections.get('03 | Personal belongings')
    if c:
        for ob in c.objects:
            lo,hi=bounds(ob)
            if hi.y<6.1 and lo.z>.72:ob.location.z+=.02
    v.section('08 | Correct furniture contact and physics')
    for c,axis in centers['desk_']:
        side=Vector((-axis.y,axis.x,0))
        for sx in (-1,1):
            for sy in (-1,1):
                p=Vector((c.x,c.y,.019))+axis*sx*.307+side*sy*.228
                v.cylinder('Fitted rubber desk foot',p,.019,.037,M['rubber'])
        col=box('Desk collision',(c.x,c.y,.385),(.70,.50,.73),None,0)
        col.rotation_euler.z=math.atan2(axis.y,axis.x)
        # box geometry is in world coordinates; rotate mesh around its own centre.
        col.rotation_euler.z=0;v.base._spin_group([col],c.x,c.y,math.degrees(math.atan2(axis.y,axis.x)))
        col['collision_only']='Architecture'
    for c,axis in centers['chair_']:
        ob=box('Chair collision',(c.x,c.y,.40),(.40,.39,.79),None,0)
        ob['collision_only']='Architecture'
    for name in ('wall_front','wall_back','wall_left','ceiling','glass0','glass1','glass2','glass3','lectern_body','cabinet','shelf'):
        ob=bpy.data.objects.get(name)
        if ob:ob['school_collision']='Architecture'
    bpy.data.objects['floor']['school_collision']='Wood'


def door_frame_x(y,number):
    for yy in (y-.60,y+.60):
        box('Classroom oak door jamb',(3.84,yy,1.15),(.40,.06,2.30),M['trim'])
    box('Classroom oak lintel',(3.84,y,2.29),(.40,1.26,.065),M['trim'])
    for x in (3.61,4.065):
        v.text('Room number',number,(x,y-.19,2.42),.085,M['paper'],rotation=(math.pi/2,0,-math.pi/2 if x<4 else math.pi/2))
    DOORS.append({'id':'ClassDoor'+number,'hinge':[3.83,0,-(y-.54)],'closed_deg':0,'open_deg':-97,'label':'Дверь класса','exterior':False})


def build_hall():
    v.section('09 | Corridor architecture')
    wall=bpy.data.objects['wall_right']
    for yy in (1.25,7.65):cut(wall,'Real classroom door opening',(3.86,yy,1.12),(1.0,1.20,2.25))
    wall['school_collision']='Architecture'
    for a,b in ((0,.65),(1.85,7.05),(8.25,9.0)):
        for x in (3.688,4.012):
            box('Dado beside actual doorway',(x,(a+b)/2,.565),(.014,b-a,1.10),M['paint'])
            box('Oak rail beside doorway',(x,(a+b)/2,1.135),(.03,b-a,.045),M['trim'])
            box('Oak skirting beside doorway',(x,(a+b)/2,.06),(.035,b-a,.12),M['trim'])
    door_frame_x(1.25,'101');door_frame_x(7.65,'101B')
    floor=box('Corridor terrazzo floor',(5.62,5.0,-.10),(3.30,11.50,.20),M['floor'],0,True,'Tile');v.base.box_uv(floor,.6)
    box('Corridor ceiling',(5.62,5.0,3.17),(3.55,11.50,.20),M['wall'],0,True)
    box('Corridor south wall',(5.63,-.69,1.55),(3.55,.24,3.1),M['wall'],0,True)
    exterior=box('Corridor east window wall',(7.30,5.0,1.55),(.24,11.5,3.1),M['wall'],0)
    for i,(a,b) in enumerate(((.2,1.9),(2.8,4.6),(5.6,7.4),(8.3,10.0))):
        cut(exterior,'Corridor window aperture',(7.3,(a+b)/2,1.83),(.6,b-a,1.65))
        glass=box('Hall glass',(7.29,(a+b)/2,1.83),(.012,b-a,1.65),M['glass'],0,True)
        glass.visible_shadow=False
        for zz in (1.02,2.65):box('Hall window sill',(7.24,(a+b)/2,zz),(.31,b-a+.1,.045),M['paper'])
        for yy in (a,(a+b)/2,b):box('Hall window mullion',(7.24,yy,1.83),(.18,.043,1.66),M['paper'])
    exterior['school_collision']='Architecture'
    box('Hall sage lower east wall',(7.169,5,.52),(.022,11.45,1.0),M['paint'])
    # Exit at the end of the corridor, on the same ground level as the garden.
    end=box('Hall garden end wall',(5.62,10.70,1.55),(3.55,.24,3.1),M['wall'],0)
    cut(end,'Garden door opening',(5.65,10.70,1.13),(1.24,.6,2.26));end['school_collision']='Architecture'
    for xx in (5.01,6.29):box('Garden exit jamb',(xx,10.68,1.15),(.06,.31,2.30),M['trim'])
    box('Garden exit lintel',(5.65,10.68,2.29),(1.34,.31,.06),M['trim'])
    DOORS.append({'id':'GardenDoor','hinge':[5.11,0,-10.69],'closed_deg':-90,'open_deg':7,'label':'Дверь во двор','exterior':True})
    for yy in (1.1,4.9,8.6):
        box('Hall ceiling fixture',(5.6,yy,3.045),(.78,.20,.07),M['paper'])
        box('Hall opal diffuser',(5.6,yy,3.003),(.70,.16,.018),M['light'])
        data=bpy.data.lights.new('Hall warm area','AREA');data.energy=48;data.color=(1,.85,.66);data.shape='RECTANGLE';data.size=.7;data.size_y=.18
        ob=bpy.data.objects.new('Hall warm area',data);bpy.context.scene.collection.objects.link(ob);ob.location=(5.6,yy,2.97)
    v.text('Garden exit sign','ЗАДНИЙ ДВОР',(5.19,10.557,2.51),.12,M['paint'])
    for yy in (3.1,6.6):bench(6.87,yy,side=True)
    v.plant(6.72,9.88,0,1.05)
    # Large pinboard at human eye level between the two classroom doors.
    box('Hall noticeboard',(4.025,4.70,1.72),(.06,1.9,1.1),M['trim'])
    for k in range(6):
        yy=4.08+(k%3)*.52;zz=1.53+(k//3)*.42
        box('Hall pinned announcement',(4.06,yy,zz),(.005,.34,.28),M['paper'],0)
        for ln in range(6):v.rod('Hall notice ink',[(4.064,yy-.14,zz+.08-ln*.025),(4.064,yy+.10,zz+.08-ln*.025)],.001,M['ink'])


def bench(x,y,side=False):
    before=set(bpy.data.objects)
    for k in range(5):box('Bench oak seat slat',(x,y-.19+k*.09,.455),(1.55,.073,.035),M['wood'],.008)
    for k in range(3):box('Bench oak back slat',(x,y+.23,.69+k*.085),(1.55,.035,.072),M['wood'],.006)
    for sx in (-.61,.61):
        v.rod('Bench iron frame',[(x+sx,y-.15,.04),(x+sx,y-.15,.435),(x+sx,y+.19,.435),(x+sx,y+.19,.91)],.024,M['metal'])
    col=box('Bench collision',(x,y,.41),(1.56,.48,.82),None,0);col['collision_only']='Architecture'
    if side:
        for ob in set(bpy.data.objects)-before:
            if ob.type=='MESH':v.base._spin_group([ob],x,y,90)


def tree(x,y,height=5.0,radius=1.9):
    """Branches plus folded leaves, batched directly into one canopy mesh."""
    v.rod('Oak trunk',[(x,y,0),(x+.14,y,.6*height),(x+.24,y+.1,height*.93)],.13,M['bark'])
    box('Tree trunk collision',(x,y,1.2),(.31,.31,2.4),None,0)['collision_only']='Architecture'
    verts=[];faces=[]
    for branch in range(10):
        a=branch*2.4;z=height*.53+branch*.13
        tip=Vector((x+math.cos(a)*radius*.7,y+math.sin(a)*radius*.7,z+.7))
        v.rod('Oak branch',[(x+.14,y,z),tip],.035,M['bark'])
        for k in range(100):
            angle=v.R.random()*math.tau;rr=radius*.63*math.sqrt(v.R.random())
            center=tip+Vector((math.cos(angle)*rr,math.sin(angle)*rr,v.R.uniform(-.6,.72)))
            along=Vector((v.R.uniform(-.25,.25),v.R.uniform(-.25,.25),v.R.uniform(-.11,.11)))
            side=along.cross(Vector((0,0,1))).normalized()*v.R.uniform(.065,.125)
            start=len(verts)
            for t in (0,.33,.66,1):
                mid=center+along*t+Vector((0,0,math.sin(t*math.pi)*.035))
                width=math.sin(t*math.pi)
                verts.extend([mid-side*width,mid+Vector((0,0,.009)),mid+side*width])
            for j in range(3):
                for q in range(2):
                    i=start+j*3+q;faces.append((i,i+1,i+4,i+3))
    me=bpy.data.meshes.new('Oak leaf clusters');me.from_pydata(verts,[],faces);me.materials.append(M['leaf']);me.materials.append(M['leaf_gold'])
    for poly in me.polygons:poly.material_index=1 if v.R.random()<.18 else 0;poly.use_smooth=True
    ob=bpy.data.objects.new('Oak canopy',me);bpy.context.scene.collection.objects.link(ob);v.remember(ob)


def build_garden():
    v.section('10 | Garden and the view from the classroom')
    box('School garden soil and grass',(-3.5,10.7,-.14),(31,31.8,.20),M['grass'],0,True,'Grass')
    for pos,size in [((-5,4.9,-.06),(2.5,12.0,.12)),((.7,12.6,-.06),(13.9,3.6,.12)),((-.8,19.2,-.06),(2.8,10.0,.12)),((8.66,5,-.06),(2.9,11.5,.12))]:
        box('Garden paving path',pos,size,M['paving'],.006,True,'Gravel')
    # A recessed strip connects the corridor threshold directly to the paving.
    box('Exit threshold paving',(5.65,11.0,-.055),(2.0,.85,.13),M['paving'],.004,True,'Gravel')
    for pos,size in [((-18.9,10.5,.85),(.20,31.6,1.7)),((11.7,10.5,.85),(.20,31.6,1.7)),((-3.6,-5.25,.85),(30.6,.20,1.7)),((-3.6,26.25,.85),(30.6,.20,1.7))]:
        box('School garden boundary wall',pos,size,M['brick'],.01,True)
        top=Vector(pos);top.z=1.735;cap=list(size);cap[2]=.08
        box('Garden wall stone cap',top,cap,M['paving'],.02)
    # A two-storey wing is distant enough to let the sunset reach the windows.
    box('Opposite school wing',(-16.5,8.5,3.2),(3.3,24,6.4),M['stucco'],.025,True)
    for level in (1.50,4.50):
        for yy in (-2,1.5,5,8.5,12,15.5,19):
            box('Opposite wing window',(-14.823,yy,level),(.025,2.0,1.8),M['window'],.006)
            for dy in (-1.035,0,1.035):box('Opposite wing window frame',(-14.78,yy+dy,level),(.08,.05,1.90),M['paper'])
            for zz in (level-.945,level+.945):box('Opposite wing sill',(-14.74,yy,zz),(.22,2.12,.06),M['paper'])
    for zz in (.33,3.0,6.37):box('School wing band',(-14.76,8.5,zz),(.14,24,.10),M['paper'])
    for x,y,h,r in [(-9,-.8,5.0,1.85),(-10.0,6.1,5.8,2.25),(-10,15.2,5.4,2.15),(-6.8,22,5.9,2.5),(5.7,21.1,5.4,2.4),(8.4,16.9,4.6,1.7),(10.5,.3,4.4,1.5)]:tree(x,y,h,r)
    for x,y,side in [(-4.0,16.4,False),(3.6,16.4,False),(-8.3,10.4,True)]:bench(x,y,side)
    # Planting beds, kerbs, bins and a drinking fountain give useful scale cues.
    for x,y,w,d in [(-8.8,3.0,3.8,3.5),(3.8,19.3,2.8,1.0),(-4.4,20,1.1,3.8)]:
        box('Garden planting bed',(x,y,.10),(w,d,.22),M['soil'],.02)
        for sx in (-1,1):box('Raised bed kerb',(x+sx*(w/2+.04),y,.16),(.09,d+.18,.32),M['paving'],.008,True)
        for sy in (-1,1):box('Raised bed kerb',(x,y+sy*(d/2+.04),.16),(w+.18,.09,.32),M['paving'],.008,True)
        for k in range(22):
            xx=x+v.R.uniform(-w*.43,w*.43);yy=y+v.R.uniform(-d*.43,d*.43)
            for j in range(4):
                a=j*2.3;v.leaf('Garden grasses',(xx,yy,.20),(xx+math.cos(a)*.21,yy+math.sin(a)*.21,v.R.uniform(.3,.6)),.038,M['leaf'])
    for x,y in ((6.8,12.6),(-3.0,16.4)):
        v.cylinder('Garden litter bin',(x,y,.36),.20,.72,M['metal'])
        v.cylinder('Bin rim',(x,y,.74),.21,.055,M['metal'])
        box('Bin collision',(x,y,.38),(.43,.43,.77),None,0)['collision_only']='Architecture'
    for yy in (2.0,8.5):
        v.rod('School rain pipe',[(7.47,yy,3.2),(7.47,yy,.25),(7.65,yy,.09)],.055,M['metal'])
    for zz in (.20,3.20):box('Classroom exterior facade band',(0,9.33,zz),(7.95,.13,.16),M['paper'],.004)


def make_door():
    """Reusable leaf, modelled at a hinge origin; pivot is not the door centre."""
    v.section('11 | Working door leaf template')
    before=set(bpy.data.objects)
    box('Door lower oak panel',(0,.54,.47),(.065,1.08,.94),M['wood'],.006)
    for yy in (.045,1.035):box('Door vertical stile',(0,yy,1.56),(.065,.09,1.23),M['wood'],.006)
    for zz in (1.0,2.16):box('Door horizontal rail',(0,.54,zz),(.065,1.0,.09),M['wood'],.006)
    glass=box('Door glazing',(0,.54,1.57),(.012,.9,1.02),M['glass'],0);glass.visible_shadow=False
    # Plaque and handles on both sides; proportions match an adult hand.
    for xx in (-.052,.052):
        box('Door lock escutcheon',(xx,.94,.96),(.018,.045,.18),M['brass'],.004)
        v.rod('Door lever',[(xx,.94,.985),(xx*1.65,.94,.985),(xx*1.65,.79,.985)],.009,M['brass'])
    for zz in (.25,1.82):v.cylinder('Door hinge',(0,.012,zz),.013,.10,M['brass'])
    objects=list(set(bpy.data.objects)-before)
    for ob in objects:ob['door_template']=True
    return objects


def make_collisions():
    v.section('12 | Collision surfaces - not rendered')
    bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get()
    for ob in list(bpy.context.scene.objects):
        if 'school_collision' in ob:
            dup=ob.copy();dup.data=bpy.data.meshes.new_from_object(ob.evaluated_get(dg),depsgraph=dg)
            dup.modifiers.clear();bpy.context.scene.collection.objects.link(dup)
            dup['collision_only']=ob['school_collision'];COLLIDERS[dup['collision_only']].append(dup)
        elif 'collision_only' in ob:COLLIDERS[ob['collision_only']].append(ob)
    for key,objs in COLLIDERS.items():
        bpy.ops.object.select_all(action='DESELECT')
        for o in objs:o.select_set(True)
        bpy.context.view_layer.objects.active=objs[0]
        if len(objs)>1:bpy.ops.object.join()
        o=bpy.context.object;o.name='Surface'+key+'-colonly';o.data.materials.clear()
        o.hide_render=True;o.display_type='WIRE';o['collision_only']=key


def export(objects,path):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objects:o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',use_selection=True,
        export_animations=False,export_cameras=False,export_lights=False,export_image_format='AUTO')


def export_scene(door_objects):
    # Disposable in-memory meshes; source was saved with editable type/modifiers.
    for o in list(bpy.context.scene.objects):
        if o.get('school_tree_instance') or o.get('door_placed'):
            bpy.data.objects.remove(o,do_unlink=True)
    for o in list(bpy.context.scene.objects):
        if o.type=='FONT':
            bpy.context.view_layer.objects.active=o;bpy.ops.object.select_all(action='DESELECT');o.select_set(True);bpy.ops.object.convert(target='MESH')
    dg=bpy.context.evaluated_depsgraph_get()
    for o in list(bpy.context.scene.objects):
        if o.type=='MESH' and o.modifiers:
            mesh=bpy.data.meshes.new_from_object(o.evaluated_get(dg),depsgraph=dg);o.modifiers.clear();o.data=mesh
    export(door_objects,ROOT/'game/assets/models/school_door.glb')
    for o in door_objects:bpy.data.objects.remove(o,do_unlink=True)
    groups=defaultdict(list);colliders=[]
    for o in bpy.context.scene.objects:
        if o.type!='MESH':continue
        if 'collision_only' in o:
            o.hide_render=False;colliders.append(o);continue
        groups[tuple(s.material.name for s in o.material_slots if s.material)].append(o)
    merged=[]
    for key,objs in groups.items():
        bpy.ops.object.select_all(action='DESELECT')
        for o in objs:o.select_set(True)
        bpy.context.view_layer.objects.active=objs[0]
        if len(objs)>1:bpy.ops.object.join()
        o=bpy.context.object;o.name=('School '+' '.join(key))[:110];merged.append(o)
    export(merged+colliders,ROOT/'game/assets/models/school_v2.glb')
    return {'render_meshes':len(merged),'collision_surfaces':len(colliders)}


def main():
    p=argparse.ArgumentParser();p.add_argument('--preview',action='store_true');p.add_argument('--no-render',action='store_true')
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    prepare();print('SCHOOL_STAGE proportions',flush=True);furniture_scale();build_hall()
    print('SCHOOL_STAGE garden',flush=True);build_garden();door_objects=make_door();make_collisions()
    scene=bpy.context.scene;v.base.setup_cycles(scene,32 if args.preview else 80)
    scene.render.resolution_percentage=65 if args.preview else 100
    scene.render.resolution_x=1500;scene.render.resolution_y=940
    cam=scene.camera;cam.location=(-.05,.88,1.64);v.aim(cam,(-.15,6.0,1.52));cam.data.lens=27;cam.data.dof.use_dof=False
    scene['Project']='Класс на закате · v2 — школа и задний двор'
    scene['Scale']='Metres. Adult 1.75 m; eye 1.64 m; desks 0.70 x 0.50 x 0.75 m.'
    # Keep template doors in their own collection and out of source renders.
    from finish_school import finish
    tree_layout=finish(DOORS)
    bpy.ops.file.pack_all();bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'school_v2.blend'))
    layout={'doors':DOORS,'trees':tree_layout,'eye_height':1.64,'classroom_size':[7.4,9,3],'corridor_width':3.18}
    for path in [OUT/'school_layout.json',ROOT/'game/assets/school_layout.json']:
        path.write_text(json.dumps(layout,ensure_ascii=False,indent=2),encoding='utf-8')
    if not args.no_render:
        for name,pos,target,lens in [('school_classroom',(-.05,.88,1.64),(-.15,7.0,1.50),27),('school_corridor',(4.80,.05,1.64),(5.8,10.5,1.45),24),('school_garden',(4.0,14.8,1.64),(-7.0,17.0,1.9),26)]:
            cam.location=pos;v.aim(cam,target);cam.data.lens=lens;scene.render.filepath=str(OUT/(name+'.png'))
            bpy.ops.render.render(write_still=True)
    for ob in door_objects:ob.hide_render=False;ob.hide_set(False)
    report=export_scene(door_objects);report['doors']=DOORS
    (OUT/'school_build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SCHOOL_BUILD_DONE '+json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
