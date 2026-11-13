# Blender: import the apartment GLB, light it, render named views.
# usage: blender -b -P render.py -- <glb> <outdir> <prefix> <samples> <view,view,...>
import bpy, sys, math
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
glb, outdir, prefix, samples, views = argv[0], argv[1], argv[2], int(argv[3]), argv[4].split(',')

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
scene = bpy.context.scene

def P(x, y, h):  # plan coords (x right, y down), height -> Blender
    return Vector((x, -y, h))

# ---------- materials
def nodes_of(m):
    m.use_nodes = True
    return m.node_tree.nodes, m.node_tree.links

def principled(m):
    for n in m.node_tree.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            return n
    return None

for m in bpy.data.materials:
    base = m.name.split('.')[0]
    if not m.node_tree:
        continue
    nt, lk = nodes_of(m)
    out = next((n for n in nt if n.type == 'OUTPUT_MATERIAL'), None)
    if base == 'glass':
        nt.clear(); out = nt.new('ShaderNodeOutputMaterial')
        tr = nt.new('ShaderNodeBsdfTransparent'); gl = nt.new('ShaderNodeBsdfGlossy'); mix = nt.new('ShaderNodeMixShader')
        gl.inputs['Roughness'].default_value = 0.02
        mix.inputs[0].default_value = 0.08
        lk.new(tr.outputs[0], mix.inputs[1]); lk.new(gl.outputs[0], mix.inputs[2]); lk.new(mix.outputs[0], out.inputs[0])
    elif base in ('shade', 'led'):
        nt.clear(); out = nt.new('ShaderNodeOutputMaterial')
        em = nt.new('ShaderNodeEmission')
        em.inputs['Color'].default_value = (1.0, 0.82, 0.6, 1)
        em.inputs['Strength'].default_value = 6.0 if base == 'led' else 3.0
        lk.new(em.outputs[0], out.inputs[0])
    else:
        p = principled(m)
        if not p:
            continue
        rough = {'floor': 0.38, 'loggia': 0.5, 'floorWet': 0.25, 'tileWall': 0.22, 'apron': 0.2, 'counter': 0.25, 'white': 0.15,
                 'water': 0.05, 'screen': 0.12, 'cabinet': 0.45, 'cabinetLow': 0.45, 'wood': 0.5, 'door': 0.5, 'frame': 0.4,
                 'dark': 0.35, 'metal': 0.25}.get(base)
        if rough is not None:
            p.inputs['Roughness'].default_value = rough
        if base in ('fabric', 'fabric2', 'rug', 'pop'):
            p.inputs['Roughness'].default_value = 1.0
            if 'Sheen Weight' in p.inputs:
                p.inputs['Sheen Weight'].default_value = 0.4
        # texture maps: make filtering smooth and add a faint bump from the same image
        tex = next((n for n in nt if n.type == 'TEX_IMAGE'), None)
        if tex and base in ('floor', 'loggia', 'floorWet', 'tileWall', 'accent'):
            bump = nt.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = 0.12 if base != 'accent' else 0.25
            lk.new(tex.outputs['Color'], bump.inputs['Height']); lk.new(bump.outputs['Normal'], p.inputs['Normal'])

# ---------- bevel-ish shading: smooth nothing, but add tiny bevel shader skip (keeps render fast)

# ---------- mirrors: 'glass' boxes that are not in a facade / balcony wall
mir = bpy.data.materials.new('mirror'); mir.use_nodes = True
pm = principled(mir); pm.inputs['Metallic'].default_value = 1.0; pm.inputs['Roughness'].default_value = 0.02; pm.inputs['Base Color'].default_value = (0.9, 0.9, 0.9, 1)
for o in bpy.data.objects:
    if o.type == 'MESH' and o.material_slots and o.material_slots[0].material and o.material_slots[0].material.name.split('.')[0] == 'glass':
        cx = sum((o.matrix_world @ Vector(c)).x for c in o.bound_box) / 8
        cy = -sum((o.matrix_world @ Vector(c)).y for c in o.bound_box) / 8
        is_window = cx < 0.05 or (1.25 < cx < 1.55 and cy > 7.5)
        is_screen = (5.55 < cx < 6.35 and 9.35 < cy < 9.45)
        if not is_window and not is_screen:
            o.material_slots[0].material = mir

# ---------- soften geometry: bevel + weighted normals
SOFT = ('fabric', 'fabric2', 'pop', 'rug')
for o in [o for o in bpy.data.objects if o.type == 'MESH']:
    d = o.dimensions
    if min(d) < 0.011:
        continue
    base = o.material_slots[0].material.name.split('.')[0] if o.material_slots and o.material_slots[0].material else ''
    if base in ('wall', 'shaft', 'slab', 'cut', 'glass', 'tileWall', 'ceiling', 'led'):
        continue
    wdt = 0.035 if base in SOFT else (0.02 if base == 'white' else 0.005)
    wdt = min(wdt, min(d) * 0.45)
    for pol in o.data.polygons:
        pol.use_smooth = True
    b = o.modifiers.new('bev', 'BEVEL'); b.width = wdt; b.segments = 4 if base in SOFT else 2; b.limit_method = 'ANGLE'; b.angle_limit = math.radians(40)
    wn = o.modifiers.new('wn', 'WEIGHTED_NORMAL'); wn.keep_sharp = False

# ---------- curtains (gathered at the sides of each window)
def curtain(x, y0, y1, flip=1):
    import bmesh
    me = bpy.data.meshes.new('curtain'); bm = bmesh.new()
    n = 48; rows = [0.03, 2.93]
    vs = []
    for i in range(n + 1):
        t = i / n; y = y0 + (y1 - y0) * t
        dx = 0.035 * math.sin(t * math.pi * 9) * flip
        vs.append([bm.verts.new(P(x + dx, y, h)) for h in rows])
    for i in range(n):
        bm.faces.new((vs[i][0], vs[i + 1][0], vs[i + 1][1], vs[i][1]))
    bm.to_mesh(me); bm.free()
    for pol in me.polygons:
        pol.use_smooth = True
    ob = bpy.data.objects.new('curtain', me); scene.collection.objects.link(ob)
    m = bpy.data.materials.get('curtain')
    if not m:
        m = bpy.data.materials.new('curtain'); m.use_nodes = True
        p = principled(m); p.inputs['Base Color'].default_value = (0.93, 0.90, 0.85, 1); p.inputs['Roughness'].default_value = 1.0
        p.inputs['Alpha'].default_value = 0.82
        if 'Subsurface Weight' in p.inputs:
            p.inputs['Subsurface Weight'].default_value = 0.0
    ob.data.materials.append(m)
scene = bpy.context.scene
for x, a, b in [(0.10, 0.45, 2.60), (0.10, 4.35, 6.50)]:
    curtain(x, a - 0.25, a + 0.30); curtain(x, b - 0.30, b + 0.25)
curtain(1.60, 7.56, 7.62 + 0.0, 1) if False else None
curtain(1.60, 9.85, 10.45)

# ---------- world + sun
w = bpy.data.worlds.new('W'); scene.world = w; w.use_nodes = True
bg = w.node_tree.nodes['Background']
bg.inputs['Color'].default_value = (0.62, 0.78, 1.0, 1); bg.inputs['Strength'].default_value = 1.5

sun = bpy.data.lights.new('Sun', 'SUN'); sun.energy = 4.2; sun.angle = math.radians(1.5); sun.color = (1.0, 0.93, 0.82)
so = bpy.data.objects.new('Sun', sun); scene.collection.objects.link(so)
d = Vector((0.80, -0.22, -0.48)).normalized()
so.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

# ---------- interior lights
CH = 3.0
SPOTS = [(5.35,0.95),(6.15,0.95),(6.85,1.55),(6.40,4.55),(6.40,5.55),(6.40,6.55),(1.2,5.3),(3.0,5.3),(1.2,6.1),(3.0,6.1),
         (2.4,8.4),(4.0,8.4),(2.4,9.9),(4.0,9.9),(6.3,8.05),(4.88,4.75),(4.88,5.30),(6.45,9.1),(6.9,10.25),(5.95,10.3),(0.65,8.6),(0.65,10.0),
         (1.1,1.05),(1.9,1.05),(2.7,1.05),(3.5,1.05),(1.1,2.95),(1.9,2.95),(2.7,2.95),(3.5,2.95)]
for i, (x, y) in enumerate(SPOTS):
    L = bpy.data.lights.new('sp%d' % i, 'SPOT'); L.energy = 55; L.spot_size = math.radians(95); L.spot_blend = 0.6
    L.shadow_soft_size = 0.05; L.color = (1.0, 0.86, 0.70)
    o = bpy.data.objects.new('sp%d' % i, L); o.location = P(x, y, CH - 0.03); scene.collection.objects.link(o)
AREAS = [(2.2,2.0,3.0,2.2,140),(6.0,1.6,2.0,1.4,90),(6.55,5.6,1.0,2.4,70),(2.2,5.7,2.6,1.6,110),(3.2,9.3,2.4,2.2,120),(6.6,9.8,1.2,1.6,70),(4.88,5.0,0.8,0.9,35),(0.65,9.3,0.8,2.4,60)]
for i, (x, y, sx, sy, e) in enumerate(AREAS):
    L = bpy.data.lights.new('ar%d' % i, 'AREA'); L.shape = 'RECTANGLE'; L.size = sx; L.size_y = sy; L.energy = e*0.45; L.color = (1.0, 0.9, 0.78)
    o = bpy.data.objects.new('ar%d' % i, L); o.location = P(x, y, CH - 0.06); scene.collection.objects.link(o)
# pendant over the dining table and bedside lamps
for x, y, h, e in [(5.45,2.20,1.7,60),(2.02,10.88,0.95,18),(4.38,10.88,0.95,18),(0.48,1.72,1.3,25),(2.1,5.7,2.3,40)]:
    L = bpy.data.lights.new('pl', 'POINT'); L.energy = e; L.shadow_soft_size = 0.12; L.color = (1.0, 0.8, 0.6)
    o = bpy.data.objects.new('pl', L); o.location = P(x, y, h); scene.collection.objects.link(o)

# ---------- render settings
scene.render.engine = 'CYCLES'
try:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'METAL'; prefs.get_devices()
    for dv in prefs.devices:
        dv.use = True
    scene.cycles.device = 'GPU'
except Exception as e:
    print('GPU setup failed', e)
scene.cycles.samples = samples
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 8; scene.cycles.diffuse_bounces = 5; scene.cycles.glossy_bounces = 4; scene.cycles.transparent_max_bounces = 8
scene.cycles.caustics_reflective = False; scene.cycles.caustics_refractive = False
scene.render.resolution_x = 1600; scene.render.resolution_y = 1000; scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'JPEG'; scene.render.image_settings.quality = 88
try:
    scene.view_settings.view_transform = 'AgX'; scene.view_settings.look = 'AgX - Medium High Contrast'
except Exception:
    pass

VIEWS = {  # cam (x,y,h), target (x,y,h), lens mm, exposure, hide ceiling
    'living':   ((4.40,3.78,1.45),(0.5,0.9,1.0),17,0.0,False),
    'kitchen':  ((2.9,3.3,1.45),(6.3,0.5,0.95),18,0.2,False),
    'kids':     ((0.14,5.72,1.95),(4.6,5.9,0.45),13,0.0,False),
    'kids2':    ((5.35,6.4,1.6),(1.0,5.6,0.6),17,0.0,False),
    'bedroom':  ((5.35,7.75,1.5),(2.6,10.5,0.8),17,0.0,False),
    'bedroom2': ((1.75,10.9,1.5),(5.2,8.2,0.9),17,0.0,False),
    'bath':     ((6.40,8.66,1.5),(6.45,10.9,0.95),12,0.3,False),
    'loggia':   ((0.65,7.70,1.5),(0.62,11.0,0.85),16,-0.3,False),
    'hall':     ((6.45,7.25,1.5),(6.3,3.0,1.2),17,0.3,False),
    'overview': ((-3.2,14.6,11.0),(3.7,5.4,0.3),40,-0.2,True),
}
cam_data = bpy.data.cameras.new('Cam'); cam = bpy.data.objects.new('Cam', cam_data); scene.collection.objects.link(cam); scene.camera = cam
cam_data.clip_start = 0.03; cam_data.sensor_width = 36
ceil_objs = [o for o in bpy.data.objects if o.type == 'MESH' and min((o.matrix_world @ Vector(c)).z for c in o.bound_box) > 2.9]
for v in views:
    c, t, lens, exp, hide = VIEWS[v]
    cam.location = P(*c)
    direction = P(*t) - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    cam_data.lens = lens
    scene.view_settings.exposure = exp
    for o in ceil_objs:
        o.hide_render = hide
    scene.render.filepath = '%s/%s-%s.jpg' % (outdir, prefix, v)
    bpy.ops.render.render(write_still=True)
    print('RENDERED', scene.render.filepath)
