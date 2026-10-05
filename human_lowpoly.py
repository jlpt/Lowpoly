"""
Low-poly human character - procedural Blender build script.

A stylised adult in a T-shirt, jeans and sneakers, built entirely from code with
`bpy`. Nothing here is made of boxes: the body is a single continuous, watertight
mesh lofted through anatomical cross-sections (chest, waist, hips, calves,
deltoids...), with real shoulder and crotch topology so the limbs grow out of the
torso instead of being stuck on. It is smooth-shaded and rigged with an armature,
so it deforms cleanly and can be posed or animated.

Usage
-----
With Blender installed:
    blender -b -P human_lowpoly.py -- [--render] [--turntable] [--quick] [--flat] [--out DIR]
With the `bpy` pip module (Python 3.11):
    python3 human_lowpoly.py [--render] [--turntable] [--quick] [--flat] [--out DIR]

Outputs (default DIR = this folder):
    models/human_lowpoly.blend    full scene (rigged character, pedestal, lights)
    models/human_lowpoly.glb      rigged character (A-pose rest + armature)
    models/human_lowpoly.fbx      rigged character
    models/human_lowpoly.obj/.mtl static mesh in the relaxed pose
    models/textures/human_face.png
    renders/*.png                 (with --render)
    renders/human_turntable.gif   (with --turntable, needs Pillow)

Conventions: metres, Z up, the character faces -Y and stands on Z = 0.
The character's left is +X (Blender's .L side).
"""

import math
import os
import random
import sys

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------
# Arguments
# --------------------------------------------------------------------------
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
DO_RENDER = "--render" in argv
DO_TURNTABLE = "--turntable" in argv
QUICK = "--quick" in argv
FLAT = "--flat" in argv            # faceted look instead of smooth shading
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

random.seed(11)

# --------------------------------------------------------------------------
# Palette (sRGB hex)
# --------------------------------------------------------------------------
PALETTE = {
    "skin": "E2AF8C",
    "hair": "3A2619",
    "hair_hi": "433021",
    "shirt": "C7653F",
    "jeans": "3D5A82",
    "shoe": "2F3540",
    "sole": "EEEBE4",
    "lace": "B9BEC6",
    "base": "7A828E",
    "base_dark": "5B636F",
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
CHAR_COLL = bpy.data.collections.new("Human")
SCENE.collection.children.link(CHAR_COLL)
ENV_COLL = bpy.data.collections.new("Environment")
SCENE.collection.children.link(ENV_COLL)

# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------
MATS = {}


def make_mat(name, hexcol, rough=0.8, metallic=0.0, spec=0.3, sheen=0.0, image=None):
    m = bpy.data.materials.new(name)
    if m.node_tree is None:
        m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = hex_lin(hexcol)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metallic
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = spec
    if sheen > 0 and "Sheen Weight" in bsdf.inputs:
        bsdf.inputs["Sheen Weight"].default_value = sheen
    if image is not None:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.location = (-400, 200)
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    m.diffuse_color = hex_lin(hexcol)
    MATS[name] = m
    return m


# --------------------------------------------------------------------------
# Face texture (eyes, brows, lips) painted with Pillow
# --------------------------------------------------------------------------
# The texture is projected onto the face from the front:
#   x in [FACE_X0, FACE_X1] -> u in [0, 1],  z in [FACE_Z0, FACE_Z1] -> v in [0, 1]
FACE_X0, FACE_X1 = -0.09, 0.09
FACE_Z0, FACE_Z1 = 1.50, 1.68
EYE_X, EYE_Z = 0.0335, 1.641
EYE_K = 1.14                     # eye size (1 = life size)
MOUTH_Z = 1.5655


def paint_face_texture(path, size=1024, ss=4):
    from PIL import Image, ImageDraw, ImageFilter

    S = size * ss
    skin = hex_rgb(PALETTE["skin"])
    img = Image.new("RGBA", (S, S), skin + (255,))

    def P(x, z):
        u = (x - FACE_X0) / (FACE_X1 - FACE_X0)
        v = (z - FACE_Z0) / (FACE_Z1 - FACE_Z0)
        return (u * S, (1.0 - v) * S)

    def qbez(p0, p1, p2, n=24):
        pts = []
        for i in range(n + 1):
            t = i / n
            a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
            pts.append((a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1]))
        return pts

    def stroke(layer, pts, w0, w1, col, wmid=None):
        """Variable-width stroke along a polyline (metres)."""
        d = ImageDraw.Draw(layer)
        top, bot = [], []
        n = len(pts)
        for i, p in enumerate(pts):
            a = pts[max(i - 1, 0)]
            b = pts[min(i + 1, n - 1)]
            tx, tz = b[0] - a[0], b[1] - a[1]
            ln = math.hypot(tx, tz) or 1.0
            nx, nz = -tz / ln, tx / ln
            t = i / (n - 1)
            if wmid is None:
                w = w0 + (w1 - w0) * t
            else:
                w = (w0 + (wmid - w0) * t * 2) if t < 0.5 else (wmid + (w1 - wmid) * (t - 0.5) * 2)
            w *= 0.5
            top.append(P(p[0] + nx * w, p[1] + nz * w))
            bot.append(P(p[0] - nx * w, p[1] - nz * w))
        d.polygon(top + bot[::-1], fill=col)

    def ellipse(layer, cx, cz, rx, rz, col):
        x0, y0 = P(cx - rx, cz + rz)
        x1, y1 = P(cx + rx, cz - rz)
        ImageDraw.Draw(layer).ellipse([x0, y0, x1, y1], fill=col)

    def blurred(fn, radius):
        layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        fn(layer)
        return layer.filter(ImageFilter.GaussianBlur(S * radius))

    # soft cheeks and a hint of shading under the brows
    img = Image.alpha_composite(img, blurred(lambda L: [
        ellipse(L, sx * 0.042, 1.610, 0.013, 0.008, hex_rgb("DE8F7A") + (28,)) for sx in (-1, 1)],
        0.010))
    img = Image.alpha_composite(img, blurred(lambda L: [
        ellipse(L, sx * EYE_X, EYE_Z + 0.006, 0.017, 0.007, hex_rgb("C98E70") + (60,))
        for sx in (-1, 1)], 0.006))

    lash = hex_rgb("2B1A12") + (255,)
    brow = hex_rgb("3A2619") + (255,)
    sclera = hex_rgb("F5F1EA") + (255,)
    iris_out = hex_rgb("3E2617")
    iris_in = hex_rgb("7A5232")

    for sx in (-1, 1):
        ex = EYE_X * sx

        def X(dx):           # +dx points away from the nose
            return ex + dx * sx * EYE_K

        def Z(dz):
            return EYE_Z + dz * EYE_K

        upper = qbez((X(-0.0140), Z(-0.0006)), (X(-0.002), Z(0.0085)),
                     (X(0.0150), Z(0.0004)))
        lower = qbez((X(0.0150), Z(0.0004)), (X(0.001), Z(-0.0062)),
                     (X(-0.0140), Z(-0.0006)))
        outline = [P(*p) for p in upper + lower]

        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).polygon(outline, fill=255)
        eye = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(eye).polygon(outline, fill=sclera)

        iris = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        icx, icz = X(0.0003), Z(0.0004)
        ellipse(iris, icx, icz, 0.0058 * EYE_K, 0.0058 * EYE_K, iris_out + (255,))
        ellipse(iris, icx, icz - 0.0008, 0.0044 * EYE_K, 0.0044 * EYE_K, iris_in + (255,))
        ellipse(iris, icx, icz, 0.0025 * EYE_K, 0.0025 * EYE_K, hex_rgb("120B07") + (255,))
        ellipse(iris, icx - 0.0018 * sx, icz + 0.0020, 0.0012, 0.0012, (255, 255, 255, 235))
        clipped = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        clipped.paste(iris, (0, 0), mask)
        eye = Image.alpha_composite(eye, clipped)

        # shadow cast by the upper lid
        shade = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        stroke(shade, [(p[0], p[1] - 0.0012) for p in upper], 0.0030, 0.0030,
               hex_rgb("8F6A58") + (110,))
        shade = shade.filter(ImageFilter.GaussianBlur(S * 0.002))
        sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        sh.paste(shade, (0, 0), mask)
        eye = Image.alpha_composite(eye, sh)
        img = Image.alpha_composite(img, eye)

        lines = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        stroke(lines, upper, 0.0010, 0.0016, lash, wmid=0.0020)
        stroke(lines, [upper[-1], (X(0.0172), Z(0.0016))], 0.0016, 0.0003, lash)
        stroke(lines, lower[2:-6], 0.0004, 0.0004, hex_rgb("9C6A55") + (200,), wmid=0.0008)
        # eyelid crease
        stroke(lines, qbez((X(-0.010), Z(0.0065)), (X(0.001), Z(0.0118)),
                           (X(0.0135), Z(0.0060))), 0.0004, 0.0004,
               hex_rgb("B57D63") + (200,), wmid=0.0008)
        # eyebrow
        stroke(lines, qbez((X(-0.0165), Z(0.0135)), (X(0.002), Z(0.0205)),
                           (X(0.0205), Z(0.0140))), 0.0052, 0.0016, brow, wmid=0.0045)
        img = Image.alpha_composite(img, lines)

    feat = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # nostrils
    for sx in (-1, 1):
        ellipse(feat, sx * 0.0068, 1.5888, 0.0024, 0.0011, hex_rgb("B97F68") + (110,))
    # lips
    lip = hex_rgb("C07A68") + (255,)
    lip_dark = hex_rgb("9C5A4C") + (255,)
    d = ImageDraw.Draw(feat)
    up = (qbez((-0.0215, MOUTH_Z), (-0.012, MOUTH_Z + 0.0062), (-0.0025, MOUTH_Z + 0.0050))
          + qbez((0.0025, MOUTH_Z + 0.0050), (0.012, MOUTH_Z + 0.0062), (0.0215, MOUTH_Z)))
    d.polygon([P(*p) for p in up] + [P(0.0, MOUTH_Z - 0.0004)], fill=lip_dark)
    lo = qbez((0.0200, MOUTH_Z - 0.0004), (0.0, MOUTH_Z - 0.0135), (-0.0200, MOUTH_Z - 0.0004))
    d.polygon([P(*p) for p in lo], fill=lip)
    stroke(feat, qbez((-0.0225, MOUTH_Z + 0.0002), (0.0, MOUTH_Z - 0.0012),
                      (0.0225, MOUTH_Z + 0.0002)), 0.0008, 0.0008, hex_rgb("6E3A30") + (255,),
           wmid=0.0013)
    feat = feat.filter(ImageFilter.GaussianBlur(S * 0.0006))
    img = Image.alpha_composite(img, feat)

    img = img.convert("RGB").resize((size, size), Image.LANCZOS)
    img.save(path)
    return path


# --------------------------------------------------------------------------
# Mesh building helpers
# --------------------------------------------------------------------------
# vertex "part" tags, used for the face UVs, hair placement and skinning
PART_TORSO, PART_HEAD, PART_EAR, PART_ARM, PART_HAND, PART_FINGER, PART_LEG, PART_SHOE, \
    PART_SOLE = range(9)


class MB:
    """Accumulates vertices/faces (with material indices and part tags) for one object."""

    def __init__(self):
        self.v = []
        self.f = []
        self.m = []
        self.part = []

    def vert(self, p, part=0):
        self.v.append(Vector(p))
        self.part.append(part)
        return len(self.v) - 1

    def face(self, idx, mat=0):
        self.f.append(tuple(idx))
        self.m.append(mat)

    def bridge(self, rings, closed=True, mat=0, mats=None, skip=None):
        """Connect consecutive rings of vertex indices (a ring of length 1 is a pole).
        Rings must run CCW around the direction of travel, which gives outward normals.
        mats: per-segment material, or a callable (segment, j) -> material.
        skip: callable (segment, j) -> True to leave that face out (holes)."""
        n = max(len(r) for r in rings)
        segs = n if closed else n - 1
        for i in range(len(rings) - 1):
            a, b = rings[i], rings[i + 1]
            for j in range(segs):
                if skip and skip(i, j):
                    continue
                if callable(mats):
                    mi = mats(i, j)
                else:
                    mi = mats[i] if mats else mat
                j1 = (j + 1) % n
                if len(a) == 1 and len(b) == 1:
                    continue
                if len(a) == 1:
                    self.face((a[0], b[j1], b[j]), mi)
                elif len(b) == 1:
                    self.face((a[j], a[j1], b[0]), mi)
                else:
                    self.face((a[j], a[j1], b[j1], b[j]), mi)

    def ring(self, pts, part):
        return [self.vert(p, part) for p in pts]

    def mirrored_x(self, eps=1e-6):
        """Return a copy with a mirrored right half. Vertices on x = 0 are shared,
        so the two halves weld into one watertight mesh."""
        out = MB()
        out.v = [v.copy() for v in self.v]
        out.part = list(self.part)
        remap = {}
        for i, v in enumerate(self.v):
            if abs(v.x) < eps:
                v.x = 0.0
                out.v[i].x = 0.0
                remap[i] = i
            else:
                remap[i] = len(out.v)
                out.v.append(Vector((-v.x, v.y, v.z)))
                out.part.append(self.part[i])
        out.f = list(self.f)
        out.m = list(self.m)
        for f, m in zip(self.f, self.m):
            out.f.append(tuple(remap[i] for i in reversed(f)))
            out.m.append(m)
        return out

    def compact(self):
        """Drop vertices no face uses."""
        used = sorted({i for f in self.f for i in f})
        remap = {o: n for n, o in enumerate(used)}
        self.v = [self.v[i] for i in used]
        self.part = [self.part[i] for i in used]
        self.f = [tuple(remap[i] for i in f) for f in self.f]

    def build(self, name, mat_names, smooth_angle=50, coll=None):
        self.compact()
        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(v) for v in self.v], [], self.f)
        me.validate(clean_customdata=False)
        me.update()
        for mn in mat_names:
            me.materials.append(MATS[mn])
        if len(me.polygons) == len(self.m):
            me.polygons.foreach_set("material_index", self.m)
        if FLAT or smooth_angle is None:
            me.shade_flat()
        else:
            me.shade_smooth()
            me.set_sharp_from_angle(angle=math.radians(smooth_angle))
        attr = me.attributes.new("part", "INT", "POINT")
        attr.data.foreach_set("value", self.part)
        ob = bpy.data.objects.new(name, me)
        (coll or CHAR_COLL).objects.link(ob)
        return ob


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def spow(x, e):
    """Signed power, for superellipse cross-sections (e < 1 squares them off)."""
    return math.copysign(abs(x) ** e, x)


def frame(T, up=Vector((0, 0, 1))):
    """(U, V) for a ring travelling along T: V is `up` made perpendicular to T and
    U = V x T, so U x V = T and CCW profiles give outward normals."""
    T = Vector(T).normalized()
    V = Vector(up) - T * Vector(up).dot(T)
    if V.length < 1e-6:
        V = Vector((0, 1, 0)) - T * T.y
    V.normalize()
    return V.cross(T).normalized(), V


def path_frames(pts, ref):
    n = len(pts)
    out = []
    for i in range(n):
        if i == 0:
            T = pts[1] - pts[0]
        elif i == n - 1:
            T = pts[-1] - pts[-2]
        else:
            T = pts[i + 1] - pts[i - 1]
        out.append(frame(T, ref(i) if callable(ref) else ref))
    return out


def tube(mb, pts, su, sv, ref, sides=6, part=0, mat=0, phase=0.0, cap=True):
    """Closed tube along pts with elliptical sections (su across, sv along ref).
    A radius of 0 at an end makes a pole, which rounds the end off."""
    pts = [Vector(p) for p in pts]
    frames = path_frames(pts, ref)
    rings = []
    for i, p in enumerate(pts):
        U, V = frames[i]
        a = su[i] if isinstance(su, (list, tuple)) else su
        b = sv[i] if isinstance(sv, (list, tuple)) else sv
        if a < 1e-7:
            rings.append([mb.vert(p, part)])
            continue
        ring = []
        for k in range(sides):
            ang = phase + 2 * math.pi * k / sides
            ring.append(mb.vert(p + U * (math.cos(ang) * a) + V * (math.sin(ang) * b), part))
        rings.append(ring)
    mb.bridge(rings, mat=mat)
    if cap:
        if len(rings[0]) > 1:
            mb.face(tuple(reversed(rings[0])), mat)
        if len(rings[-1]) > 1:
            mb.face(tuple(rings[-1]), mat)
    return rings


# ==========================================================================
# Materials
# ==========================================================================
face_png = paint_face_texture(os.path.join(TEX_DIR, "human_face.png"))
face_img = bpy.data.images.load(face_png)
face_img.name = "human_face"

BODY_MATS = ["Skin", "Skin_Face", "Shirt", "Jeans", "Shoe", "Sole", "Lace"]
M_SKIN, M_FACE, M_SHIRT, M_JEANS, M_SHOE, M_SOLE, M_LACE = range(len(BODY_MATS))
make_mat("Skin", PALETTE["skin"], rough=0.62, spec=0.35)
make_mat("Skin_Face", PALETTE["skin"], rough=0.62, spec=0.35, image=face_img)
make_mat("Shirt", PALETTE["shirt"], rough=0.9, spec=0.2, sheen=0.3)
make_mat("Jeans", PALETTE["jeans"], rough=0.85, spec=0.2, sheen=0.2)
make_mat("Shoe", PALETTE["shoe"], rough=0.7, spec=0.3)
make_mat("Sole", PALETTE["sole"], rough=0.75, spec=0.25)
make_mat("Lace", PALETTE["lace"], rough=0.85, spec=0.2)
make_mat("Hair", PALETTE["hair"], rough=0.55, spec=0.45)
make_mat("Hair_Light", PALETTE["hair_hi"], rough=0.55, spec=0.45)
make_mat("Base", PALETTE["base"], rough=0.85)
make_mat("Base_Dark", PALETTE["base_dark"], rough=0.85)

# ==========================================================================
# Body: torso, neck and head
# ==========================================================================
# The body is modelled as its left half (x >= 0) and mirrored. Torso, neck and head
# share one stack of half-rings that run from the front centre (-Y) round the left
# side (+X) to the back centre (+Y).
TORSO_ANG = [-90 + 22.5 * h for h in range(9)]
HEAD_ANG = [-90, -73, -55, -35, -13, 14, 42, 67, 90]   # denser over the face


def half_ring(z, w, f, b, cy=0.0, n=2.2, zf=None, zb=None, ang=TORSO_ANG):
    """9 points: front centre -> left side -> back centre.
    w half-width, f / b depth in front of / behind cy, n superellipse exponent,
    zf / zb tilt the ring (height at the front / back centre)."""
    zf = z if zf is None else zf
    zb = z if zb is None else zb
    e = 2.0 / n
    pts = []
    for a in ang:
        th = math.radians(a)
        c, s = math.cos(th), math.sin(th)
        x = w * spow(c, e)
        y = cy + (b if s > 0 else f) * spow(s, e)
        zz = z + (zf - z) * max(0.0, -s) + (zb - z) * max(0.0, s)
        pts.append(Vector((x, y, zz)))
    pts[0].x = pts[-1].x = 0.0
    return pts


def blend_ang(t):
    return [lerp(a, b, t) for a, b in zip(TORSO_ANG, HEAD_ANG)]


# (name, material of the band ABOVE this ring, ring)
TORSO_SPEC = [
    ("hip", M_JEANS, half_ring(0.893, 0.166, 0.092, 0.114, 0.012, 2.3, zf=0.866, zb=0.862)),
    ("hem_in", M_SHIRT, half_ring(0.928, 0.168, 0.095, 0.115, 0.010, 2.3)),
    ("hem_out", M_SHIRT, half_ring(0.932, 0.178, 0.104, 0.122, 0.010, 2.3)),
    ("waist_lo", M_SHIRT, half_ring(1.015, 0.168, 0.103, 0.111, 0.006, 2.3)),
    ("waist", M_SHIRT, half_ring(1.100, 0.161, 0.105, 0.102, 0.002, 2.4)),
    ("ribs", M_SHIRT, half_ring(1.180, 0.165, 0.110, 0.102, -0.002, 2.5)),
    ("chest", M_SHIRT, half_ring(1.260, 0.169, 0.116, 0.104, -0.004, 2.6)),
    ("armpit", M_SHIRT, half_ring(1.325, 0.168, 0.112, 0.105, -0.004, 2.6)),
    ("shoulder", M_SHIRT, half_ring(1.388, 0.166, 0.104, 0.102, -0.002, 2.6)),
    ("yoke", M_SHIRT, half_ring(1.433, 0.136, 0.086, 0.091, 0.004, 2.3, zf=1.426, zb=1.452)),
    ("collar_out", M_SHIRT, half_ring(1.480, 0.076, 0.068, 0.071, 0.010, 2.0, zf=1.456,
                                      zb=1.488, ang=blend_ang(0.2))),
    ("collar_in", M_SKIN, half_ring(1.477, 0.065, 0.058, 0.062, 0.010, 2.0, zf=1.453,
                                    zb=1.485, ang=blend_ang(0.2))),
    ("neck0", M_SKIN, half_ring(1.509, 0.061, 0.054, 0.059, 0.012, 2.0, zf=1.489, zb=1.519,
                                ang=blend_ang(0.5))),
    ("neck1", M_SKIN, half_ring(1.532, 0.058, 0.051, 0.058, 0.014, 2.0, zf=1.510, zb=1.548,
                                ang=blend_ang(0.8))),
]

HEAD_SPEC = [
    # (name, z side, half-width, front depth, back depth, cy, n, z front, z back)
    ("jaw", 1.562, 0.066, 0.092, 0.058, 0.010, 2.8, 1.525, 1.566),
    ("chin", 1.578, 0.070, 0.094, 0.072, 0.008, 2.6, 1.541, 1.586),
    ("mouth", 1.596, 0.072, 0.098, 0.085, 0.006, 2.3, 1.563, 1.600),
    ("philtrum", 1.606, 0.072, 0.099, 0.090, 0.006, 2.3, 1.584, 1.608),
    ("nose", 1.616, 0.074, 0.098, 0.094, 0.006, 2.3, 1.596, 1.616),
    ("cheek", 1.630, 0.077, 0.097, 0.098, 0.006, 2.3, 1.622, 1.630),
    ("eyes", 1.645, 0.078, 0.095, 0.101, 0.007, 2.3, 1.645, 1.645),
    ("brow", 1.666, 0.077, 0.096, 0.102, 0.007, 2.3, 1.667, 1.666),
    ("forehead", 1.696, 0.073, 0.090, 0.098, 0.008, 2.2, 1.696, 1.694),
    ("crown_lo", 1.722, 0.062, 0.075, 0.085, 0.009, 2.1, 1.722, 1.720),
    ("crown", 1.742, 0.040, 0.049, 0.057, 0.010, 2.0, 1.742, 1.741),
]
CROWN_TOP = Vector((0.0, 0.011, 1.752))
HEAD_SCALE = 1.05                       # slightly stylised: a touch bigger than life
HEAD_PIVOT = Vector((0.0, 0.012, 1.53))


def head_xf(p):
    return HEAD_PIVOT + (Vector(p) - HEAD_PIVOT) * HEAD_SCALE


def head_unxf(p):
    return HEAD_PIVOT + (Vector(p) - HEAD_PIVOT) / HEAD_SCALE


# Per-vertex sculpting of the face: (ring, index) -> absolute y for the front
# centre column, or an offset vector elsewhere.
FACE_PROFILE_Y = {          # front centre (index 0)
    "jaw": -0.084, "chin": -0.093, "mouth": -0.095, "philtrum": -0.099, "nose": -0.121,
    "cheek": -0.111, "eyes": -0.103, "brow": -0.101,
}
FACE_TWEAKS = {
    ("philtrum", 1): (0.0, -0.004, 0.0),       # nostril wings
    ("nose", 1): (-0.004, -0.010, -0.004),
    ("cheek", 1): (-0.003, -0.004, 0.0),
    ("eyes", 1): (0.0, 0.004, 0.0),              # eye sockets
    ("eyes", 2): (0.0, 0.002, 0.0),
    ("brow", 1): (0.0, -0.001, 0.0),
    ("brow", 2): (0.0, -0.002, 0.0),
    ("cheek", 2): (0.002, -0.004, 0.0),          # cheekbones
    ("cheek", 3): (0.002, -0.002, 0.0),
    ("mouth", 1): (0.0, -0.002, 0.0),
    ("jaw", 3): (0.002, 0.0, 0.004),             # jaw angle
    ("jaw", 4): (0.002, 0.0, 0.004),
}

ARMPIT, SHOULDER, YOKE = 7, 8, 9    # torso rings the arm grows out of
# the 8 vertices around the shoulder socket (overrides of indices 3/4/5 on those rings)
SOCKET = {
    (ARMPIT, 3): (0.158, -0.058, 1.340),
    (ARMPIT, 4): (0.156, 0.002, 1.322),
    (ARMPIT, 5): (0.156, 0.059, 1.340),
    (SHOULDER, 3): (0.177, -0.067, 1.392),
    (SHOULDER, 5): (0.177, 0.064, 1.392),
    (YOKE, 3): (0.193, -0.047, 1.431),
    (YOKE, 4): (0.206, 0.004, 1.438),
    (YOKE, 5): (0.193, 0.051, 1.431),
}

# Joint positions (left side) shared with the skeleton
S_JOINT = Vector((0.189, 0.0, 1.386))           # shoulder
ARM_DROP = math.radians(52)                      # A-pose: arm angle below horizontal
ARM_DIR = Vector((math.cos(ARM_DROP), 0.0, -math.sin(ARM_DROP)))
UPPER_ARM_LEN, FOREARM_LEN = 0.295, 0.255
E_JOINT = S_JOINT + ARM_DIR * UPPER_ARM_LEN       # elbow
FORE_DIR = (ARM_DIR + Vector((0.0, -0.17, -0.02))).normalized()
W_JOINT = E_JOINT + FORE_DIR * FOREARM_LEN        # wrist
HAND_DIR = (FORE_DIR + Vector((0.0, 0.0, -0.06))).normalized()

H_JOINT = Vector((0.092, 0.0, 0.900))            # hip
K_JOINT = Vector((0.097, -0.010, 0.490))          # knee
A_JOINT = Vector((0.103, 0.022, 0.088))           # ankle
TOE_OUT = math.radians(6)


def build_body():
    mb = MB()

    # ---------------- torso / neck / head stack --------------------------
    specs = [(name, mat, list(pts)) for name, mat, pts in TORSO_SPEC]
    for name, zs, w, f, b, cy, n, zf, zb in HEAD_SPEC:
        pts = half_ring(zs, w, f, b, cy, n, zf, zb, ang=HEAD_ANG)
        if name in FACE_PROFILE_Y:
            pts[0].y = FACE_PROFILE_Y[name]
        for (rn, idx), off in FACE_TWEAKS.items():
            if rn == name:
                pts[idx] += Vector(off)
        specs.append((name, M_SKIN, [head_xf(p) for p in pts]))

    stack = []
    for k, (name, mat, pts) in enumerate(specs):
        for (rk, idx), p in SOCKET.items():
            if rk == k:
                pts[idx] = Vector(p)
        part = PART_HEAD if k >= len(TORSO_SPEC) - 2 else PART_TORSO
        stack.append(mb.ring(pts, part))
    stack.append([mb.vert(head_xf(CROWN_TOP), PART_HEAD)])
    seg_mats = [mat for _, mat, _ in specs]

    def socket_hole(i, j):
        return i in (ARMPIT, SHOULDER) and j in (3, 4)

    mb.bridge(stack, closed=False, mats=seg_mats, skip=socket_hole)

    # ---------------- arm ------------------------------------------------
    hole = [stack[SHOULDER][5], stack[YOKE][5], stack[YOKE][4], stack[YOKE][3],
            stack[SHOULDER][3], stack[ARMPIT][3], stack[ARMPIT][4], stack[ARMPIT][5]]
    build_arm(mb, hole)

    # ---------------- leg ------------------------------------------------
    hip = stack[0]
    crotch = mb.vert((0.0, 0.010, 0.826), PART_LEG)
    top_loop = [hip[4], hip[5], hip[6], hip[7], hip[8], crotch, hip[0], hip[1], hip[2],
                hip[3]]
    build_leg(mb, top_loop)

    build_ear(mb)
    return mb


# --------------------------------------------------------------------------
# Arm and hand
# --------------------------------------------------------------------------
def arm_ring(c, T, su_b, su_f, sv_t, sv_d, n=8, e=1.0):
    """8-point ring around T. U points back (+Y), V points up (back of the hand)."""
    U, V = frame(T)
    pts = []
    for k in range(n):
        a = 2 * math.pi * k / n
        cu, sv = math.cos(a), math.sin(a)
        pu = (su_b if cu > 0 else su_f) * spow(cu, e)
        pv = (sv_t if sv > 0 else sv_d) * spow(sv, e)
        pts.append(c + U * pu + V * pv)
    return pts


def build_arm(mb, hole):
    rings = [hole]
    mats = []
    d, d2, d3 = ARM_DIR, FORE_DIR, HAND_DIR
    S, E, W = S_JOINT, E_JOINT, W_JOINT

    # (centre, direction, back, front, top, bottom radius, material of the band leading
    # here, part)
    secs = [
        (S + d * 0.045, d, 0.058, 0.060, 0.064, 0.052, M_SHIRT, PART_ARM),   # deltoid
        (S + d * 0.105, d, 0.057, 0.058, 0.060, 0.053, M_SHIRT, PART_ARM),
        (S + d * 0.140, d, 0.056, 0.057, 0.057, 0.053, M_SHIRT, PART_ARM),   # sleeve hem
        (S + d * 0.137, d, 0.046, 0.047, 0.048, 0.044, M_SHIRT, PART_ARM),   # (inside)
        (S + d * 0.200, d, 0.044, 0.046, 0.046, 0.042, M_SKIN, PART_ARM),    # biceps
        (S + d * 0.262, d, 0.039, 0.040, 0.040, 0.037, M_SKIN, PART_ARM),
        (E + d * 0.005, (d + d2).normalized(), 0.042, 0.036, 0.037, 0.035, M_SKIN,
         PART_ARM),                                                           # elbow
        (E + d2 * 0.055, d2, 0.042, 0.043, 0.039, 0.036, M_SKIN, PART_ARM),  # forearm
        (E + d2 * 0.135, d2, 0.036, 0.037, 0.031, 0.029, M_SKIN, PART_ARM),
        (E + d2 * 0.205, d2, 0.030, 0.031, 0.023, 0.022, M_SKIN, PART_ARM),
        (W, d2, 0.028, 0.029, 0.0195, 0.0185, M_SKIN, PART_ARM),             # wrist
        (W + d3 * 0.024, d3, 0.034, 0.039, 0.020, 0.020, M_SKIN, PART_HAND),  # palm
        (W + d3 * 0.060, d3, 0.043, 0.044, 0.019, 0.019, M_SKIN, PART_HAND),
        (W + d3 * 0.090, d3, 0.045, 0.045, 0.016, 0.0155, M_SKIN, PART_HAND),  # knuckles
        (W + d3 * 0.101, d3, 0.037, 0.037, 0.011, 0.0105, M_SKIN, PART_HAND),
    ]
    for c, T, sb, sf, st, sd, mat, part in secs:
        rings.append(mb.ring(arm_ring(c, T, sb, sf, st, sd, e=0.92), part))
        mats.append(mat)
    rings.append([mb.vert(W + d3 * 0.104, PART_HAND)])
    mats.append(M_SKIN)
    mb.bridge(rings, mats=mats)
    build_fingers(mb)


FINGERS = [
    # (name, offset across the hand, length, spread degrees, radius)
    ("index", -0.0305, 0.076, -5.0, 0.0100),
    ("middle", -0.0102, 0.084, -1.0, 0.0103),
    ("ring", 0.0105, 0.079, 3.0, 0.0098),
    ("pinky", 0.0295, 0.063, 8.0, 0.0086),
]


def finger_chain(base, direction, V, lengths, curls):
    """Joint positions of a finger curling towards -V (the palm)."""
    pts = [base]
    dirn = direction.normalized()
    side = V.cross(dirn).normalized()       # rotation axis across the finger
    for ln, curl in zip(lengths, curls):
        dirn = (Matrix.Rotation(math.radians(curl), 3, side) @ dirn).normalized()
        pts.append(pts[-1] + dirn * ln)
    return pts


def hand_frame():
    return frame(HAND_DIR)


def finger_joints():
    """Joint chains for every finger and the thumb (used by the mesh and the rig)."""
    U, V = hand_frame()
    d3 = HAND_DIR
    knuckle = W_JOINT + d3 * 0.090
    out = {}
    for name, off, ln, spread, r in FINGERS:
        base = knuckle + U * off - V * 0.003
        dirn = Matrix.Rotation(math.radians(spread), 3, V) @ d3
        out[name] = finger_chain(base, dirn, V, [ln * 0.45, ln * 0.31, ln * 0.24],
                                 [8, 16, 14])
    # thumb: from the base of the palm, forwards (-U) and towards the palm
    base = W_JOINT + d3 * 0.012 - U * 0.020 - V * 0.006
    dirn = (d3 * 0.62 - U * 0.62 - V * 0.48).normalized()
    out["thumb"] = finger_chain(base, dirn, V, [0.032, 0.030, 0.026], [0, 14, 16])
    return out


def build_fingers(mb):
    U, V = hand_frame()
    joints = finger_joints()
    radii = {name: r for name, _, _, _, r in FINGERS}
    radii["thumb"] = 0.0118
    for name, pts in joints.items():
        r = radii[name]
        if name == "thumb":
            path = [pts[0], pts[0].lerp(pts[1], 0.5), pts[1], pts[2], pts[3].lerp(pts[2], 0.25),
                    pts[3]]
            su = [r * 1.05, r * 1.15, r * 1.0, r * 0.92, r * 0.82, 0.0]
        else:
            back = pts[0] - (pts[1] - pts[0]).normalized() * 0.012
            path = [back, pts[0], pts[1], pts[2], pts[3].lerp(pts[2], 0.25), pts[3]]
            su = [r * 1.05, r * 1.05, r * 0.95, r * 0.88, r * 0.80, 0.0]
        sv = [s * 0.86 for s in su]
        tube(mb, path, su, sv, ref=V, sides=6, part=PART_FINGER, mat=M_SKIN,
             phase=math.pi / 6)


# --------------------------------------------------------------------------
# Leg and shoe
# --------------------------------------------------------------------------
def leg_axis(z):
    if z >= K_JOINT.z:
        t = (H_JOINT.z - z) / (H_JOINT.z - K_JOINT.z)
        return H_JOINT.lerp(K_JOINT, t)
    t = (K_JOINT.z - z) / (K_JOINT.z - A_JOINT.z)
    return K_JOINT.lerp(A_JOINT, t)


UNIFORM10 = [36.0 * k for k in range(10)]


def leg_ring(z, ro, ri, rf, rb, angles=UNIFORM10, n=2.1, z_in=None, z_out=None,
             z_front=None, z_back=None, dy=0.0):
    """10 points CCW from above, starting at the outer side (+X).
    ro / ri outer / inner radius, rf / rb front / back radius."""
    c = leg_axis(z)
    e = 2.0 / n
    pts = []
    for a in angles:
        th = math.radians(a)
        cs, sn = math.cos(th), math.sin(th)
        x = c.x + (ro if cs > 0 else ri) * spow(cs, e)
        y = c.y + dy + (rb if sn > 0 else rf) * spow(sn, e)
        zz = z
        if z_in is not None:
            zz += (z_in - z) * max(0.0, -cs)
        if z_out is not None:
            zz += (z_out - z) * max(0.0, cs)
        if z_front is not None:
            zz += (z_front - z) * max(0.0, -sn)
        if z_back is not None:
            zz += (z_back - z) * max(0.0, sn)
        pts.append(Vector((x, y, zz)))
    return pts


def shoe_section(A, B, su):
    """10 points across the foot. A = (y, z) of the top / front of the section,
    B = (y, z) of the bottom / back. Index 0 is the outer side, 1-4 run along the
    sole, 5 is the inner side and 6-9 run over the top of the foot."""
    A = Vector((0.0, A[0], A[1]))
    B = Vector((0.0, B[0], B[1]))
    c = (A + B) * 0.5
    c.x = A_JOINT.x
    sv = (B - A).length * 0.5
    V = (B - A).normalized()
    pts = []
    for a in UNIFORM10:
        th = math.radians(a)
        cs, sn = math.cos(th), math.sin(th)
        if sn > 0:      # sole side: square it off
            px, py = spow(cs, 0.55), spow(sn, 0.55)
            w = su
        else:           # top of the foot: rounder and a little narrower
            px, py = spow(cs, 0.85), spow(sn, 0.9)
            w = su * 0.88
        pts.append(c + Vector((px * w, 0, 0)) + V * (py * sv))
    return pts


SHOE_SECTIONS = [
    # A (y, z) top/front, B (y, z) bottom/back, half width -- from the toe back
    ((-0.186, 0.046), (-0.186, 0.016), 0.034),
    ((-0.160, 0.057), (-0.160, 0.013), 0.045),
    ((-0.123, 0.068), (-0.123, 0.012), 0.050),
    ((-0.085, 0.082), (-0.085, 0.012), 0.048),
    ((-0.050, 0.093), (-0.040, 0.012), 0.045),
    ((-0.040, 0.097), (0.022, 0.012), 0.042),
    ((-0.034, 0.100), (0.054, 0.020), 0.040),
    ((-0.029, 0.103), (0.066, 0.052), 0.040),
]
SHOE_TIP = (-0.198, 0.029)


def toe_out(p):
    """Rotate shoe geometry about the ankle so the feet point slightly outwards."""
    piv = Vector((A_JOINT.x, A_JOINT.y, 0.0))
    rot = Matrix.Rotation(TOE_OUT, 3, "Z")
    q = Vector(p) - piv
    return rot @ q + piv


def build_leg(mb, top_loop):
    rings = []

    # toe -> heel (shoe upper)
    tip = Vector((A_JOINT.x, SHOE_TIP[0], SHOE_TIP[1]))
    rings.append([mb.vert(toe_out(tip), PART_SHOE)])
    for A, B, su in SHOE_SECTIONS:
        rings.append(mb.ring([toe_out(p) for p in shoe_section(A, B, su)], PART_SHOE))

    def shoe_mat(i, j):
        if j in (7, 8) and 3 <= i <= 6:     # laces / tongue
            return M_LACE
        return M_SHOE

    # shoe collar (horizontal ring round the ankle) and jeans hem
    collar = leg_ring(0.100, 0.040, 0.038, 0.045, 0.046, z_front=0.104, z_back=0.098,
                      dy=0.001)
    rings.append(mb.ring([toe_out(p) for p in collar], PART_SHOE))
    n_shoe = len(rings) - 1

    # (z, outer, inner, front, back, kwargs) from the jeans hem up to the thigh
    leg_specs = [
        (0.104, 0.056, 0.055, 0.058, 0.060, dict(z_front=0.116, z_back=0.090)),  # hem
        (0.150, 0.055, 0.054, 0.056, 0.059, {}),
        (0.245, 0.055, 0.053, 0.056, 0.061, {}),
        (0.345, 0.058, 0.055, 0.057, 0.066, {}),       # calf
        (0.430, 0.058, 0.056, 0.059, 0.063, {}),
        (0.495, 0.061, 0.058, 0.064, 0.060, {}),       # knee
        (0.580, 0.069, 0.062, 0.071, 0.067, {}),
        (0.680, 0.078, 0.068, 0.080, 0.079, {}),
        (0.770, 0.085, 0.072, 0.086, 0.091, dict(z_in=0.762)),
    ]
    # the top loop is irregular (it shares the hip ring); blend into even spacing
    top_pts = [mb.v[i] for i in top_loop]
    cen = leg_axis(0.84)
    top_ang = []
    for p in top_pts:
        a = math.degrees(math.atan2(p.y - cen.y, p.x - cen.x)) % 360.0
        top_ang.append(a)
    top_ang[0] = top_ang[0] if top_ang[0] < 180 else top_ang[0] - 360.0
    for k, (z, ro, ri, rf, rb, kw) in enumerate(leg_specs):
        t = smoothstep((k - (len(leg_specs) - 3)) / 2.0)
        ang = [lerp(u, a, t * 0.85) for u, a in zip(UNIFORM10, top_ang)]
        rings.append(mb.ring(leg_ring(z, ro, ri, rf, rb, ang, **kw), PART_LEG))
    rings.append(top_loop)

    def mat(i, j):
        if i < n_shoe:
            return shoe_mat(i, j)
        return M_JEANS        # hem underside and the jeans leg

    mb.bridge(rings, mats=mat)
    build_sole(mb)


def build_sole(mb):
    """Separate rubber sole under the shoe upper."""
    # (y, outer half-width, inner half-width) from toe to heel
    prof = [(-0.196, 0.022, 0.022), (-0.186, 0.036, 0.034), (-0.160, 0.050, 0.047),
            (-0.123, 0.056, 0.052), (-0.085, 0.054, 0.046), (-0.045, 0.050, 0.040),
            (-0.005, 0.047, 0.040), (0.030, 0.045, 0.042), (0.056, 0.040, 0.038),
            (0.070, 0.028, 0.027), (0.077, 0.0, 0.0)]
    cx = A_JOINT.x
    outline = []
    # outer side toe -> heel, then inner side heel -> toe (CCW seen from above)
    for y, wo, wi in prof[:-1]:
        outline.append(Vector((cx + wo, y, 0)))
    outline.append(Vector((cx, prof[-1][0], 0)))
    for y, wo, wi in reversed(prof[1:-1]):
        outline.append(Vector((cx - wi, y, 0)))
    outline.append(Vector((cx, -0.202, 0)))
    centre = Vector((cx, -0.06, 0))

    def ring_at(z, inset):
        pts = []
        n = len(outline)
        for i, p in enumerate(outline):
            a, b = outline[i - 1], outline[(i + 1) % n]
            t = (b - a).normalized()
            nrm = Vector((t.y, -t.x, 0))         # outward for a CCW outline
            pts.append(toe_out(p + nrm * (0.004 - inset) + Vector((0, 0, z))))
        return pts

    rings = [[mb.vert(toe_out(centre), PART_SOLE)]]
    for z, inset in ((0.0, 0.003), (0.004, 0.0), (0.024, 0.0), (0.027, 0.003)):
        rings.append(mb.ring(ring_at(z, inset), PART_SOLE))
    rings.append([mb.vert(toe_out(centre + Vector((0, 0, 0.027))), PART_SOLE)])
    mb.bridge(rings, mat=M_SOLE)


# --------------------------------------------------------------------------
# Ears
# --------------------------------------------------------------------------
def build_ear(mb):
    base = Vector((0.0705, 0.010, 1.632))
    tilt = Matrix.Rotation(math.radians(-14), 3, "X")     # top leans back
    # (height, outwards, back, width, thickness)
    secs = [(-0.034, 0.002, 0.006, 0.0, 0.0),
            (-0.028, 0.006, 0.004, 0.008, 0.005),
            (-0.012, 0.010, 0.006, 0.013, 0.006),
            (0.008, 0.012, 0.008, 0.016, 0.006),
            (0.024, 0.011, 0.009, 0.013, 0.006),
            (0.033, 0.007, 0.008, 0.0, 0.0)]
    pts, su, sv = [], [], []
    for h, out, back, w, t in secs:
        pts.append(head_xf(base + tilt @ Vector((out, back, h))))
        su.append(w * HEAD_SCALE)
        sv.append(t * HEAD_SCALE)
    tube(mb, pts, su, sv, ref=Vector((1, 0, 0)), sides=6, part=PART_EAR, mat=M_SKIN)


# ==========================================================================
# Hair: a short cut shrink-wrapped onto the scalp, plus a few chunky locks
# ==========================================================================
HAIR_C = Vector((0.0, 0.010, 1.640))


def sph(az, el):
    """Unit direction: az 0 = front (-Y), 90 = left (+X); el 90 = straight up."""
    az, el = math.radians(az), math.radians(el)
    return Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))


# hairline elevation (degrees) against |azimuth|: forehead, temples, sideburns,
# around the ears, nape
HAIRLINE = [(0, 37), (22, 35), (40, 27), (54, 18), (64, 4), (71, -15), (80, -17),
            (86, 4), (92, 21), (106, 23), (117, 8), (128, -18), (148, -36), (180, -42)]


def hairline(az):
    a = abs((az + 180.0) % 360.0 - 180.0)
    for (a0, e0), (a1, e1) in zip(HAIRLINE, HAIRLINE[1:]):
        if a0 <= a <= a1:
            t = (a - a0) / (a1 - a0)
            return lerp(e0, e1, (1 - math.cos(math.pi * t)) * 0.5)
    return HAIRLINE[-1][1]


def hair_thickness(az, el, el0):
    a = math.radians(az)
    top = smoothstep((el - 8.0) / 60.0)
    front = max(0.0, math.cos(a)) ** 2 * smoothstep((el - 22.0) / 26.0)
    side = abs(math.sin(a)) * (1.0 - top)
    t = 0.0030 + 0.0045 * smoothstep((el - el0) / 10.0) + 0.0150 * top + 0.0075 * front
    return t - 0.0015 * side


def head_bvh(body):
    me = body.data
    parts = [a.value for a in me.attributes["part"].data]
    verts = [v.co.copy() for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons
             if all(parts[i] == PART_HEAD for i in p.vertices)]
    return BVHTree.FromPolygons(verts, polys)


def scalp_point(bvh, centre, d):
    hit = bvh.ray_cast(centre, d, 0.3)
    if hit[0] is None:
        return centre + d * 0.10
    return hit[0]


def build_hair(body):
    bvh = head_bvh(body)
    centre = head_xf(HAIR_C)
    mb = MB()
    n_az, n_el = 40, 9
    cols = []
    for i in range(n_az):
        az = 360.0 * i / n_az
        el0 = hairline(az)
        # choppy edge: alternate the hairline a little
        jag = 1.0 if abs(math.cos(math.radians(az))) > 0.6 else 0.5
        el0 += (1.6 if i % 2 else -1.0) * jag
        col = []
        d = sph(az, el0)
        p = scalp_point(bvh, centre, d)
        col.append(p - d * 0.003)                         # tucked under the scalp
        for j in range(n_el):
            t = (j / n_el) ** 1.15
            el = lerp(el0, 88.0, t)
            d = sph(az, el)
            p = scalp_point(bvh, centre, d)
            col.append(p + d * hair_thickness(az, el, el0))
        cols.append(col)
    rings = []
    for j in range(n_el + 1):
        rings.append([mb.vert(cols[i][j]) for i in range(n_az)])
    top = scalp_point(bvh, centre, Vector((0, 0.05, 1)).normalized())
    rings.append([mb.vert(top + Vector((0, 0, 0.0245)))])
    mb.bridge(rings, mat=0)

    # a few chunky locks over the top for a tousled, low-poly silhouette
    locks = [
        # root (az, el), tip (az, el), width, lift
        ((170, 72), (8, 44), 0.038, 0.003),
        ((185, 74), (-14, 46), 0.038, 0.003),
        ((150, 70), (30, 42), 0.036, 0.0025),
        ((205, 70), (-34, 41), 0.036, 0.0025),
        ((175, 80), (-2, 58), 0.040, 0.004),
        ((120, 62), (62, 36), 0.032, 0.002),
        ((240, 62), (-62, 36), 0.032, 0.002),
        ((150, 50), (95, 40), 0.030, 0.0015),
        ((210, 50), (-95, 40), 0.030, 0.0015),
    ]
    for root, tip, w, lift in locks:
        hair_lock(mb, bvh, centre, root, tip, w, lift)
    return mb.build("Human_Hair", ["Hair", "Hair_Light"], smooth_angle=45)


def hair_lock(mb, bvh, centre, root, tip, width, lift, segs=7):
    """A flattened clump that follows the scalp from root to tip and ends in a point."""
    pts, nrm = [], []
    d0, d1 = sph(*root), sph(*tip)
    for i in range(segs + 1):
        t = i / segs
        d = d0.lerp(d1, t).normalized()
        az = math.degrees(math.atan2(d.x, -d.y))
        el = math.degrees(math.asin(max(-1.0, min(1.0, d.z))))
        base = scalp_point(bvh, centre, d)
        r = hair_thickness(az, el, hairline(az)) + lift * math.sin(math.pi * min(1.0, t * 1.15))
        pts.append(base + d * (r * lerp(0.55, 0.86, smoothstep(t / 0.3))))
        nrm.append(d)
    frames = path_frames(pts, lambda i: nrm[i])
    prof = [(1, 0), (0.4, 0.7), (-0.4, 0.7), (-1, 0), (-0.4, -0.45), (0.4, -0.45)]
    rings = []
    for i, p in enumerate(pts):
        t = i / segs
        if i == segs:
            rings.append([mb.vert(p)])
            continue
        U, V = frames[i]
        grow = smoothstep(t / 0.35)
        w = width * (0.25 + 0.75 * grow) * (1.0 - t) ** 0.6
        th = 0.0085 * (0.3 + 0.7 * grow) * (1.0 - t ** 1.5) + 0.0012
        rings.append([mb.vert(p + U * (px * w) + V * (py * th)) for px, py in prof])
    mat = 1 if random.random() < 0.5 else 0
    mb.bridge(rings, mat=mat)
    mb.face(tuple(reversed(rings[0])), mat)


# ==========================================================================
# Head UVs (front projection for the painted face)
# ==========================================================================
def face_uvs(ob):
    me = ob.data
    uv = me.uv_layers.new(name="UVMap")
    parts = me.attributes["part"].data
    for poly in me.polygons:
        vs = poly.vertices
        is_face = (all(parts[i].value == PART_HEAD for i in vs)
                   and poly.center.y < -0.045 and poly.center.z < 1.69
                   and poly.center.z > 1.515 and abs(poly.center.x) < 0.075)
        if is_face:
            poly.material_index = M_FACE
        for li in poly.loop_indices:
            co = head_unxf(me.vertices[me.loops[li].vertex_index].co)
            if is_face:
                u = (co.x - FACE_X0) / (FACE_X1 - FACE_X0)
                v = (co.z - FACE_Z0) / (FACE_Z1 - FACE_Z0)
            else:
                u, v = 0.01, 0.01        # plain skin corner of the texture
            uv.data[li].uv = (u, v)


# ==========================================================================
# Environment: pedestal, lights, world, camera
# ==========================================================================
def build_pedestal():
    mb = MB()
    n = 28
    rings = []
    for z, r in ((-0.10, 0.50), (-0.094, 0.512), (-0.012, 0.512), (0.0, 0.50)):
        rings.append([mb.vert((r * math.cos(2 * math.pi * k / n),
                               r * math.sin(2 * math.pi * k / n), z)) for k in range(n)])
    mats = [1, 0, 0]
    mb.bridge(rings, mats=mats)
    mb.face(tuple(reversed(rings[0])), 1)
    mb.face(tuple(rings[-1]), 0)
    return mb.build("Pedestal", ["Base", "Base_Dark"], smooth_angle=30, coll=ENV_COLL)


def setup_world():
    w = bpy.data.worlds.new("World")
    SCENE.world = w
    if w.node_tree is None:
        w.use_nodes = True
    nt = w.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = hex_lin("E2E4E8")
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = hex_lin("A9B3C2")
    bg_cam = nt.nodes.new("ShaderNodeBackground")
    bg_amb = nt.nodes.new("ShaderNodeBackground")
    bg_amb.inputs["Color"].default_value = hex_lin("C4CCD8")
    bg_amb.inputs["Strength"].default_value = 0.55
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(tc.outputs["Window"], sep.inputs[0])
    nt.links.new(sep.outputs["Y"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg_cam.inputs["Color"])
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
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return ob


def setup_lights():
    tgt = (0, 0, 0.95)
    add_area("Key", (-2.0, -2.7, 3.1), tgt, 460, 1.8, (1.0, 0.95, 0.88))
    add_area("Fill", (2.8, -2.1, 1.5), tgt, 130, 3.0, (0.86, 0.91, 1.0))
    add_area("Rim", (1.1, 3.0, 2.7), tgt, 400, 1.4, (1.0, 0.97, 0.93))
    add_area("Rim2", (-1.7, 2.6, 1.9), tgt, 180, 1.4, (0.86, 0.92, 1.0))


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
    SCENE.view_settings.exposure = -0.3
    r.resolution_x = 540 if QUICK else 1200
    r.resolution_y = 720 if QUICK else 1600
    r.resolution_percentage = 100
    r.film_transparent = False
    try:
        SCENE.view_settings.view_transform = "AgX"
        SCENE.view_settings.look = "AgX - Punchy"
    except Exception:
        pass


# ==========================================================================
# Rig: armature, skin weights and a relaxed pose
# ==========================================================================
def bone_specs():
    """(name, head, tail, parent, roll_axis). Left side only; .R bones are mirrored."""
    d3 = HAND_DIR
    _, hand_v = hand_frame()
    ball = toe_out(Vector((A_JOINT.x, -0.122, 0.024)))
    toe_tip = toe_out(Vector((A_JOINT.x, -0.198, 0.024)))
    fwd, back, up = Vector((0, -1, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    centre = [
        ("root", Vector((0, 0, 0)), Vector((0, 0.25, 0)), None, up),
        ("hips", Vector((0, 0.008, 0.915)), Vector((0, 0.006, 1.03)), "root", fwd),
        ("spine", Vector((0, 0.006, 1.03)), Vector((0, 0.002, 1.17)), "hips", fwd),
        ("chest", Vector((0, 0.002, 1.17)), Vector((0, 0.010, 1.445)), "spine", fwd),
        ("neck", Vector((0, 0.010, 1.445)), Vector((0, 0.014, 1.535)), "chest", fwd),
        ("head", Vector((0, 0.014, 1.535)), head_xf(Vector((0, 0.014, 1.76))), "neck", fwd),
    ]
    left = [
        ("shoulder.L", Vector((0.022, -0.004, 1.432)), Vector((0.165, 0.008, 1.418)), "chest",
         up),
        ("upper_arm.L", S_JOINT, E_JOINT, "shoulder.L", back),
        ("forearm.L", E_JOINT, W_JOINT, "upper_arm.L", back),
        ("hand.L", W_JOINT, W_JOINT + d3 * 0.088, "forearm.L", hand_v),
        ("thigh.L", H_JOINT, K_JOINT, "hips", fwd),
        ("shin.L", K_JOINT, A_JOINT, "thigh.L", fwd),
        ("foot.L", A_JOINT, ball, "shin.L", up),
        ("toe.L", ball, toe_tip, "foot.L", up),
    ]
    for name, pts in finger_joints().items():
        for k in range(3):
            left.append((f"{name}.{k + 1:02d}.L", pts[k], pts[k + 1],
                         "hand.L" if k == 0 else f"{name}.{k:02d}.L", hand_v))
    return centre, left


def mirror_name(n):
    return n[:-2] + ".R" if n.endswith(".L") else n


def build_armature():
    arm_data = bpy.data.armatures.new("Human_Rig")
    arm_data.display_type = "OCTAHEDRAL"
    rig = bpy.data.objects.new("Human_Rig", arm_data)
    CHAR_COLL.objects.link(rig)
    rig.show_in_front = True
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_data.edit_bones
    centre, left = bone_specs()
    specs = list(centre)
    for name, h, t, par, roll in left:
        specs.append((name, h, t, par, roll))
        mx = Vector((-1, 1, 1))
        specs.append((mirror_name(name), h * mx, t * mx, mirror_name(par) if par else None,
                      roll * mx))
    for name, h, t, par, roll in specs:
        b = eb.new(name)
        b.head, b.tail = Vector(h), Vector(t)
        b.align_roll(Vector(roll))
    for name, h, t, par, roll in specs:
        if par:
            b = eb[name]
            b.parent = eb[par]
            b.use_connect = (b.head - eb[par].tail).length < 1e-5
    eb["root"].use_deform = False
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig


def skin_to_rig(rig, body, hair):
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    # the ears are separate shells the heat solver can't reach: they ride on the head
    parts = body.data.attributes["part"].data
    ears = [i for i in range(len(parts)) if parts[i].value == PART_EAR]
    body.vertex_groups["head"].add(ears, 1.0, "REPLACE")
    # safety net: any other vertex the heat solver missed follows its nearest bone
    groups = {g.index: g for g in body.vertex_groups}
    bones = [(b.name, b.head_local, b.tail_local) for b in rig.data.bones if b.use_deform]
    missed = 0
    for v in body.data.vertices:
        if sum(g.weight for g in v.groups if g.group in groups) > 1e-4:
            continue
        missed += 1
        best = min(bones, key=lambda b: seg_dist(v.co, b[1], b[2]))
        vg = body.vertex_groups.get(best[0]) or body.vertex_groups.new(name=best[0])
        vg.add([v.index], 1.0, "REPLACE")
    if missed:
        print(f"[human] {missed} vertices fell back to nearest-bone weights")
    smooth_weights(body, factor=0.5, iterations=3, limit=4)
    # the hair rides rigidly on the head
    vg = hair.vertex_groups.new(name="head")
    vg.add(list(range(len(hair.data.vertices))), 1.0, "REPLACE")
    hair.parent = rig
    mod = hair.modifiers.new("Armature", "ARMATURE")
    mod.object = rig


def smooth_weights(ob, factor=0.5, iterations=3, limit=4):
    """Blur the skin weights along mesh edges so joints fold softly instead of
    creasing, then keep the strongest `limit` influences per vertex (game engines
    usually allow 4) and normalise."""
    me = ob.data
    nbrs = [[] for _ in me.vertices]
    for e in me.edges:
        a, b = e.vertices
        nbrs[a].append(b)
        nbrs[b].append(a)
    w = [{g.group: g.weight for g in v.groups} for v in me.vertices]
    for _ in range(iterations):
        new = []
        for i, wi in enumerate(w):
            if not nbrs[i]:
                new.append(wi)
                continue
            avg = {}
            for j in nbrs[i]:
                for g, x in w[j].items():
                    avg[g] = avg.get(g, 0.0) + x
            k = 1.0 / len(nbrs[i])
            out = {g: (1 - factor) * x for g, x in wi.items()}
            for g, x in avg.items():
                out[g] = out.get(g, 0.0) + factor * x * k
            new.append(out)
        w = new
    groups = list(ob.vertex_groups)
    for i, wi in enumerate(w):
        best = sorted(wi.items(), key=lambda kv: -kv[1])[:limit]
        best = [(g, x) for g, x in best if x > 1e-3]
        tot = sum(x for _, x in best) or 1.0
        for vg in groups:
            vg.remove([i])
        for g, x in best:
            groups[g].add([i], x / tot, "REPLACE")


def seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-12)))
    return (a + ab * t - p).length


def rotate_bone(rig, name, axis, deg):
    """Rotate a pose bone about a world-space axis through its head."""
    pb = rig.pose.bones[name]
    head = rig.matrix_world @ pb.head
    rot = (Matrix.Translation(head) @ Matrix.Rotation(math.radians(deg), 4, Vector(axis))
           @ Matrix.Translation(-head))
    pb.matrix = rig.matrix_world.inverted() @ rot @ rig.matrix_world @ pb.matrix
    bpy.context.view_layer.update()


def bend_towards(rig, name, target_dir, deg):
    pb = rig.pose.bones[name]
    v = (pb.tail - pb.head).normalized()
    axis = v.cross(Vector(target_dir))
    if axis.length > 1e-6:
        rotate_bone(rig, name, axis.normalized(), deg)


def relaxed_pose(rig):
    """Arms down by the sides, a soft bend in the elbows, a slight lean and head turn.
    The legs are left alone so both feet stay planted on the ground."""
    for pb in rig.pose.bones:
        pb.rotation_mode = "QUATERNION"
    for side, sx in (("L", 1), ("R", -1)):
        rotate_bone(rig, f"shoulder.{side}", (0, 1, 0), 6 * sx)
        rotate_bone(rig, f"upper_arm.{side}", (0, 1, 0), 26 * sx)
        rotate_bone(rig, f"upper_arm.{side}", (1, 0, 0), -6)
        bend_towards(rig, f"forearm.{side}", (0, -1, 0), 14)
        rotate_bone(rig, f"hand.{side}", (0, 0, 1), -8 * sx)
    rotate_bone(rig, "spine", (0, 1, 0), 1.0)
    rotate_bone(rig, "chest", (0, 1, 0), 1.0)
    rotate_bone(rig, "head", (1, 0, 0), -2.0)
    rotate_bone(rig, "head", (0, 0, 1), 4.0)


def clear_pose(rig):
    for pb in rig.pose.bones:
        pb.location = (0, 0, 0)
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.rotation_euler = (0, 0, 0)
        pb.scale = (1, 1, 1)
    bpy.context.view_layer.update()


# ==========================================================================
# Build everything
# ==========================================================================
half = build_body()
body = half.mirrored_x().build("Human_Body", BODY_MATS, smooth_angle=80)
face_uvs(body)
hair = build_hair(body)
rig = build_armature()
skin_to_rig(rig, body, hair)
relaxed_pose(rig)
build_pedestal()
setup_world()
setup_lights()
cam = setup_camera()
setup_render()

tri = 0
for o in (body, hair):
    tri += sum(len(p.vertices) - 2 for p in o.data.polygons)
print(f"[human] character: {len(body.data.vertices) + len(hair.data.vertices)} verts, "
      f"{tri} triangles")

# --------------------------------------------------------------------------
# Save / export
# --------------------------------------------------------------------------
face_img.pack()
aim_camera(cam, -30, 8, 4.7, (0, 0, 0.88))
bpy.context.preferences.filepaths.save_version = 0     # no .blend1 backups
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(MODEL_DIR, "human_lowpoly.blend"),
                            compress=True)


def select_only(objs, active):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active


# rigged formats are written in the rest (A-) pose
clear_pose(rig)
select_only((rig, body, hair), rig)
bpy.ops.export_scene.gltf(filepath=os.path.join(MODEL_DIR, "human_lowpoly.glb"),
                          export_format="GLB", use_selection=True, export_apply=True,
                          export_skins=True, export_animations=False)
try:
    bpy.ops.export_scene.fbx(filepath=os.path.join(MODEL_DIR, "human_lowpoly.fbx"),
                             use_selection=True, path_mode="COPY", embed_textures=True,
                             apply_scale_options="FBX_SCALE_ALL", add_leaf_bones=False,
                             bake_anim=False)
except Exception as e:   # pragma: no cover
    print("[human] FBX export failed:", e)

# the OBJ is a static mesh, so give it the relaxed pose from the renders
relaxed_pose(rig)
select_only((body, hair), body)
try:
    bpy.ops.wm.obj_export(filepath=os.path.join(MODEL_DIR, "human_lowpoly.obj"),
                          export_selected_objects=True, apply_modifiers=True,
                          export_materials=True, path_mode="RELATIVE",
                          forward_axis="NEGATIVE_Z", up_axis="Y")
except Exception as e:   # pragma: no cover
    print("[human] OBJ export failed:", e)


# --------------------------------------------------------------------------
# Renders
# --------------------------------------------------------------------------
def add_wire_overlay(objs):
    """Copies of the character drawn as thin dark edges, to show the topology."""
    make_mat("Wire", "1C2026", rough=0.9)
    wires = []
    for ob in objs:
        w = ob.copy()
        w.data = ob.data.copy()
        w.data.materials.clear()
        w.data.materials.append(MATS["Wire"])
        w.name = ob.name + "_Wire"
        CHAR_COLL.objects.link(w)
        mod = w.modifiers.new("Wire", "WIREFRAME")
        mod.thickness = 0.0014
        mod.offset = 1.0
        mod.use_even_offset = True
        mod.use_replace = True
        w.hide_render = True
        wires.append(w)
    return wires


VIEWS = {
    "front": (0, 6, 4.7, (0, 0, 0.88)),
    "three_quarter": (-32, 9, 4.7, (0, 0, 0.88)),
    "side": (-90, 6, 4.7, (0, 0, 0.88)),
    "back": (160, 10, 4.7, (0, 0, 0.88)),
    "portrait": (-20, 4, 1.25, (0, 0, 1.56)),
    "wireframe": (-32, 9, 4.7, (0, 0, 0.88)),
}

if DO_RENDER:
    wires = add_wire_overlay((body, hair))
    for name, (az, el, dist, tgt) in VIEWS.items():
        if ONLY_VIEWS and name not in ONLY_VIEWS:
            continue
        for w in wires:
            w.hide_render = name != "wireframe"
        aim_camera(cam, az, el, dist, tgt)
        SCENE.render.filepath = os.path.join(RENDER_DIR, f"human_{name}.png")
        bpy.ops.render.render(write_still=True)
        print("[human] rendered", name)
    for w in wires:
        w.hide_render = True

if DO_TURNTABLE:
    from PIL import Image

    frames = []
    r = SCENE.render
    r.resolution_x, r.resolution_y = (300, 400) if QUICK else (480, 640)
    SCENE.cycles.samples = 16 if QUICK else 48
    tmp = os.path.join(RENDER_DIR, "_turntable_frame.png")
    n = 36
    for i in range(n):
        aim_camera(cam, -360.0 * i / n, 8, 4.7, (0, 0, 0.88))
        r.filepath = tmp
        bpy.ops.render.render(write_still=True)
        frames.append(Image.open(tmp).convert("RGB").copy())
    os.remove(tmp)
    pal = [f.quantize(colors=200, method=Image.Quantize.MEDIANCUT) for f in frames]
    pal[0].save(os.path.join(RENDER_DIR, "human_turntable.gif"), save_all=True,
                append_images=pal[1:], duration=80, loop=0, optimize=True)
    print("[human] rendered turntable")
