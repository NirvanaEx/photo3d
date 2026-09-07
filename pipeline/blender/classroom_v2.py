"""Editable Blender classroom v2 and matching Godot asset. Run with Blender 4.5+.

    blender -b -P pipeline/blender/classroom_v2.py -- --samples 64

Reuses the original classroom's measured layout and locally cached Poly Haven
textures. All new props are modelled here. Source files and v1 remain untouched.
Paths are resolved from this script so moving the project does not break it.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/output/loc_classroom_v2"
sys.path.insert(0, str(Path(__file__).parent))
import classroom as base

R = random.Random(1742)
M = {}
ADDED = []
COLLECTION = None


def remember(o):
    ADDED.append(o)
    if COLLECTION:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        COLLECTION.objects.link(o)
    return o


def section(name):
    global COLLECTION
    COLLECTION = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(COLLECTION)


def mat(name, rgb, rough=.55, metal=0):
    return base.mat_flat(name, rgb, rough, metal)


def box(name, pos, size, material, bevel=.006):
    x,y,z = pos
    a,b,c = (s/2 for s in size)
    return remember(base.make_box(name, x-a,x+a,y-b,y+b,z-c,z+c,material,bevel))


def rod(name, points, radius, material):
    return remember(base.tube(name, points, radius, material))


def sphere(name, pos, scale, material, segments=16, rings=8):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, location=pos)
    o = bpy.context.object
    o.name, o.scale = name, scale
    o.data.materials.append(material)
    for p in o.data.polygons:
        p.use_smooth = True
    return remember(o)


def cylinder(name, pos, radius, depth, material, rtop=None):
    bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=radius,
                                  radius2=radius if rtop is None else rtop,
                                  depth=depth, location=pos)
    o = bpy.context.object
    o.name = name
    o.data.materials.append(material)
    for p in o.data.polygons:
        p.use_smooth = len(p.vertices) == 4
    b = o.modifiers.new("Soft manufactured edges", "BEVEL")
    b.width, b.segments = .003, 2
    return remember(o)


def text(name, body, pos, size, material, rotation=(math.pi/2,0,0), font=None):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body, cu.size, cu.space_character = body, size, 1.05
    cu.extrude, cu.resolution_u = .00015, 6
    if font:
        cu.font = font
    ob = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(ob)
    ob.location, ob.rotation_euler = pos, rotation
    cu.materials.append(material)
    return remember(ob)


def aim(o, target):
    o.rotation_euler = (Vector(target)-o.location).to_track_quat("-Z", "Y").to_euler()


def repair_and_refine():
    # Resolve old Blender/WSL paths before packing. Source textures are shared.
    for im in bpy.data.images:
        if im.packed_file or im.source != 'FILE':
            continue
        old = im.filepath.replace('\\', '/')
        if 'textures/' in old:
            candidate = ROOT / 'data/textures' / old.split('textures/',1)[1]
            if candidate.exists():
                im.filepath = str(candidate)
                im.reload()
        if not Path(bpy.path.abspath(im.filepath)).exists():
            raise RuntimeError(f'Missing source texture: {im.filepath}')
    for o in list(bpy.data.objects):
        if o.name.startswith(('horizon','haze','curtain','paper')) or o.type == 'LIGHT':
            bpy.data.objects.remove(o, do_unlink=True)
    for name, color in [('wall_plaster',(.98,.97,.92)),('ceiling_tiles',(1,1,.99))]:
        m = bpy.data.materials[name]
        for n in m.node_tree.nodes:
            if n.type == 'MIX_RGB':
                n.inputs[2].default_value = (*color,1)
    floor = bpy.data.materials['floor_parquet']
    for n in floor.node_tree.nodes:
        if n.type == 'MAP_RANGE':
            n.inputs['To Min'].default_value = .22
            n.inputs['To Max'].default_value = .43
        if n.type == 'MIX_RGB':
            n.inputs[2].default_value = (.88,.86,.78,1)
    for name, col, metallic in [('frame_metal',(.29,.32,.33),.72),('alu',(.51,.53,.52),.8)]:
        b = bpy.data.materials[name].node_tree.nodes.get('Principled BSDF')
        b.inputs['Base Color'].default_value = (*col,1)
        b.inputs['Metallic'].default_value = metallic
    b = bpy.data.materials['glass'].node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (.84,.93,.98,1)
    b.inputs['Alpha'].default_value = .13
    b.inputs['Transmission Weight'].default_value = 0
    b.inputs['Roughness'].default_value = .07
    bpy.data.materials['glass'].surface_render_method = 'DITHERED'
    for o in bpy.data.objects:
        if o.name.startswith('glass'):
            o.visible_shadow = False
    # The original chalkboard bake stays visible below the new writing.
    for o in bpy.data.objects:
        if o.type == 'MESH' and any(o.name.startswith(p) for p in ('desk_', 'chair_', 'lectern_', 'cab')):
            for mo in o.modifiers:
                if mo.type == 'BEVEL':
                    mo.segments = 3


def refine_board():
    """Low-contrast eraser wear, shared as an image by Cycles and glTF."""
    w,h=1024,512
    x,y=np.meshgrid(np.linspace(0,1,w),np.linspace(0,1,h))
    rnd=np.random.default_rng(1742)
    wear=np.zeros((h,w),dtype=np.float32)
    for k in range(28):
        cx,cy=rnd.random(2)
        wear+=np.exp(-((x-cx)/rnd.uniform(.12,.36))**2-((y-cy)/.018)**2)*rnd.uniform(.003,.017)
    grain=rnd.normal(0,.002,(h,w))+wear
    pixels=np.empty((h,w,4),dtype=np.float32)
    for i,c in enumerate((.15,.255,.205)):pixels[:,:,i]=c+grain
    pixels[:,:,3]=1
    im=bpy.data.images.get('V2 subtle chalkboard wear') or bpy.data.images.new('V2 subtle chalkboard wear',width=w,height=h)
    im.pixels.foreach_set(pixels.ravel());im.pack()
    m=mat('V2 rubbed green chalkboard',(.15,.255,.205),.87)
    n=m.node_tree.nodes.new('ShaderNodeTexImage');n.image=im
    m.node_tree.links.new(n.outputs['Color'],m.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
    board=bpy.data.objects['board'];board.data.materials.clear();board.data.materials.append(m)
    uv=board.data.uv_layers.active
    for p in board.data.polygons:
        for li in p.loop_indices:
            co=board.data.vertices[board.data.loops[li].vertex_index].co
            uv.data[li].uv=((co.x+2.2)/3.6,(co.z-.9)/1.2)


def materials():
    M.update({
        'paper': mat('V2 warm uncoated paper',(.83,.82,.74),.83),
        'chalk': mat('V2 chalk ivory',(.73,.79,.69),.95),
        'bluechalk': mat('V2 pale blue chalk',(.31,.61,.68),.95),
        'ink': mat('V2 blue black ink',(.025,.057,.09),.9),
        'red': mat('V2 oxblood bookcloth',(.24,.038,.028),.82),
        'navy': mat('V2 navy school canvas',(.026,.055,.095),.87),
        'sage': mat('V2 sage notebook',(.14,.24,.19),.8),
        'linen': mat('V2 ivory linen',(.78,.79,.72),.94),
        'green': mat('V2 ficus deep green',(.065,.16,.036),.38),
        'leaflight': mat('V2 new leaf green',(.18,.30,.068),.44),
        'vein': mat('V2 leaf veins',(.17,.23,.048),.64),
        'stem': mat('V2 bark',(.13,.072,.028),.95),
        'terra': mat('V2 terracotta',(.31,.105,.047),.85),
        'soil': mat('V2 potting soil',(.027,.019,.013),1),
        'ceramic': mat('V2 blue grey ceramic',(.11,.22,.24),.23),
        'brass': mat('V2 worn brass',(.48,.30,.11),.3,.8),
        'rubber': mat('V2 rubber feet',(.021,.023,.025),.9),
        'paint': mat('V2 muted sage wall paint',(.30,.38,.33),.81),
        'stucco': mat('V2 courtyard pale plaster',(.51,.48,.40),.92),
        'asphalt': mat('V2 courtyard paving',(.19,.20,.18),.98),
        'window': mat('V2 distant cool windows',(.12,.23,.30),.18,.25),
    })
    M['linen'].node_tree.nodes['Principled BSDF'].inputs['Sheen Weight'].default_value = .26


def notebook(x,y,z,angle=0,opened=False,color='sage'):
    first = len(ADDED)
    w=.29 if opened else .145
    box('Notebook cloth cover',(x,y,z+.003),(w,.205,.006),M[color],.002)
    box('Ivory page block',(x,y,z+.009),(w-.009,.195,.008),M['paper'],.001)
    if not opened:
        box('Notebook top cover',(x,y,z+.016),(w,.205,.004),M[color],.001)
        box('Paper name label',(x,y-.02,z+.0185),(.098,.045,.0006),M['paper'],0)
        for i in range(2):
            rod('Name on notebook',[(x-.032,y-.022+i*.013,z+.019),(x+.025,y-.022+i*.013,z+.019)],.0005,M['ink'])
    else:
        rod('Notebook centre fold',[(x,y-.095,z+.014),(x,y+.095,z+.014)],.0006,M['ink'])
        for side in (-1,1):
            xx=x+side*.073
            for k in range(13):
                yy=y-.083+k*.013
                rod('Ruled page',[(xx-.058,yy,z+.014),(xx+.058,yy,z+.014)],.00022,M['bluechalk'])
            for k in range(7):
                yy=y-.071+k*.020
                pts=[(xx-.048+i*.011, yy+R.uniform(-.002,.002),z+.0147) for i in range(R.randint(5,9))]
                rod('Handwritten class notes',pts,.00045,M['ink'])
    for o in ADDED[first:]:
        if o.type=='MESH':
            # New boxes use world-space vertices; cylinders/text use transforms.
            if o.location.length < .0001:
                base._spin_group([o],x,y,angle)
    return z+.02


def pencil(x,y,z,angle=.3):
    a=Vector((x,y,z)); d=Vector((math.cos(angle),math.sin(angle),0))
    rod('Hexagonal yellow pencil',[a,a+d*.155],.003,M['terra'])
    rod('Graphite pencil tip',[a+d*.155,a+d*.166],.0011,M['ink'])
    rod('Pencil ferrule',[a-d*.01,a],.0033,M['brass'])


def backpack(x,y,z,angle=0):
    o=box('Canvas backpack body',(x,y,z+.20),(.27,.14,.36),M['navy'],.055)
    for mo in o.modifiers: mo.segments=5
    box('Backpack front pocket',(x,y-.082,z+.15),(.215,.037,.16),M['navy'],.024)
    rod('Bag carry handle',[(x-.05,y,z+.38),(x-.045,y,z+.425),(x+.045,y,z+.425),(x+.05,y,z+.38)],.008,M['navy'])
    for s in (-1,1):
        rod('Backpack shoulder strap',[(x+s*.09,y+.05,z+.34),(x+s*.12,y+.17,z+.19),(x+s*.08,y+.05,z+.05)],.012,M['navy'])
    rod('Pocket zipper',[(x-.09,y-.103,z+.22),(x+.09,y-.103,z+.22)],.0017,M['brass'])
    box('Backpack sewn patch',(x+.048,y-.105,z+.17),(.045,.002,.018),M['paper'],.001)


def desks_and_details():
    section('03 | Personal belongings')
    for i,(x,y) in enumerate([(x,y) for y in base.ROWS for x in base.COLS]):
        if i in (0,5,10):
            notebook(x-.04,y-.015,.734, R.uniform(-9,9),True)
            pencil(x+.13,y-.055,.751,1.4)
        elif i in (2,4,7,8,13,15):
            notebook(x-.07,y+.01,.735, R.uniform(-12,12),False, 'red' if i%2 else 'navy')
        if i in (0,6,11):
            backpack(x+.29,y-.16,.035)
    notebook(1.10,7.79,.853,-8,True)
    z=.85
    for k in range(3):
        z=notebook(1.62,7.94,z,4,False,('red','sage','navy')[k])+.003
    cylinder('Teacher ceramic mug',(1.54,7.62,.905),.042,.103,M['ceramic'])
    cylinder('Dark tea surface',(1.54,7.62,.958),.035,.001,M['stem'])
    rod('Mug handle',[(1.576,7.62,.935),(1.615,7.62,.927),(1.615,7.62,.887),(1.576,7.62,.88)],.006,M['ceramic'])
    cylinder('Pencil cup',(.94,8.04,.91),.035,.12,M['terra'])
    for k in range(5):
        rod('Pencils in cup',[(.94+R.uniform(-.018,.018),8.04+R.uniform(-.018,.018),.88),(.94+R.uniform(-.033,.033),8.04+R.uniform(-.03,.03),1.08)],.003,M['brass'])
    # A rubbed board eraser and felt underside resting in the tray.
    box('Wood chalk eraser',(-1.4,8.94,.907),(.16,.055,.036),bpy.data.materials['desk_wood'])
    box('Eraser felt',(-1.4,8.94,.887),(.16,.056,.006),M['rubber'],.002)


def board_and_wall():
    section('04 | Chalk, notices and classroom fittings')
    handwriting = bpy.data.fonts.load('C:/Windows/Fonts/segoepr.ttf')
    regular = bpy.data.fonts.load('C:/Windows/Fonts/segoeui.ttf')
    y=8.973
    text('Lesson heading','Свет и тень',(-1.97,y,1.87),.142,M['chalk'],font=handwriting)
    text('Date','7 сентября',(.49,y,1.96),.068,M['chalk'],font=handwriting)
    text('Lesson notes','Угол падения = углу отражения',(-1.98,y,1.64),.073,M['chalk'],font=handwriting)
    text('Lesson notes','Наблюдай, как меняется свет.',(-1.98,y,1.48),.066,M['chalk'],font=handwriting)
    text('Homework','Домой: зарисовка окна на закате',(-1.98,y,1.11),.059,M['chalk'],font=handwriting)
    rod('Chalk underline',[(-1.98,y,1.82),(-.77,y,1.813),(-.53,y,1.823)],.002,M['chalk'])
    # Reflection construction: actual lines, arcs and arrows, not a decal.
    for pts in [[(.15,y,1.22),(1.08,y,1.22)],[(.60,y,1.22),(.60,y,1.83)],[(.18,y,1.78),(.60,y,1.22),(1.02,y,1.78)]]:
        rod('Optics diagram',pts,.0018,M['bluechalk'])
    for x,sgn in ((.20,1),(1.0,-1)):
        rod('Chalk arrow',[(x,y,1.74),(x+.08*sgn,y,1.69),(x+.03*sgn,y,1.78)],.0016,M['bluechalk'])
    text('Diagram alpha','α',(.43,y,1.46),.09,M['chalk'],font=handwriting)
    text('Diagram beta','β',(.7,y,1.46),.09,M['chalk'],font=handwriting)
    text('Room motto','ЗАМЕЧАЙ СВЕТ',(-.867,8.961,2.643),.049,M['ink'],font=regular)
    for k in range(12):
        a=k*math.tau/12
        x,z=math.sin(a),math.cos(a)
        rod('Clock index',[(x*.117,8.924,2.62+z*.117),(x*.133,8.924,2.62+z*.133)],.002,M['ink'])
    # Correct the frozen clock to 17:42.
    for name in ('hand_h','hand_m'):
        bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True)
    for length,angle in ((.078,(5+42/60)*math.tau/12),(.119,42*math.tau/60)):
        rod('Clock hand 17 42',[(0,8.922,2.62),(length*math.sin(angle),8.922,2.62+length*math.cos(angle))],.003,M['ink'])
    for j,(x,z) in enumerate([(1.89,1.91),(2.27,1.53),(1.9,1.28),(2.95,1.96),(3.17,1.57),(2.89,1.28)]):
        box('Pinned notice',(x,8.967,z),(.24,.002,.30),M['paper'],0)
        sphere('Red drawing pin',(x,8.96,z+.135),(.008,.004,.008),M['red'],12,6)
        text('Notice heading',('ПЛАН','КРУЖОК','ДЕЖУРСТВО')[j%3],(x-.105,8.963,z+.096),.022,M['ink'],font=regular)
        for k in range(8):
            length=R.uniform(.08,.20)
            rod('Notice printed line',[(x-.105,8.963,z+.049-k*.020),(x-.105+length,8.963,z+.049-k*.020)],.00065,M['ink'])
    # Two-tone plaster, switch plates and a believable timber sliding door.
    box('Sage lower right wall',(3.689,4.5,.57),(.012,9,1.08),M['paint'],0)
    box('Right dado rail',(3.678,4.5,1.12),(.025,9,.035),bpy.data.materials['trim_wood'])
    box('Rear sage dado',(0,.012,.57),(7.4,.018,1.08),M['paint'],0)
    box('Rear dado rail',(0,.025,1.12),(7.4,.025,.035),bpy.data.materials['trim_wood'])
    for ya in (1.25,7.65):
        box('Door wood panel',(3.666,ya,1.07),(.045,.90,2.13),bpy.data.materials['cabinet_wood'])
        for dy in (-.49,.49):
            box('Door jamb',(3.627,ya+dy,1.13),(.09,.06,2.26),bpy.data.materials['trim_wood'])
        box('Door lintel',(3.627,ya,2.26),(.09,1.05,.07),bpy.data.materials['trim_wood'])
        box('Door frosted inset',(3.635,ya,1.65),(.014,.69,.66),M['window'])
        rod('Door handle',[(3.575,ya-.30,.88),(3.55,ya-.30,.91),(3.55,ya-.30,1.08),(3.575,ya-.30,1.1)],.012,M['brass'])
    box('Switch plate',(3.61,2.02,1.25),(.035,.10,.14),M['paper'])
    for dz in (-.029,.029):
        box('Light switch',(3.584,2.02,1.25+dz),(.022,.057,.035),M['linen'],.002)


def leaf(name, start, end, width, material):
    start,end=Vector(start),Vector(end)
    axis=end-start
    side=axis.cross(Vector((0,0,1))).normalized()*width
    verts=[]
    for t in (0,.25,.5,.75,1):
        mid=start+axis*t+Vector((0,0,math.sin(t*math.pi)*width*.40))
        w=math.sin(math.pi*t)**.7
        verts.extend([mid-side*w,mid+Vector((0,0,width*.10*w)),mid+side*w])
    faces=[]
    for i in range(4):
        for j in range(2):
            a=i*3+j;faces.append((a,a+1,a+4,a+3))
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(verts,[],faces);mesh.update()
    ob=bpy.data.objects.new(name,mesh);bpy.context.scene.collection.objects.link(ob)
    mesh.materials.append(material)
    for p in mesh.polygons:p.use_smooth=True
    return remember(ob)


def plant(x,y,z,scale=1):
    s=scale
    cylinder('Terracotta pot',(x,y,z+.115*s),.095*s,.23*s,M['terra'],.135*s)
    cylinder('Pot rim',(x,y,z+.23*s),.142*s,.025*s,M['terra'])
    cylinder('Dark potting soil',(x,y,z+.234*s),.125*s,.012*s,M['soil'])
    rod('Ficus woody stem',[(x,y,z+.23*s),(x+.025*s,y,z+.63*s),(x-.015*s,y,z+.97*s)],.009*s,M['stem'])
    for k in range(15):
        zz=z+(.38+k*.039)*s;a=k*2.4
        start=Vector((x,y,zz));tip=start+Vector((math.cos(a)*.25*s,math.sin(a)*.25*s,.09*s))
        rod('Ficus petiole',[start,start.lerp(tip,.42)],.0025*s,M['stem'])
        leaf('Waxy ficus leaf',start.lerp(tip,.30),tip,.055*s,M['green'] if k%3 else M['leaflight'])
        rod('Leaf central vein',[start.lerp(tip,.33)+Vector((0,0,.003)),start.lerp(tip,.82)+Vector((0,0,.015*s))],.00065*s,M['vein'])


def curtains_and_greenery():
    section('05 | Linen and window plants')
    for i,(y0,y1) in enumerate(base.WIN_BAYS):
        rod('Curtain track',[(-3.52,y0-.13,2.74),(-3.52,y1+.13,2.74)],.011,bpy.data.materials['alu'])
        for side,ya in enumerate((y0-.025,y1-.30)):
            verts=[];faces=[];nc,nr=30,24
            for iz in range(nr):
                v=iz/(nr-1);zz=2.70-v*2.07
                for iy in range(nc):
                    u=iy/(nc-1)
                    yy=ya+u*.32+.05*math.sin(v*math.pi)*(1 if side==0 else -1)
                    xx=-3.53+.041*math.sin(u*math.tau*4)+.12*math.sin(v*math.pi*.85)**2
                    verts.append((xx,yy,zz+.018*math.cos(u*math.tau*4)*v))
            for iz in range(nr-1):
                for iy in range(nc-1):
                    a=iz*nc+iy;faces.append((a,a+1,a+nc+1,a+nc))
            me=bpy.data.meshes.new('Woven curtain folds');me.from_pydata(verts,[],faces);me.update()
            ob=bpy.data.objects.new(f'Linen curtain {i+1} {side+1}',me);bpy.context.scene.collection.objects.link(ob)
            me.materials.append(M['linen']);remember(ob)
            for p in me.polygons:p.use_smooth=True
            sol=ob.modifiers.new('Cloth thickness','SOLIDIFY');sol.thickness=.0012
            for k in range(7):
                rod('Curtain hanging tab',[(-3.53,ya+k*.05,2.68),(-3.52,ya+k*.05,2.75)],.003,M['linen'])
    plant(-3.64,3.84,.85,.60)
    plant(-3.64,6.06,.85,.78)
    plant(-2.92,8.39,0,1.26)


def refine_fittings():
    # Use each actual desk's jitter and rotation, rather than the nominal grid.
    for ob in list(bpy.data.objects):
        if ob.name.startswith('Desk rubber foot'):
            bpy.data.objects.remove(ob,do_unlink=True)
    rubber=bpy.data.materials['V2 rubber feet']
    for ob in list(bpy.data.objects):
        if not ob.name.startswith('desk_top'):continue
        points=[ob.matrix_world@v.co for v in ob.data.vertices]
        center=sum(points,Vector())/len(points)
        dx=(points[1]-points[0]).normalized()
        dy=Vector((-dx.y,dx.x,0))
        for sx in (-1,1):
            for sy in (-1,1):
                pos=center+dx*sx*.285+dy*sy*.205;pos.z=.022
                cylinder('Desk rubber foot',pos,.016,.034,rubber)
    # Idempotent repair for saved drafts. A pot's base must sit on the sill.
    prefixes=('Terracotta pot','Pot rim','Dark potting soil','Ficus woody stem',
              'Ficus petiole','Waxy ficus leaf','Leaf central vein')
    for yy in (3.84,6.06):
        pot=next(o for o in bpy.data.objects if o.name.startswith('Terracotta pot') and abs(o.location.y-yy)<.01)
        delta=-3.64-pot.location.x
        for ob in bpy.data.objects:
            if not ob.name.startswith(prefixes):continue
            midpoint=sum((ob.matrix_world@Vector(p) for p in ob.bound_box),Vector())/8
            if abs(midpoint.y-yy)<.4:
                ob.location.x+=delta


def courtyard():
    section('06 | Courtyard beyond the windows')
    box('Courtyard ground',(-17,5,-3.15),(27,42,.2),M['asphalt'],0)
    box('Opposite school wing',(-22,7,1.0),(3.2,29,8.0),M['stucco'],.035)
    for level in (-1.5,1.25,4.0):
        box('School facade floor band',(-20.37,7,level-1.0),(.18,29,.13),M['paper'],.01)
        for yy in range(-6,22,3):
            box('Courtyard school window',(-20.385,yy,level),(.045,1.8,1.6),M['window'],.01)
            for dy in (-.93,0,.93):
                box('Courtyard window mullion',(-20.33,yy+dy,level),(.08,.045,1.70),M['paper'],.004)
            box('Courtyard window sill',(-20.23,yy,level-.84),(.29,2.0,.055),M['paper'],.004)
    for x,y,h in [(-10,1,4.8),(-12,7,5.3),(-11,13,4.9),(-16,-5,5.9),(-15,19,6.3)]:
        z=-3.04
        rod('Courtyard tree trunk',[(x,y,z),(x+.17,y,z+h*.7),(x+.10,y+.2,z+h)],.105,M['stem'])
        for k in range(12):
            a=k*2.4;zz=z+h*.5+k*.14
            end=Vector((x+math.cos(a)*1.45,y+math.sin(a)*1.45,zz+.7))
            rod('Tree branch',[(x+.1,y,zz),end],.022,M['stem'])
            for j in range(20):
                center=end+Vector((R.uniform(-.60,.60),R.uniform(-.60,.60),R.uniform(-.33,.53)))
                d=Vector((R.uniform(-.30,.30),R.uniform(-.30,.30),R.uniform(-.07,.16)))
                leaf('Courtyard tree leaf',center,center+d,.09,M['green'] if j%3 else M['leaflight'])


def lighting(samples):
    section('07 | Sunset lighting')
    scene=bpy.context.scene
    world=bpy.data.worlds.new('V2 cool sky fill');world.use_nodes=True
    bg=world.node_tree.nodes['Background'];bg.inputs[0].default_value=(.44,.57,.78,1);bg.inputs[1].default_value=.26
    scene.world=world
    e,a=math.radians(22),math.radians(24)
    direction=Vector((math.cos(a)*math.cos(e),math.sin(a)*math.cos(e),-math.sin(e)))
    data=bpy.data.lights.new('Low September sun','SUN');data.energy=7.5;data.color=(1,.57,.27);data.angle=math.radians(.7)
    o=bpy.data.objects.new('Low September sun',data);scene.collection.objects.link(o);remember(o)
    o.rotation_euler=direction.to_track_quat('-Z','Y').to_euler();o.location=(-8,0,6)
    for i,(y0,y1) in enumerate(base.WIN_BAYS):
        data=bpy.data.lights.new('Soft window sky','AREA');data.energy=42;data.color=(.93,.82,.67)
        data.shape='RECTANGLE';data.size=y1-y0;data.size_y=1.6
        o=bpy.data.objects.new(f'Window sky fill {i+1}',data);scene.collection.objects.link(o);remember(o)
        o.location=(-3.78,(y0+y1)/2,1.8);aim(o,(0,(y0+y1)/2,1.2))
    base.setup_cycles(scene,samples)
    scene.cycles.adaptive_threshold=.035
    scene.view_settings.view_transform='AgX';scene.view_settings.exposure=.7
    scene.view_settings.look='AgX - Medium High Contrast'
    scene.render.resolution_x=1600;scene.render.resolution_y=1000;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.render.film_transparent=False
    # A whisper of glow from bright panes; no blanket orange filter.
    scene.use_nodes=True
    nt=scene.node_tree;nt.nodes.clear()
    rl=nt.nodes.new('CompositorNodeRLayers');gl=nt.nodes.new('CompositorNodeGlare');gl.glare_type='FOG_GLOW';gl.quality='HIGH';gl.threshold=2;gl.mix=-.96
    out=nt.nodes.new('CompositorNodeComposite');nt.links.new(rl.outputs['Image'],gl.inputs['Image']);nt.links.new(gl.outputs['Image'],out.inputs['Image'])
    cam=scene.camera;cam.name='Camera | classroom hero';cam.location=(2.86,.79,1.65);aim(cam,(-.58,7.5,1.22));cam.data.lens=23.5
    cam.data.dof.use_dof=False
    return direction


def export_game():
    # Export a disposable copy of the in-memory geometry; the editable .blend
    # was saved first. Curves and type are converted only for glTF.
    for o in list(bpy.context.scene.objects):
        if o.type in {'FONT','CURVE'}:
            bpy.ops.object.select_all(action='DESELECT');o.select_set(True);bpy.context.view_layer.objects.active=o
            bpy.ops.object.convert(target='MESH')
    # Join by material after evaluating modifiers, avoiding hundreds of draw calls.
    groups=defaultdict(list)
    depsgraph=bpy.context.evaluated_depsgraph_get()
    for o in list(bpy.context.scene.objects):
        if o.type!='MESH':continue
        if o.modifiers:
            mesh=bpy.data.meshes.new_from_object(o.evaluated_get(depsgraph),depsgraph=depsgraph)
            o.modifiers.clear();o.data=mesh
        key=tuple(s.material.name if s.material else '' for s in o.material_slots)
        groups[key].append(o)
    visible=[]
    for key,objs in groups.items():
        bpy.ops.object.select_all(action='DESELECT')
        for ob in objs:ob.select_set(True)
        bpy.context.view_layer.objects.active=objs[0]
        if len(objs)>1:bpy.ops.object.join()
        ob=bpy.context.object;ob.name='V2 '+(' + '.join(key))[:110];visible.append(ob)
    # Keep the already-tested collision shell from v1. Furniture positions match.
    before=set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(ROOT/'game/assets/models/m_classroom_game.glb'))
    imported=set(bpy.context.scene.objects)-before
    colliders=[o for o in imported if 'colonly' in o.name]
    if not colliders:
        raise RuntimeError('No v1 collision shell found; game export must retain walkable collisions.')
    for o in imported:
        if o not in colliders:bpy.data.objects.remove(o,do_unlink=True)
    for o in colliders:o.parent=None
    bpy.ops.object.select_all(action='DESELECT')
    for ob in visible+colliders:ob.select_set(True)
    dest=ROOT/'game/assets/models/classroom_v2.glb'
    bpy.ops.export_scene.gltf(filepath=str(dest),export_format='GLB',use_selection=True,
                              export_animations=False,export_cameras=False,export_lights=False,
                              export_materials='EXPORT',export_image_format='AUTO')
    if not dest.exists() or dest.stat().st_size<100000:raise RuntimeError('Empty v2 GLB export')
    return {'glb':str(dest),'size_mb':round(dest.stat().st_size/1e6,2),'draw_meshes':len(visible),'collision_meshes':len(colliders)}


def main():
    p=argparse.ArgumentParser();p.add_argument('--samples',type=int,default=64);p.add_argument('--preview',action='store_true');p.add_argument('--skip-export',action='store_true')
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    OUT.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(ROOT/'data/output/loc_classroom/classroom_baked.blend'))
    repair_and_refine();refine_board();materials();desks_and_details();board_and_wall();curtains_and_greenery();courtyard();refine_fittings()
    d=lighting(args.samples)
    scene=bpy.context.scene
    scene['Project']='Класс на закате — v2';scene['Design']='Реалистичная атмосфера после последнего урока. 17:42.'
    scene['Asset sources']='Original photo3d classroom; local Poly Haven CC0 textures; new props modelled in classroom_v2.py.'
    # Every used image/font travels inside the .blend; no old D:\\Develop paths.
    bpy.ops.file.pack_all()
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.region_3d.view_perspective='CAMERA'
                area.spaces.active.clip_end=200
    blend=OUT/'classroom_v2.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    if args.preview:
        scene.render.resolution_percentage=60
    scene.render.filepath=str(OUT/'classroom_v2.png')
    bpy.ops.render.render(write_still=True)
    result={'blend':str(blend),'render':scene.render.filepath,'sun_direction_blender':list(d),
            'objects':len(scene.objects),'new_objects':len(ADDED)}
    if not args.skip_export:result.update(export_game())
    (OUT/'build.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CLASSROOM_V2_DONE '+json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
