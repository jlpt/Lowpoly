"""
Low-poly Rudeus Greyrat (Mushoku Tensei) - procedural Blender build script.

Everything (meshes, materials, the painted face texture, lighting, cameras)
is generated from this file, so the model can be tweaked and rebuilt.

Usage
-----
With Blender installed:
    blender -b -P rudeus_lowpoly.py -- [--render] [--turntable] [--quick] [--out DIR]
With the `bpy` pip module (Python 3.11):
    python3 rudeus_lowpoly.py [--render] [--turntable] [--quick] [--out DIR]

Outputs (default DIR = this folder):
    models/rudeus_lowpoly.blend   full scene (character, staff, pedestal, lights)
    models/rudeus_lowpoly.glb     character + staff (game / web ready)
    models/rudeus_lowpoly.fbx     character + staff
    models/rudeus_lowpoly.obj/.mtl
    models/textures/rudeus_face.png
    renders/*.png                 (with --render)
    renders/rudeus_turntable.gif  (with --turntable, needs Pillow)

Conventions: metres, Z up, the character faces -Y and stands on Z = 0.
"""

import math
import os
import random
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------
# Arguments
# --------------------------------------------------------------------------
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
DO_RENDER = "--render" in argv
DO_TURNTABLE = "--turntable" in argv
QUICK = "--quick" in argv
OUT = HERE
if "--out" in argv:
    OUT = os.path.abspath(argv[argv.index("--out") + 1])
ONLY_VIEWS = None
if "--views" in argv:
    ONLY_VIEWS = argv[argv.index("--views") + 1].split(",")

MODEL_DIR = os.path.join(OUT, "models")
TEX_DIR = os.path.join(MODEL_DIR, "textures")
RENDER_DIR = os.path.join(OUT, "renders")
for d in (MODEL_DIR, TEX_DIR, RENDER_DIR):
    os.makedirs(d, exist_ok=True)

random.seed(7)

# --------------------------------------------------------------------------
# Palette (sRGB hex)
# --------------------------------------------------------------------------
PALETTE = {
    "skin": "F2C6AA",
    "hair": "573522",
    "hair_hi": "65402A",
    "robe": "7C818C",
    "robe_in": "434752",
    "robe_trim": "545864",
    "shirt": "E6DFD0",
    "pants": "3F322B",
    "boot": "6A4227",
    "sole": "2E1F16",
    "belt": "4F3221",
    "gold": "C9A040",
    "wood": "5E3B22",
    "wood_dark": "3E2716",
    "crystal": "1E9FE0",
    "boot_cuff": "8A5A36",
    "stone": "707A86",
    "stone_dark": "4F5762",
    "grass": "6C9A4C",
}


def srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_lin(h):
    return tuple(srgb_to_lin(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4)) + (1.0,)


def hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# --------------------------------------------------------------------------
# Scene reset
# --------------------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
SCENE = bpy.context.scene
CHAR_COLL = bpy.data.collections.new("Rudeus_Greyrat")
SCENE.collection.children.link(CHAR_COLL)
ENV_COLL = bpy.data.collections.new("Environment")
SCENE.collection.children.link(ENV_COLL)

# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------
MATS = {}


def make_mat(name, hexcol, rough=0.8, metallic=0.0, emit=0.0, spec=0.3, image=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = hex_lin(hexcol)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metallic
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = spec
    if emit > 0:
        bsdf.inputs["Emission Color"].default_value = hex_lin(hexcol)
        bsdf.inputs["Emission Strength"].default_value = emit
    if image is not None:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.location = (-400, 200)
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    m.diffuse_color = hex_lin(hexcol)
    MATS[name] = m
    return m


# --------------------------------------------------------------------------
# Face texture (anime eyes, brows, mouth) painted with Pillow
# --------------------------------------------------------------------------
# Head-space mapping used both here and for the UV projection:
#   x in [-1, 1] * R  ->  u in [0, 1]
#   z in [-1.3, 0.7] * R (relative to head centre) -> v in [0, 1]
FACE_X0, FACE_X1 = -1.0, 1.0
FACE_Z0, FACE_Z1 = -1.3, 0.7


def paint_face_texture(path, size=1024, ss=4):
    from PIL import Image, ImageDraw, ImageFilter

    S = size * ss
    skin = hex_rgb(PALETTE["skin"])
    img = Image.new("RGBA", (S, S), skin + (255,))

    XF = [None]    # optional (cx, cz, scale) applied around an eye centre

    def P(x, z):
        if XF[0]:
            cx, cz, k = XF[0]
            x, z = cx + (x - cx) * k, cz + (z - cz) * k
        u = (x - FACE_X0) / (FACE_X1 - FACE_X0)
        v = (z - FACE_Z0) / (FACE_Z1 - FACE_Z0)
        return (u * S, (1.0 - v) * S)

    def qbez(p0, p1, p2, n=24):
        pts = []
        for i in range(n + 1):
            t = i / n
            a = (1 - t) ** 2
            b = 2 * (1 - t) * t
            c = t * t
            pts.append((a * p0[0] + b * p1[0] + c * p2[0],
                        a * p0[1] + b * p1[1] + c * p2[1]))
        return pts

    def stroke(pts, w0, w1, col, layer):
        """Variable-width stroke along a polyline (head units)."""
        d = ImageDraw.Draw(layer)
        top, bot = [], []
        n = len(pts)
        for i, p in enumerate(pts):
            a = pts[max(i - 1, 0)]
            b = pts[min(i + 1, n - 1)]
            tx, tz = b[0] - a[0], b[1] - a[1]
            ln = math.hypot(tx, tz) or 1.0
            nx, nz = -tz / ln, tx / ln
            w = (w0 + (w1 - w0) * i / (n - 1)) * 0.5
            top.append(P(p[0] + nx * w, p[1] + nz * w))
            bot.append(P(p[0] - nx * w, p[1] - nz * w))
        d.polygon(top + bot[::-1], fill=col)

    def ellipse(layer, cx, cz, rx, rz, col):
        d = ImageDraw.Draw(layer)
        x0, y0 = P(cx - rx, cz + rz)
        x1, y1 = P(cx + rx, cz - rz)
        d.ellipse([x0, y0, x1, y1], fill=col)

    lash = hex_rgb("2A1710") + (255,)
    brow = hex_rgb("5A3320") + (255,)
    white = hex_rgb("FBFCFF") + (255,)
    iris_top = hex_rgb("1C5236")
    iris_bot = hex_rgb("5CC07E")
    pupil = hex_rgb("0F2F1F") + (255,)
    iris_rim = hex_rgb("143A27") + (255,)

    # soft blush
    blush = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    for sx in (-1, 1):
        ellipse(blush, sx * 0.50, -0.60, 0.13, 0.055, hex_rgb("F2A49A") + (70,))
    blush = blush.filter(ImageFilter.GaussianBlur(S * 0.012))
    img = Image.alpha_composite(img, blush)

    for sx in (-1, 1):
        ex = 0.40 * sx
        XF[0] = (ex, -0.31, 1.10)
        # x helper: "outer" direction is away from the nose
        def X(dx):
            return ex + dx * sx

        # upper lid / lash line (inner corner -> outer corner)
        upper = qbez((X(-0.165), -0.255), (X(-0.02), -0.105), (X(0.185), -0.215))
        lash_w = [0.030 + 0.035 * (i / (len(upper) - 1)) ** 1.2 for i in range(len(upper))]
        lower = qbez((X(0.170), -0.255), (X(0.02), -0.515), (X(-0.150), -0.300))

        # lash lower edge = upper curve pushed down by half width
        lash_lower_edge = [(p[0], p[1] - w * 0.5) for p, w in zip(upper, lash_w)]

        # eye white mask
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).polygon([P(*p) for p in lash_lower_edge + lower], fill=255)

        eye = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(eye).polygon([P(*p) for p in lash_lower_edge + lower], fill=white)

        # iris with vertical gradient
        icx, icz, irx, irz = X(-0.005), -0.325, 0.108, 0.150
        iris = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        x0, y0 = P(icx - irx, icz + irz)
        x1, y1 = P(icx + irx, icz - irz)
        h = int(y1 - y0)
        grad = Image.new("RGBA", (int(x1 - x0) + 1, h + 1))
        gd = ImageDraw.Draw(grad)
        for yy in range(h + 1):
            t = (yy / h) ** 1.3
            c = tuple(int(iris_top[k] + (iris_bot[k] - iris_top[k]) * t) for k in range(3))
            gd.line([(0, yy), (grad.width, yy)], fill=c + (255,))
        emask = Image.new("L", grad.size, 0)
        ImageDraw.Draw(emask).ellipse([0, 0, grad.width - 1, grad.height - 1], fill=255)
        rim = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ellipse(rim, icx, icz, irx + 0.012, irz + 0.012, iris_rim)
        iris = Image.alpha_composite(iris, rim)
        iris.paste(grad, (int(x0), int(y0)), emask)
        ellipse(iris, icx, icz + 0.012, 0.050, 0.078, pupil)
        # iris inner light ring (bottom)
        glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ellipse(glow, icx, icz - 0.075, 0.07, 0.04, hex_rgb("9BE6AE") + (150,))
        glow = glow.filter(ImageFilter.GaussianBlur(S * 0.006))
        iris = Image.alpha_composite(iris, glow)
        # highlights (same light direction for both eyes)
        ellipse(iris, icx - 0.045, icz + 0.070, 0.036, 0.040, white)
        ellipse(iris, icx + 0.040, icz - 0.075, 0.016, 0.016, white)

        clipped = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        clipped.paste(iris, (0, 0), mask)
        eye = Image.alpha_composite(eye, clipped)

        # lid shadow under lash
        shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        stroke([(p[0], p[1] - 0.025) for p in lash_lower_edge], 0.045, 0.05,
               hex_rgb("8EA0B8") + (90,), shadow)
        shadow = shadow.filter(ImageFilter.GaussianBlur(S * 0.004))
        sh_clip = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        sh_clip.paste(shadow, (0, 0), mask)
        eye = Image.alpha_composite(eye, sh_clip)

        img = Image.alpha_composite(img, eye)

        lines = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        stroke(upper, lash_w[0], lash_w[-1], lash, lines)
        # outer flick
        stroke([upper[-1], (X(0.215), -0.255)], lash_w[-1] * 0.9, 0.01, lash, lines)
        # lower lash (outer half only)
        stroke(qbez((X(0.165), -0.27), (X(0.11), -0.43), (X(0.0), -0.475)), 0.016, 0.006,
               lash, lines)
        # double eyelid crease
        stroke(qbez((X(-0.10), -0.115), (X(0.02), -0.050), (X(0.15), -0.125)), 0.006, 0.010,
               hex_rgb("B9846A") + (255,), lines)
        # eyebrow
        stroke(qbez((X(-0.15), 0.035), (X(0.0), 0.110), (X(0.19), 0.050)), 0.040, 0.018,
               brow, lines)
        img = Image.alpha_composite(img, lines)
        XF[0] = None

    feat = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # nose hint
    stroke([(0.015, -0.585), (0.030, -0.640)], 0.010, 0.016, hex_rgb("D9A58C") + (255,), feat)
    # mouth: small relaxed smile
    stroke(qbez((-0.085, -0.855), (0.0, -0.900), (0.085, -0.855)), 0.014, 0.014,
           hex_rgb("9A4E40") + (255,), feat)
    img = Image.alpha_composite(img, feat)

    img = img.convert("RGB").resize((size, size), Image.LANCZOS)
    img.save(path)
    return path


# --------------------------------------------------------------------------
# Mesh building helpers
# --------------------------------------------------------------------------
def circle(n, phase=0.0):
    return [(math.cos(phase + 2 * math.pi * j / n), math.sin(phase + 2 * math.pi * j / n))
            for j in range(n)]


def arc(n, a0, a1):
    return [(math.cos(a0 + (a1 - a0) * j / (n - 1)), math.sin(a0 + (a1 - a0) * j / (n - 1)))
            for j in range(n)]


class MB:
    """Accumulates vertices/faces (with material indices) for one object."""

    def __init__(self):
        self.v = []
        self.f = []
        self.m = []

    def vert(self, p):
        self.v.append(Vector(p))
        return len(self.v) - 1

    def face(self, idx, mat=0):
        self.f.append(tuple(idx))
        self.m.append(mat)

    def bridge(self, rings, closed=True, cap0=True, cap1=True, mat=0, mats=None,
               cap_mat=None):
        """Connect consecutive rings of vertex indices. A ring of length 1 is a pole.
        Ring orientation: profile CCW around the travel direction -> outward normals."""
        n = max(len(r) for r in rings)
        segs = n if closed else n - 1
        for i in range(len(rings) - 1):
            a, b = rings[i], rings[i + 1]
            mi = mats[i] if mats else mat
            for j in range(segs):
                j1 = (j + 1) % n
                if len(a) == 1 and len(b) == 1:
                    continue
                if len(a) == 1:
                    self.face((a[0], b[j1], b[j]), mi)
                elif len(b) == 1:
                    self.face((a[j], a[j1], b[0]), mi)
                else:
                    self.face((a[j], a[j1], b[j1], b[j]), mi)
        cm = mat if cap_mat is None else cap_mat
        if closed:
            if cap0 and len(rings[0]) > 2:
                self.face(tuple(reversed(rings[0])), cm)
            if cap1 and len(rings[-1]) > 2:
                self.face(tuple(rings[-1]), cm)
        return rings

    def loft(self, sections, profile, closed=True, cap0=True, cap1=True, mat=0, mats=None,
             cap_mat=None):
        """sections: (centre, U, V, su, sv[, profile]) ; profile: 2D CCW points."""
        rings = []
        for s in sections:
            c, U, V, su, sv = s[:5]
            prof = s[5] if len(s) > 5 else profile
            if su < 1e-7 and sv < 1e-7:
                rings.append([self.vert(c)])
            else:
                rings.append([self.vert(c + U * (px * su) + V * (py * sv)) for px, py in prof])
        return self.bridge(rings, closed, cap0, cap1, mat, mats, cap_mat)

    def tube(self, pts, ru, rv=None, ref=Vector((0, -1, 0)), profile=None, sides=8,
             closed=True, cap0=True, cap1=True, mat=0, mats=None, cap_mat=None):
        pts = [Vector(p) for p in pts]
        rv = ru if rv is None else rv
        prof = profile or circle(sides)
        frames = path_frames(pts, ref)
        secs = []
        for i, p in enumerate(pts):
            U, V = frames[i]
            a = ru[i] if isinstance(ru, (list, tuple)) else ru
            b = rv[i] if isinstance(rv, (list, tuple)) else rv
            secs.append((p, U, V, a, b))
        return self.loft(secs, prof, closed, cap0, cap1, mat, mats, cap_mat)

    def merge(self, other, mat_offset=0):
        off = len(self.v)
        self.v.extend(other.v)
        for f, m in zip(other.f, other.m):
            self.f.append(tuple(i + off for i in f))
            self.m.append(m + mat_offset)

    def build(self, name, mat_names, smooth_angle=None, coll=None):
        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(v) for v in self.v], [], self.f)
        me.validate(clean_customdata=False)
        me.update()
        for mn in mat_names:
            me.materials.append(MATS[mn])
        if len(me.polygons) == len(self.m):
            me.polygons.foreach_set("material_index", self.m)
        if smooth_angle is not None:
            me.shade_smooth()
            me.set_sharp_from_angle(angle=math.radians(smooth_angle))
        else:
            me.shade_flat()
        ob = bpy.data.objects.new(name, me)
        (coll or CHAR_COLL).objects.link(ob)
        return ob


def path_frames(pts, ref):
    """Return (U, V) per point. V ~ ref projected off the tangent, U = V x T,
    so U x V = T and CCW profiles give outward normals."""
    n = len(pts)
    out = []
    for i in range(n):
        if i == 0:
            T = pts[1] - pts[0]
        elif i == n - 1:
            T = pts[-1] - pts[-2]
        else:
            T = pts[i + 1] - pts[i - 1]
        T.normalize()
        r = ref(i) if callable(ref) else ref
        r = Vector(r)
        V = r - T * r.dot(T)
        if V.length < 1e-4:
            axis = min((Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))),
                       key=lambda a: abs(a.dot(T)))
            V = axis - T * axis.dot(T)
        V.normalize()
        U = V.cross(T).normalized()
        out.append((U, V))
    return out


def solidify(ob, thick, offset=-1.0, mat_offset=0, rim_offset=0):
    mod = ob.modifiers.new("Solidify", "SOLIDIFY")
    mod.thickness = thick
    mod.offset = offset
    mod.material_offset = mat_offset
    mod.material_offset_rim = rim_offset
    mod.use_even_offset = True
    return mod


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


# --------------------------------------------------------------------------
# Proportions
# --------------------------------------------------------------------------
R = 0.128                          # head (cranium) radius
HC = Vector((0.0, 0.0, 1.462))     # head centre
SHOULDER_Z = 1.235

# ==========================================================================
# Materials
# ==========================================================================
face_png = paint_face_texture(os.path.join(TEX_DIR, "rudeus_face.png"))
face_img = bpy.data.images.load(face_png)
face_img.name = "rudeus_face"
make_mat("Skin_Face", PALETTE["skin"], rough=0.7, spec=0.25, image=face_img)
make_mat("Skin", PALETTE["skin"], rough=0.7, spec=0.25)
make_mat("Hair", PALETTE["hair"], rough=0.6, spec=0.4)
make_mat("Hair_Light", PALETTE["hair_hi"], rough=0.6, spec=0.4)
make_mat("Robe", PALETTE["robe"], rough=0.9, spec=0.2)
make_mat("Robe_Lining", PALETTE["robe_in"], rough=0.9, spec=0.2)
make_mat("Robe_Trim", PALETTE["robe_trim"], rough=0.85, spec=0.2)
make_mat("Shirt", PALETTE["shirt"], rough=0.85, spec=0.2)
make_mat("Pants", PALETTE["pants"], rough=0.9, spec=0.2)
make_mat("Boots", PALETTE["boot"], rough=0.55, spec=0.4)
make_mat("Sole", PALETTE["sole"], rough=0.8)
make_mat("Belt", PALETTE["belt"], rough=0.6, spec=0.4)
make_mat("Gold", PALETTE["gold"], rough=0.35, metallic=1.0)
make_mat("Wood", PALETTE["wood"], rough=0.7, spec=0.3)
make_mat("Wood_Dark", PALETTE["wood_dark"], rough=0.7, spec=0.3)
make_mat("Crystal", PALETTE["crystal"], rough=0.08, emit=0.9, spec=0.8)
make_mat("Boot_Cuff", PALETTE["boot_cuff"], rough=0.6, spec=0.35)
make_mat("Stone", PALETTE["stone"], rough=0.9)
make_mat("Stone_Dark", PALETTE["stone_dark"], rough=0.9)
make_mat("Grass", PALETTE["grass"], rough=0.9)


# ==========================================================================
# Head
# ==========================================================================
def head_ring(z0, w, f, b, cy, n=16, zf=None, zb=None):
    """Ring around Z (CCW from above). Front (-Y) half uses depth f, back uses b.
    zf/zb tilt the ring (front z / back z)."""
    zf = z0 if zf is None else zf
    zb = z0 if zb is None else zb
    pts = []
    for j in range(n):
        th = 2 * math.pi * j / n
        c, s = math.cos(th), math.sin(th)   # s>0 -> back (+Y)
        x = w * c
        y = cy + (b * s if s > 0 else f * s)
        frontness = -s
        z = (zf + zb) * 0.5 + (zf - zb) * 0.5 * frontness
        pts.append(Vector((x, y, z)))
    return pts


def build_head():
    mb = MB()
    # (z, w, f, b, cy, zf, zb) in head units, bottom to top
    rings_def = [
        (None, 0.30, 0.62, 0.30, -0.08, -1.08, -0.70),
        (None, 0.56, 0.76, 0.46, -0.05, -0.86, -0.60),
        (-0.55, 0.82, 0.86, 0.74, -0.02, None, None),
        (-0.28, 0.93, 0.91, 0.92, 0.00, None, None),
        (0.02, 0.98, 0.93, 1.00, 0.02, None, None),
        (0.36, 0.94, 0.88, 0.96, 0.03, None, None),
        (0.66, 0.78, 0.70, 0.82, 0.04, None, None),
        (0.89, 0.48, 0.42, 0.52, 0.05, None, None),
    ]
    rings = [[mb.vert(HC + Vector((0, -0.60, -1.23)) * R)]]   # chin pole
    for z0, w, f, b, cy, zf, zb in rings_def:
        if z0 is None:
            z0 = (zf + zb) * 0.5
        pts = head_ring(z0, w, f, b, cy, zf=zf, zb=zb)
        rings.append([mb.vert(HC + p * R) for p in pts])
    rings.append([mb.vert(HC + Vector((0, 0.05, 1.0)) * R)])  # crown pole
    mb.bridge(rings)

    # slight nose: pull the front-centre vertex on the cheek ring forward
    front_j = 12
    nose_v = rings[3][front_j]
    mb.v[nose_v] += Vector((0, -0.05, 0.0)) * R

    ob = mb.build("Head", ["Skin_Face"], smooth_angle=40)

    # front projection UVs for the face texture
    me = ob.data
    uv = me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        front = poly.center.y < HC.y - 0.15 * R
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            if front:
                u = ((co.x - HC.x) / R - FACE_X0) / (FACE_X1 - FACE_X0)
                v = ((co.z - HC.z) / R - FACE_Z0) / (FACE_Z1 - FACE_Z0)
            else:
                u, v = 0.02, 0.98   # plain skin corner of the texture
            uv.data[li].uv = (u, v)
    return ob


def build_ears(mb):
    for sx in (-1, 1):
        base = HC + Vector((sx * 0.90 * R, 0.10 * R, -0.30 * R))
        pts = [base,
               base + Vector((sx * 0.12 * R, 0.08 * R, 0.22 * R)),
               base + Vector((sx * 0.14 * R, 0.14 * R, 0.42 * R))]
        mb.tube(pts, [0.10 * R, 0.13 * R, 0.0], [0.06 * R, 0.07 * R, 0.0],
                ref=Vector((sx, 0, 0)), sides=6)


# ==========================================================================
# Hair
# ==========================================================================
HAIR_C = HC + Vector((0.0, 0.012, 0.03))
HAIR_R = 1.06 * R


def sph(az, el):
    az, el = math.radians(az), math.radians(el)
    return Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))


def slerp(a, b, t):
    a = a.normalized()
    b = b.normalized()
    d = max(-1.0, min(1.0, a.dot(b)))
    om = math.acos(d)
    if om < 1e-5:
        return a.copy()
    so = math.sin(om)
    return (a * math.sin((1 - t) * om) + b * math.sin(t * om)) / so


HAIR_PROFILE = [(1, 0), (0.45, 0.8), (-0.45, 0.8), (-1, 0), (-0.45, -0.4), (0.45, -0.4)]
WHORL = (178, 66)     # the crown whorl every clump fans out from (top-back of the head)


def hair_strand(mb, root, tip, width, thick=0.024, bulge=0.10, flick=0.0, segs=9, mat=0,
                twist=0.0):
    """A hair clump that follows the scalp along a great circle from `root` (az, el)
    to `tip` (az, el): narrow at the whorl, widest over the crown, sharp at the tip.
    bulge lifts the middle off the scalp (volume), flick pushes the tip outward."""
    d0, d1 = sph(*root), sph(*tip)
    pts, normals = [], []
    for i in range(segs + 1):
        t = i / segs
        d = slerp(d0, d1, t)
        r = HAIR_R * (1.0 + bulge * math.sin(math.pi * t) ** 0.8 + flick * t ** 2.5)
        pts.append(HAIR_C + d * r)
        normals.append(d)
    frames = path_frames(pts, lambda i: normals[i])
    secs = []
    for i, p in enumerate(pts):
        t = i / segs
        w = width * (0.30 + 0.70 * min(1.0, t / 0.35) ** 0.7) * (1.0 - t) ** 0.75
        th = thick * (0.55 + 0.45 * min(1.0, t / 0.3)) * (1.0 - t ** 1.3)
        U, V = frames[i]
        if twist:
            a = twist * t
            U, V = U * math.cos(a) + V * math.sin(a), V * math.cos(a) - U * math.sin(a)
        if i == segs:
            w = th = 0.0
        secs.append((p, U, V, w, th))
    mb.loft(secs, HAIR_PROFILE, mat=mat)


def build_hair():
    mb = MB()
    # --- scalp cap (hidden under the clumps, closes any gaps) -------------
    segs, rings_n = 16, 10
    rings = [[mb.vert(HAIR_C + Vector((0, 0.03 * R, HAIR_R * 0.99)))]]
    for k in range(1, rings_n):
        el = 90 - 180 * k / rings_n
        ring = []
        for j in range(segs):
            az = 360 * j / segs
            d = sph(az, el)
            d.y *= 1.04
            ring.append(mb.vert(HAIR_C + d * HAIR_R * 0.985))
        rings.append(ring)
    # sph() azimuth runs CCW seen from above, so travelling bottom -> top
    # gives outward normals
    rings = rings[::-1]
    keep_f, keep_m = [], []
    start = len(mb.f)
    mb.bridge(rings, cap0=False, cap1=False)

    def hairline(az):
        c = (1 + math.cos(math.radians(az))) * 0.5     # 1 front, 0 back
        return -48 + 78 * c ** 1.4

    for fi in range(start, len(mb.f)):
        f = mb.f[fi]
        cen = sum((mb.v[i] for i in f), Vector()) / len(f)
        d = (cen - HAIR_C).normalized()
        el = math.degrees(math.asin(max(-1, min(1, d.z))))
        az = math.degrees(math.atan2(d.x, -d.y))
        if el > hairline(az):
            keep_f.append(f)
            keep_m.append(0)
    mb.f = mb.f[:start] + keep_f
    mb.m = mb.m[:start] + keep_m

    W = R
    # (tip az, tip el, width, flick, bulge) -- every clump starts near the whorl
    bangs = [
        (-5, -33, 0.56, 0.05, 0.12),     # long lock between the eyes
        (10, -20, 0.50, 0.06, 0.12),
        (25, -30, 0.54, 0.05, 0.12),
        (-21, -24, 0.52, 0.06, 0.12),
        (39, -22, 0.50, 0.07, 0.11),
        (-37, -30, 0.52, 0.06, 0.11),
        (53, -36, 0.48, 0.08, 0.10),
        (-53, -36, 0.48, 0.08, 0.10),
    ]
    sides = [
        (68, -52, 0.54, 0.14, 0.11), (-68, -50, 0.54, 0.14, 0.11),
        (86, -62, 0.54, 0.18, 0.11), (-86, -60, 0.54, 0.18, 0.11),
        (104, -52, 0.54, 0.26, 0.12), (-104, -54, 0.54, 0.26, 0.12),
    ]
    back = [
        (120, -50, 0.50, 0.34, 0.12), (-120, -52, 0.50, 0.34, 0.12),
        (136, -62, 0.50, 0.40, 0.13), (-136, -60, 0.50, 0.40, 0.13),
        (152, -56, 0.50, 0.44, 0.14), (-152, -58, 0.50, 0.44, 0.14),
        (167, -68, 0.50, 0.40, 0.13), (-167, -66, 0.50, 0.40, 0.13),
        (180, -60, 0.52, 0.46, 0.14),
    ]
    # short layered clumps for a tousled silhouette
    top = [
        (40, 26, 0.58, 0.16, 0.18), (-40, 28, 0.58, 0.16, 0.18),
        (98, 12, 0.56, 0.22, 0.16), (-98, 10, 0.56, 0.22, 0.16),
        (135, 0, 0.56, 0.26, 0.16), (-135, 2, 0.56, 0.26, 0.16),
        (5, 40, 0.62, 0.14, 0.19),
    ]

    def root_near_whorl():
        return (WHORL[0] + random.uniform(-14, 14), WHORL[1] + random.uniform(-6, 6))

    for (az, el, w, fl, bu) in back:
        hair_strand(mb, root_near_whorl(), (az, el), w * W, thick=0.026, flick=fl, bulge=bu,
                    segs=7, mat=random.choice((0, 0, 1)))
    for (az, el, w, fl, bu) in sides:
        hair_strand(mb, root_near_whorl(), (az, el), w * W, thick=0.026, flick=fl, bulge=bu,
                    segs=9, mat=random.choice((0, 1)))
    for (az, el, w, fl, bu) in bangs:
        hair_strand(mb, root_near_whorl(), (az, el), w * W, thick=0.024, flick=fl, bulge=bu,
                    segs=10, mat=random.choice((0, 1)))
    for (az, el, w, fl, bu) in top:
        hair_strand(mb, root_near_whorl(), (az, el), w * W, thick=0.030, flick=fl, bulge=bu,
                    segs=7, mat=1)
    return mb.build("Hair", ["Hair", "Hair_Light"])


# ==========================================================================
# Body
# ==========================================================================
REF_FWD = Vector((0, -1, 0))

L_SHOULDER = Vector((0.160, 0.010, 1.205))
L_ELBOW = Vector((0.212, 0.030, 0.985))
L_WRIST = Vector((0.232, 0.000, 0.785))

R_SHOULDER = Vector((-0.160, 0.010, 1.205))
R_ELBOW = Vector((-0.232, 0.050, 1.000))
STAFF_XY = Vector((-0.300, -0.150, 0.0))
GRIP_Z = 0.905
R_WRIST = Vector((-0.282, -0.090, 0.915))

L_HIP = Vector((0.082, 0.0, 0.80))
L_KNEE = Vector((0.092, -0.012, 0.45))
L_ANKLE = Vector((0.098, 0.005, 0.10))


def build_skin_parts():
    mb = MB()
    # neck
    mb.tube([(0, 0.012, 1.245), (0, 0.016, 1.32), (0, 0.022, HC.z - 0.30 * R)],
            0.040, 0.037, sides=8)
    build_ears(mb)

    # left hand (relaxed, palm toward the thigh)
    w = L_WRIST
    pts = [w + Vector((0.0, 0.002, 0.02)), w + Vector((0.004, -0.004, -0.035)),
           w + Vector((0.006, -0.010, -0.080)), w + Vector((0.002, -0.020, -0.118)),
           w + Vector((-0.008, -0.028, -0.140))]
    mb.tube(pts, [0.020, 0.022, 0.021, 0.017, 0.0], [0.028, 0.040, 0.040, 0.034, 0.0],
            ref=REF_FWD, sides=8)
    thumb = [w + Vector((-0.004, -0.024, -0.030)), w + Vector((-0.012, -0.040, -0.062)),
             w + Vector((-0.018, -0.044, -0.088))]
    mb.tube(thumb, [0.012, 0.010, 0.0], [0.012, 0.010, 0.0], ref=Vector((1, 0, 0)), sides=6)

    # right hand gripping the staff: a fist wrapped around the shaft
    c = Vector((STAFF_XY.x, STAFF_XY.y, GRIP_Z))
    fist_prof = [(1, -0.2), (0.95, 0.55), (0.55, 1.0), (-0.4, 1.0), (-0.95, 0.6),
                 (-1.0, -0.3), (-0.6, -1.0), (0.6, -1.0)]
    off = Vector((0.004, 0.010, 0))
    secs = []
    for dz, s in ((-0.040, 0.85), (-0.025, 1.0), (0.020, 1.0), (0.038, 0.88)):
        secs.append((c + off + Vector((0, 0, dz)), Vector((-1, 0, 0)), Vector((0, -1, 0)),
                     0.030 * s, 0.032 * s))
    # loft runs upward, U=-X, V=-Y -> U x V = +Z
    mb.loft(secs, fist_prof)
    # back of hand / wrist joint
    mb.tube([R_WRIST + Vector((0.0, 0.01, 0.0)), c + off + Vector((0.006, 0.026, 0.004))],
            [0.024, 0.028], [0.020, 0.024], ref=Vector((0, 0, 1)), sides=8)
    # thumb over the front of the grip
    mb.tube([c + Vector((0.020, -0.020, 0.030)), c + Vector((0.006, -0.036, 0.034)),
             c + Vector((-0.016, -0.034, 0.026))], [0.011, 0.010, 0.0], [0.011, 0.010, 0.0],
            ref=Vector((0, 0, 1)), sides=6)
    return mb.build("Skin", ["Skin"], smooth_angle=50)


def build_outfit():
    mb = MB()
    # material slots
    M_SHIRT, M_PANTS, M_BOOT, M_SOLE, M_BELT, M_GOLD, M_CUFF = range(7)

    # ---- torso (shirt) ----
    secs = []
    for z, rx, ry, cy in ((0.86, 0.120, 0.084, 0.0), (0.95, 0.118, 0.084, 0.0),
                          (1.08, 0.134, 0.090, 0.0), (1.19, 0.148, 0.084, 0.006),
                          (1.250, 0.122, 0.072, 0.010), (1.300, 0.048, 0.044, 0.012)):
        secs.append((Vector((0, cy, z)), Vector((-1, 0, 0)), Vector((0, -1, 0)), rx, ry))
    mb.loft(secs, circle(12), mat=M_SHIRT)

    # shirt collar (stand collar, open at the front)
    col = []
    for z, s in ((1.262, 1.0), (1.308, 1.05)):
        col.append((Vector((0, 0.010, z)), Vector((-1, 0, 0)), Vector((0, -1, 0)),
                    0.050 * s, 0.050 * s,
                    arc(9, math.radians(90 + 28), math.radians(90 + 360 - 28))))
    collar_mb = MB()
    collar_mb.loft(col, None, closed=False)

    # ---- pelvis + legs (pants) ----
    secs = []
    for z, rx, ry in ((0.985, 0.122, 0.088), (0.87, 0.138, 0.095), (0.78, 0.130, 0.090),
                      (0.715, 0.060, 0.055)):
        secs.append((Vector((0, 0, z)), Vector((1, 0, 0)), Vector((0, -1, 0)), rx, ry))
    # loft goes downward: U=+X, V=-Y -> U x V = -Z  (travel direction)
    mb.loft(secs, circle(12), mat=M_PANTS)
    for sx in (-1, 1):
        hip = Vector((sx * L_HIP.x, L_HIP.y, L_HIP.z))
        knee = Vector((sx * L_KNEE.x, L_KNEE.y, L_KNEE.z))
        ank = Vector((sx * L_ANKLE.x, L_ANKLE.y, L_ANKLE.z))
        low = knee.lerp(ank, 0.62)
        pts = [hip + Vector((0, 0, 0.06)), hip.lerp(knee, 0.5), knee, knee.lerp(ank, 0.35), low]
        mb.tube(pts, [0.070, 0.063, 0.054, 0.049, 0.040], ref=REF_FWD, sides=8, mat=M_PANTS)

        # ---- boots ----
        bx = sx * (L_ANKLE.x + 0.004)
        shaft = [Vector((bx, 0.000, 0.300)), Vector((bx, 0.001, 0.262)),
                 Vector((bx, 0.004, 0.17)), Vector((bx, 0.012, 0.075))]
        mb.tube(shaft, [0.066, 0.063, 0.057, 0.052], ref=REF_FWD, sides=8, mat=M_BOOT,
                profile=circle(8, math.pi / 8))
        # foot: travels toward the toe (-Y, rotated outward a little)
        rot = math.radians(7 * sx)
        fwd = Vector((math.sin(rot), -math.cos(rot), 0))
        side = Vector((math.cos(rot), math.sin(rot), 0))
        base = Vector((bx, 0.0, 0.0))
        foot_prof = [(1, -1), (1, 0.3), (0.6, 0.95), (-0.6, 0.95), (-1, 0.3), (-1, -1)]
        secs = []
        for along, w, h in ((0.060, 0.042, 0.050), (0.020, 0.050, 0.060), (-0.050, 0.054, 0.045),
                            (-0.110, 0.048, 0.034), (-0.145, 0.030, 0.024)):
            cen = base + fwd * (-along) + Vector((0, 0, 0.016 + h))
            # U x V must equal the travel direction: side x Z = fwd
            secs.append((cen, side, Vector((0, 0, 1)), w, h))
        mb.loft(secs, foot_prof, mat=M_BOOT)
        # sole
        secs = []
        for along, w in ((0.068, 0.044), (0.0, 0.052), (-0.11, 0.050), (-0.152, 0.032)):
            cen = base + fwd * (-along) + Vector((0, 0, 0.009))
            secs.append((cen, side, Vector((0, 0, 1)), w + 0.004, 0.009))
        mb.loft(secs, [(1, -1), (1, 1), (-1, 1), (-1, -1)], mat=M_SOLE)
        # turned-down cuff
        cuff = [Vector((bx, 0.000, 0.322)), Vector((bx, 0.001, 0.300)), Vector((bx, 0.001, 0.268))]
        mb.tube(cuff, [0.070, 0.074, 0.071], ref=REF_FWD, sides=8, mat=M_CUFF, cap0=False,
                profile=circle(8, math.pi / 8))
        # buckle strap around the ankle
        mb.tube([Vector((bx, 0.008, 0.125)), Vector((bx, 0.009, 0.103))], 0.056, ref=REF_FWD,
                sides=8, mat=M_SOLE, cap0=False, cap1=False, profile=circle(8, math.pi / 8))

    # ---- shirt buttons ----
    for z in (1.205, 1.130, 1.055, 0.975):
        fy = -0.088 + 0.010 * max(0.0, z - 1.10) / 0.1
        b = Vector((0, fy, z))
        mb.tube([b + Vector((0, 0.004, 0)), b + Vector((0, -0.003, 0))], 0.0075,
                ref=Vector((0, 0, 1)), sides=6, mat=M_BELT)

    # ---- belt + buckle ----
    secs = []
    for z in (0.918, 0.880):
        secs.append((Vector((0, 0, z)), Vector((1, 0, 0)), Vector((0, -1, 0)), 0.130, 0.094))
    mb.loft(secs, circle(12), mat=M_BELT, cap0=False, cap1=False)
    bc = Vector((0, -0.096, 0.899))
    mb.tube([bc + Vector((0, 0.004, 0)), bc + Vector((0, -0.008, 0))], 0.022, 0.018,
            ref=Vector((0, 0, 1)), profile=[(1, 1), (-1, 1), (-1, -1), (1, -1)], mat=M_GOLD)

    ob = mb.build("Outfit", ["Shirt", "Pants", "Boots", "Sole", "Belt", "Gold", "Boot_Cuff"])
    collar = collar_mb.build("Collar", ["Shirt"])
    solidify(collar, 0.008, offset=1.0)
    return [ob, collar]


def build_robe():
    """Long open-front robe with hood and wide sleeves (Rudeus' grey robe)."""
    objs = []
    # ---- body of the robe: open profile loft, travelling downward ----
    mb = MB()
    # z, rx, ry, cy, gap(deg)
    defs = [
        (1.318, 0.060, 0.058, 0.014, 70),
        (1.272, 0.150, 0.090, 0.012, 46),
        (1.225, 0.205, 0.108, 0.010, 40),
        (1.130, 0.178, 0.116, 0.004, 36),
        (0.980, 0.160, 0.112, 0.004, 40),
        (0.840, 0.186, 0.130, 0.006, 52),
        (0.640, 0.218, 0.158, 0.010, 62),
        (0.460, 0.246, 0.186, 0.014, 72),
        (0.374, 0.257, 0.196, 0.015, 76),
        (0.340, 0.262, 0.200, 0.016, 78),
    ]
    secs = []
    n = 17
    edge = math.radians(10)          # width of the dark trim along the front edges
    for i, (z, rx, ry, cy, gap) in enumerate(defs):
        g = math.radians(gap) * 0.5
        a0, a1 = math.pi / 2 + g, math.pi / 2 + 2 * math.pi - g
        angs = [a0] + [a0 + edge + (a1 - a0 - 2 * edge) * k / (n - 3) for k in range(n - 2)] + [a1]
        prof = [(math.cos(a), math.sin(a)) for a in angs]
        secs.append((Vector((0, cy, z)), Vector((1, 0, 0)), Vector((0, -1, 0)), rx, ry, prof))
    rings = mb.loft(secs, None, closed=False)
    # trim: front edge columns + hem band
    for i in range(len(rings) - 1):
        for j in range(n - 1):
            if j in (0, n - 2) or i == len(rings) - 2:
                mb.m[i * (n - 1) + j] = 2
    # cloth folds on the lower skirt: push alternating columns in/out
    for ri in range(5, len(rings)):
        amt = min(1.0, (ri - 4) / (len(rings) - 6))
        for j, vi in enumerate(rings[ri]):
            if 1 < j < n - 2:
                v = mb.v[vi]
                radial = Vector((v.x, v.y - defs[ri][3], 0)).normalized()
                mb.v[vi] = v + radial * (0.012 * amt * (1 if j % 2 else -0.6))
    # uneven hem (move the trim ring with it so the band keeps its height)
    for j in range(n):
        dz = 0.012 * math.sin(j * 1.7)
        mb.v[rings[-1][j]].z += dz
        mb.v[rings[-2][j]].z += dz
    robe = mb.build("Robe", ["Robe", "Robe_Lining", "Robe_Trim"])
    solidify(robe, 0.012, offset=-1.0, mat_offset=1, rim_offset=2)
    objs.append(robe)

    # ---- sleeves ----
    mb = MB()
    for side in (1, -1):
        if side == 1:
            sh, el, wr = L_SHOULDER, L_ELBOW, L_WRIST
        else:
            sh, el, wr = R_SHOULDER, R_ELBOW, R_WRIST
        cuff_dir = (wr - el).normalized()
        pts = [sh + Vector((side * -0.03, 0, 0.03)), sh, sh.lerp(el, 0.5), el,
               el.lerp(wr, 0.55), wr - cuff_dir * 0.035, wr + cuff_dir * 0.010]
        ru = [0.050, 0.062, 0.058, 0.056, 0.058, 0.066, 0.072]
        ref = Vector((side, 0, 0)) if side == 1 else Vector((0, 0, 1))
        mb.tube(pts, ru, sides=8, ref=ref, cap1=False, cap0=True,
                mats=[0, 0, 0, 0, 0, 2])
    sleeves = mb.build("Sleeves", ["Robe", "Robe_Lining", "Robe_Trim"])
    solidify(sleeves, 0.010, offset=-1.0, mat_offset=1, rim_offset=2)
    objs.append(sleeves)

    # ---- hood (lowered, bunched behind the neck) ----
    mb = MB()
    # collar roll from right collarbone, around the back, to the left collarbone
    roll = []
    for k in range(9):
        a = math.radians(-160 + 320 * k / 8)        # 0 = back
        roll.append(Vector((math.sin(a) * 0.090, 0.016 + math.cos(a) * 0.082,
                            1.300 + 0.018 * math.cos(a))))
    rr = [0.020 + 0.016 * math.cos(math.radians(-160 + 320 * k / 8)) ** 2 for k in range(9)]
    rr[0] = rr[-1] = 0.012
    mb.tube(roll, rr, ref=Vector((0, 0, 1)), sides=6)
    # hood sack hanging down the back
    hc = Vector((0, 0.125, 1.205))
    secs = []
    for dz, rx, ry, dy in ((0.10, 0.06, 0.03, -0.035), (0.075, 0.120, 0.050, -0.02),
                           (0.02, 0.135, 0.058, 0.0), (-0.05, 0.110, 0.048, 0.004),
                           (-0.110, 0.050, 0.026, 0.0), (-0.135, 0.0, 0.0, 0.0)):
        secs.append((hc + Vector((0, dy, dz)), Vector((1, 0, 0)), Vector((0, -1, 0)), rx, ry))
    mb.loft(secs, circle(10))
    hood = mb.build("Hood", ["Robe"])
    objs.append(hood)
    return objs


# ==========================================================================
# Aqua Heartia (staff)
# ==========================================================================
def build_staff():
    mb = MB()
    M_WOOD, M_DARK, M_GOLD, M_CRYSTAL = range(4)
    base = Vector((STAFF_XY.x, STAFF_XY.y, 0.0))
    top = 1.38
    pts = [base + Vector((0, 0, z)) for z in (0.0, 0.03, 0.45, 0.85, 1.20, top)]
    rr = [0.014, 0.016, 0.017, 0.018, 0.019, 0.023]
    for i in range(2, 5):   # slight hand-carved wobble
        pts[i] += Vector((random.uniform(-0.004, 0.004), random.uniform(-0.004, 0.004), 0))
    mb.tube(pts, rr, sides=6, ref=REF_FWD, mat=M_WOOD)
    # iron ferrule at the foot
    mb.tube([base + Vector((0, 0, -0.002)), base + Vector((0, 0, 0.05))], 0.019, sides=6,
            ref=REF_FWD, mat=M_DARK)
    # leather wrap at the grip
    mb.tube([base + Vector((0, 0, GRIP_Z - 0.07)), base + Vector((0, 0, GRIP_Z + 0.07))],
            0.020, sides=6, ref=REF_FWD, mat=M_DARK)
    # gold collars
    mb.tube([base + Vector((0, 0, top - 0.035)), base + Vector((0, 0, top - 0.020)),
             base + Vector((0, 0, top + 0.004))],
            [0.026, 0.030, 0.034], sides=8, ref=REF_FWD, mat=M_GOLD)
    mb.tube([base + Vector((0, 0, top - 0.11)), base + Vector((0, 0, top - 0.095))],
            0.024, sides=8, ref=REF_FWD, mat=M_GOLD)
    cz = top + 0.135
    # three carved, twisting branches cradling the stone and curling over it
    for k in range(3):
        a0 = math.radians(30 + 120 * k)
        prong = []
        for t, r, z in ((0.00, 0.020, top - 0.005), (0.18, 0.050, top + 0.030),
                        (0.40, 0.074, top + 0.100), (0.62, 0.070, top + 0.180),
                        (0.80, 0.048, top + 0.240), (0.92, 0.022, top + 0.268),
                        (1.00, 0.004, top + 0.262)):
            a = a0 + math.radians(70) * t
            prong.append(base + Vector((math.cos(a) * r, math.sin(a) * r, z)))
        d = Vector((math.cos(a0), math.sin(a0), 0))
        mb.tube(prong, [0.016, 0.015, 0.013, 0.012, 0.010, 0.007, 0.0], sides=5,
                ref=lambda i, d=d: d, mat=M_WOOD)
    # the aqua magic stone: faceted gem
    crystal_mb = MB()
    c = base + Vector((0, 0, cz))
    secs = []
    for dz, r in ((-0.095, 0.0), (-0.050, 0.046), (0.0, 0.062), (0.050, 0.050),
                  (0.100, 0.0)):
        secs.append((c + Vector((0, 0, dz)), Vector((-1, 0, 0)), Vector((0, -1, 0)), r, r))
    crystal_mb.loft(secs, circle(8, 0.2), mat=0)
    mb.merge(crystal_mb, mat_offset=M_CRYSTAL)
    return mb.build("Aqua_Heartia", ["Wood", "Wood_Dark", "Gold", "Crystal"])


# ==========================================================================
# Environment: pedestal, lights, world, camera
# ==========================================================================
def build_pedestal():
    mb = MB()
    prof = circle(10, math.pi / 10)
    secs = []
    for z, r in ((-0.16, 0.60), (-0.10, 0.62), (-0.09, 0.56), (-0.012, 0.55), (0.0, 0.53)):
        secs.append((Vector((0, 0, z)), Vector((1, 0, 0)), Vector((0, 1, 0)), r, r))
    mb.loft(secs, prof, mats=[1, 1, 0, 0], mat=0)
    ob = mb.build("Pedestal", ["Stone", "Stone_Dark"], coll=ENV_COLL)
    # top grass disc
    g = MB()
    secs = [(Vector((0, 0, 0.0)), Vector((1, 0, 0)), Vector((0, 1, 0)), 0.535, 0.535),
            (Vector((0, 0, 0.012)), Vector((1, 0, 0)), Vector((0, 1, 0)), 0.50, 0.50)]
    g.loft(secs, circle(10, math.pi / 10), cap0=False)
    # little rocks and tufts
    for (x, y, s) in ((0.36, 0.18, 0.05), (-0.40, 0.22, 0.04), (0.30, -0.33, 0.035),
                      (-0.12, 0.40, 0.03)):
        c = Vector((x, y, 0.01))
        rs = [(c + Vector((0, 0, -0.01)), 0.0), (c + Vector((0, 0, s * 0.3)), s),
              (c + Vector((0, 0, s * 0.9)), s * 0.6), (c + Vector((0, 0, s * 1.1)), 0.0)]
        rock = MB()
        rock.tube([p for p, _ in rs], [r for _, r in rs], sides=5, ref=Vector((0, 1, 0)),
                  mat=0)
        for vi in range(len(rock.v)):
            rock.v[vi] += Vector((random.uniform(-0.006, 0.006),) * 2 + (0,))
        g.merge(rock, mat_offset=1)
    for (x, y) in ((0.42, -0.08), (-0.30, -0.36), (0.12, 0.44), (-0.46, 0.0), (0.25, 0.30)):
        for k in range(3):
            a = random.uniform(0, 2 * math.pi)
            b = Vector((x + 0.015 * math.cos(a), y + 0.015 * math.sin(a), 0.01))
            tip = b + Vector((0.03 * math.cos(a), 0.03 * math.sin(a), random.uniform(0.05, 0.08)))
            blade = MB()
            blade.tube([b, b.lerp(tip, 0.5), tip], [0.010, 0.007, 0.0], [0.004, 0.003, 0.0],
                       sides=4, ref=Vector((-math.sin(a), math.cos(a), 0)))
            g.merge(blade, mat_offset=0)
    grass = g.build("Grass", ["Grass", "Stone"], coll=ENV_COLL)
    return [ob, grass]


def setup_world():
    w = bpy.data.worlds.new("World")
    SCENE.world = w
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = hex_lin("D9DEE8")
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = hex_lin("8FA3C2")
    bg_cam = nt.nodes.new("ShaderNodeBackground")
    bg_amb = nt.nodes.new("ShaderNodeBackground")
    bg_amb.inputs["Color"].default_value = hex_lin("B8C4D8")
    bg_amb.inputs["Strength"].default_value = 0.55
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(tc.outputs["Window"], sep.inputs[0])
    nt.links.new(sep.outputs["Y"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg_cam.inputs["Color"])
    bg_cam.inputs["Strength"].default_value = 1.0
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
    nt.links.new(bg_amb.outputs[0], mix.inputs[1])
    nt.links.new(bg_cam.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])


def add_area(name, loc, target, energy, size, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy = energy
    ld.size = size
    ld.color = color
    ob = bpy.data.objects.new(name, ld)
    ENV_COLL.objects.link(ob)
    ob.location = loc
    d = Vector(target) - Vector(loc)
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return ob


def setup_lights():
    tgt = (0, 0, 0.9)
    add_area("Key", (-2.0, -2.6, 3.0), tgt, 430, 1.8, (1.0, 0.94, 0.86))
    add_area("Fill", (2.8, -2.0, 1.4), tgt, 120, 3.0, (0.86, 0.91, 1.0))
    # soft cyan glow from Aqua Heartia's stone
    ld = bpy.data.lights.new("Crystal_Glow", "POINT")
    ld.energy = 4.0
    ld.color = (0.45, 0.85, 1.0)
    ld.shadow_soft_size = 0.05
    ob = bpy.data.objects.new("Crystal_Glow", ld)
    ENV_COLL.objects.link(ob)
    ob.location = (STAFF_XY.x + 0.03, STAFF_XY.y - 0.09, 1.515)
    add_area("Rim", (1.0, 3.0, 2.6), tgt, 380, 1.4, (1.0, 0.97, 0.92))
    add_area("Rim2", (-1.6, 2.6, 1.8), tgt, 180, 1.4, (0.85, 0.92, 1.0))


def setup_camera():
    cd = bpy.data.cameras.new("Camera")
    cd.lens = 85
    cam = bpy.data.objects.new("Camera", cd)
    ENV_COLL.objects.link(cam)
    SCENE.camera = cam
    return cam


def aim_camera(cam, az_deg, el_deg, dist, target):
    az, el = math.radians(az_deg), math.radians(el_deg)
    t = Vector(target)
    loc = t + Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el),
                      math.sin(el))) * dist
    cam.location = loc
    cam.rotation_euler = (t - loc).to_track_quat("-Z", "Y").to_euler()


def setup_render():
    r = SCENE.render
    r.engine = "CYCLES"
    SCENE.cycles.device = "CPU"
    SCENE.cycles.samples = 24 if QUICK else 160
    SCENE.cycles.use_denoising = True
    try:
        SCENE.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    SCENE.cycles.max_bounces = 6
    SCENE.view_settings.exposure = -0.35
    r.resolution_x = 540 if QUICK else 1200
    r.resolution_y = 720 if QUICK else 1600
    r.resolution_percentage = 100
    r.film_transparent = False
    try:
        SCENE.view_settings.view_transform = "AgX"
        SCENE.view_settings.look = "AgX - Punchy"
    except Exception:
        try:
            SCENE.view_settings.look = "Punchy"
        except Exception:
            pass


# ==========================================================================
# Build everything
# ==========================================================================
head = build_head()
hair = build_hair()
skin = build_skin_parts()
outfit = build_outfit()
robe = build_robe()
staff = build_staff()
env = build_pedestal()


def apply_modifiers(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    if not ob.modifiers:
        return
    ev = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    me.name = old.name
    bpy.data.meshes.remove(old)


char_objs = [head, hair, skin] + outfit + robe + [staff]
for ob in char_objs:
    apply_modifiers(ob)

# Join clothing pieces so the outliner stays tidy: Body / Hair / Clothes / Staff
def join(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active
    o.name = name
    o.data.name = name
    return o


body = join([head, skin], "Rudeus_Body")
clothes = join(outfit + robe, "Rudeus_Clothes")
hair.name = "Rudeus_Hair"
hair.data.name = "Rudeus_Hair"

root = bpy.data.objects.new("Rudeus_Greyrat", None)
CHAR_COLL.objects.link(root)
root.empty_display_type = "PLAIN_AXES"
root.empty_display_size = 0.3
for o in (body, clothes, hair, staff):
    o.parent = root

setup_world()
setup_lights()
cam = setup_camera()
setup_render()

# stats
tri = 0
for o in (body, clothes, hair, staff):
    for p in o.data.polygons:
        tri += len(p.vertices) - 2
print(f"[rudeus] character triangles: {tri}")

# --------------------------------------------------------------------------
# Save / export
# --------------------------------------------------------------------------
blend_path = os.path.join(MODEL_DIR, "rudeus_lowpoly.blend")
face_img.pack()
aim_camera(cam, -28, 8, 4.7, (0, 0, 0.80))
bpy.context.preferences.filepaths.save_version = 0     # no .blend1 backups
bpy.ops.wm.save_as_mainfile(filepath=blend_path, compress=True)

bpy.ops.object.select_all(action="DESELECT")
for o in (root, body, clothes, hair, staff):
    o.select_set(True)
bpy.context.view_layer.objects.active = root

bpy.ops.export_scene.gltf(filepath=os.path.join(MODEL_DIR, "rudeus_lowpoly.glb"),
                          export_format="GLB", use_selection=True, export_apply=True)
try:
    bpy.ops.export_scene.fbx(filepath=os.path.join(MODEL_DIR, "rudeus_lowpoly.fbx"),
                             use_selection=True, path_mode="COPY", embed_textures=True,
                             apply_scale_options="FBX_SCALE_ALL")
except Exception as e:   # pragma: no cover
    print("[rudeus] FBX export failed:", e)
try:
    bpy.ops.wm.obj_export(filepath=os.path.join(MODEL_DIR, "rudeus_lowpoly.obj"),
                          export_selected_objects=True, export_materials=True,
                          path_mode="RELATIVE", forward_axis="NEGATIVE_Z", up_axis="Y")
except Exception as e:   # pragma: no cover
    print("[rudeus] OBJ export failed:", e)

# --------------------------------------------------------------------------
# Renders
# --------------------------------------------------------------------------
VIEWS = {
    "front": (0, 6, 4.7, (0, 0, 0.80), 85),
    "three_quarter": (-32, 9, 4.7, (0, 0, 0.80), 85),
    "side": (-90, 6, 4.7, (0, 0, 0.80), 85),
    "back": (160, 10, 4.7, (0, 0, 0.80), 85),
    "three_quarter_left": (35, 8, 4.7, (0, 0, 0.80), 85),
    "portrait": (-18, 4, 1.55, (-0.03, 0, 1.40), 85),
}

# close-ups only rendered when asked for with --views
EXTRA_VIEWS = {
    "head_back": (145, 18, 1.5, (0, 0.02, 1.43), 85),
    "head_side": (-90, 4, 1.5, (0, 0.0, 1.43), 85),
    "head_top": (-20, 45, 1.5, (0, 0.0, 1.45), 85),
}

if DO_RENDER:
    views = dict(VIEWS)
    if ONLY_VIEWS:
        views.update(EXTRA_VIEWS)
    for name, (az, el, dist, tgt, lens) in views.items():
        if ONLY_VIEWS and name not in ONLY_VIEWS:
            continue
        cam.data.lens = lens
        aim_camera(cam, az, el, dist, tgt)
        SCENE.render.filepath = os.path.join(RENDER_DIR, f"rudeus_{name}.png")
        bpy.ops.render.render(write_still=True)
        print("[rudeus] rendered", name)

if DO_TURNTABLE:
    from PIL import Image

    frames = []
    r = SCENE.render
    r.resolution_x, r.resolution_y = (300, 400) if QUICK else (480, 640)
    SCENE.cycles.samples = 16 if QUICK else 48
    cam.data.lens = 85
    tmp = os.path.join(RENDER_DIR, "_turntable_frame.png")
    n = 36
    for i in range(n):
        aim_camera(cam, -360.0 * i / n, 8, 4.7, (0, 0, 0.80))
        r.filepath = tmp
        bpy.ops.render.render(write_still=True)
        frames.append(Image.open(tmp).convert("RGB").copy())
    os.remove(tmp)
    pal = [f.quantize(colors=200, method=Image.MEDIANCUT) for f in frames]
    pal[0].save(os.path.join(RENDER_DIR, "rudeus_turntable.gif"), save_all=True,
                append_images=pal[1:], duration=80, loop=0, optimize=True)
    print("[rudeus] rendered turntable")
