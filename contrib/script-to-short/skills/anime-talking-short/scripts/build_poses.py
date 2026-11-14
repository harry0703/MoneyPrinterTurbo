"""Prepare stage assets for render.py at the 1440x2560 stage size.
  poses/<name>/X.png        the pose at rest (its own closed mouth)
  poses/<name>/B..F.png     mouth patches (lips erased, new mouth), pasted at pose.json "box"
  poses/<name>/pose.json    {"face": [x, y, width], "box": [x0, y0] or null when the mouth is hidden}
  backgrounds/<name>.png
Usage: python build_poses.py SHEET POSES_IN BACKGROUNDS_IN OUT
       python build_poses.py --check SHEET      draws the calibration boxes on the sheet -> <sheet>-check.png
  SHEET: the two-figure character sheet (closed mouth left, open mouth right). Its pixel calibration is
  read from <sheet>.json (same name, .json); copy sheet.example.json and adjust it to your sheet.
  POSES_IN: waist-up pose images on flat green. Every name becomes a pose."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

CW, CH = 1440, 2560
# Calibration defaults; load_calibration() replaces them from <sheet>.json
BOX = (85, 100, 905, 1360)      # closed figure in the sheet; the coordinates below are inside it
MOUTH, FACE_UP, FACE_W = (410, 720), 120, 560  # closed lip line centre; face centre is FACE_UP above it; face width
TPL = (240, 610, 580, 870)      # mustache + lips + soul patch: what the mouth finder looks for
ART = (1290, 780, 1520, 900)    # the open figure's mouth in the sheet
SEED = (110, 52)                # a dark interior pixel of that mouth, ART coords
LIP, LINE, DARK = (172, 96, 80), (20, 10, 10), (67, 25, 28)
SHAPES = {"B": (0.90, 0.32), "C": (0.92, 0.55), "D": (0.96, 0.75), "E": (0.68, 0.60)}  # x, y scale of the art mouth
SS = 3                          # supersampling for smooth sprite edges


def pack(rest, shapes, face, out):
    """rest: RGBA stage-size image; shapes: {name: RGBA same size, lips redrawn}; face: [x, y, width]."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    assert rest.size == (CW, CH), rest.size
    rest.save(out / "X.png")
    meta = {"face": [round(v, 1) for v in face], "box": None}
    if shapes:
        base = np.asarray(rest).astype(np.int16)
        union = Image.new("L", rest.size, 0)
        for s in shapes.values():
            union = ImageChops.lighter(union, Image.fromarray((np.abs(np.asarray(s).astype(np.int16) - base).max(2) > 8).astype(np.uint8) * 255))
        x0, y0, x1, y1 = union.getbbox()
        box = (max(x0 - 16, 0), max(y0 - 16, 0), min(x1 + 16, CW), min(y1 + 16, CH))
        # soft-edged alpha: only where pixels changed, so a sub-pixel offset at render time leaves no seam
        soft = union.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(3)).crop(box)
        for name, img in shapes.items():
            patch = img.crop(box)
            patch.putalpha(ImageChops.multiply(soft, patch.getchannel("A")))
            patch.save(out / f"{name}.png")
        meta["box"] = list(box[:2])
    (out / "pose.json").write_text(json.dumps(meta))


def sprite(mask, content, lip=9, wrap=0.86):
    """Lip tint above and below + mouth content + a fresh outline of constant weight (scaling thins the art's own)."""
    pad = 16 * SS
    size = (mask.width + 2 * pad, mask.height + 2 * pad)
    m = Image.new("L", size, 0)
    m.paste(mask, (pad, pad))
    narrow = mask.resize((round(mask.width * wrap), mask.height))  # lips stop short of the mouth corners
    lips = Image.new("L", size, 0)
    lips.paste(narrow, (pad + (mask.width - narrow.width) // 2, pad))
    grown = lips.filter(ImageFilter.GaussianBlur(lip * SS)).point(lambda v: 255 if v > 40 else 0)  # round dilation by ~lip px
    out = Image.new("RGBA", size, LIP + (0,))
    out.putalpha(ImageChops.offset(grown, 0, 3 * SS).filter(ImageFilter.GaussianBlur(SS)))
    out.paste(content, (pad, pad), mask)
    out.paste(LINE, mask=ImageChops.subtract(m, m.filter(ImageFilter.MinFilter(2 * 6 * SS + 1))))
    return out.resize((size[0] // SS, size[1] // SS), Image.LANCZOS), pad // SS


def mouth_sprites(sheet):
    """{shape: (sprite RGBA, pad, height)} at sheet scale, cut from the open figure's mouth art."""
    art = sheet.crop(ART)
    g = art.convert("L").point(lambda v: 255 if v < 60 else 0)
    ImageDraw.floodfill(g, SEED, 128)
    outside = g.point(lambda v: 255 if v == 128 else 0)
    ImageDraw.floodfill(outside, (0, 0), 128)
    mask = outside.point(lambda v: 0 if v == 128 else 255)
    bbox = mask.getbbox()
    art, mask = art.crop(bbox), mask.crop(bbox)
    out = {}
    for name, (sx, sy) in SHAPES.items():
        size = (round(art.width * sx) * SS, round(art.height * sy) * SS)
        out[name] = sprite(mask.resize(size, Image.LANCZOS), art.resize(size, Image.LANCZOS)) + (size[1] // SS,)
    pucker = Image.new("L", (58 * SS, 36 * SS), 0)
    ImageDraw.Draw(pucker).ellipse((0, 0, 58 * SS - 1, 36 * SS - 1), fill=255)
    out["F"] = sprite(pucker, Image.new("RGB", pucker.size, DARK), lip=11, wrap=1.0) + (36,)
    return out


def odd(v):
    return max(3, int(round(v)) | 1)


def redraw_mouths(rest, mx, my, s, sprites):
    """Erase the lips at (mx, my) and draw each mouth shape; s = face scale relative to the sheet."""
    rgb = rest.convert("RGB")
    a = np.asarray(rgb).astype(int)
    pts = [a[int(my - 10 * s), int(mx + dx * s)] for dx in (-175, -160, 160, 175)]
    skin = tuple(int(v) for v in np.median(pts, 0))
    dark = rgb.convert("L").point(lambda v: 255 if v < 75 else 0)
    hair = dark.filter(ImageFilter.MinFilter(odd(11 * s))).filter(ImageFilter.MaxFilter(odd(11 * s)))  # mustache, beard
    erase = Image.new("L", rest.size, 0)
    ImageDraw.Draw(erase).ellipse((mx - 128 * s, my - 42 * s, mx + 128 * s, my + 48 * s), fill=255)
    erase = ImageChops.subtract(erase, hair.filter(ImageFilter.MaxFilter(odd(5 * s)))).filter(ImageFilter.GaussianBlur(1.2 * s))
    base = rest.copy()
    base.paste(skin + (255,), mask=erase)
    out = {}
    for name, (sp, pad, height) in sprites.items():
        sp = sp.resize((max(1, round(sp.width * s)), max(1, round(sp.height * s))), Image.LANCZOS)
        frame = base.copy()
        top = round(my - (0.38 * height + 4 + pad) * s)  # opens mostly downward from the closed lip line
        frame.alpha_composite(sp, (round(mx - sp.width / 2), max(0, top)))
        frame.paste(rest, mask=hair)  # mustache and soul patch stay in front of the lip tint
        out[name] = frame
    return out


def ncc(img, tpl):
    """Normalized cross-correlation of tpl over every valid position of img (FFT + integral images)."""
    th, tw = tpl.shape
    t = tpl - tpl.mean()
    t /= np.sqrt((t ** 2).sum()) + 1e-9
    corr = np.fft.irfft2(np.fft.rfft2(img) * np.conj(np.fft.rfft2(t, img.shape)), img.shape)
    hh, ww = img.shape[0] - th + 1, img.shape[1] - tw + 1
    def box(ii):
        return ii[th:th + hh, tw:tw + ww] - ii[:hh, tw:tw + ww] - ii[th:th + hh, :ww] + ii[:hh, :ww]
    ii = np.pad(img, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    ii2 = np.pad(img ** 2, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    var = box(ii2) - box(ii) ** 2 / (th * tw)
    return corr[:hh, :ww] / np.sqrt(np.maximum(var, 1e-3))


def find_mouth(rest, tpl):
    """-> (score, mouth x, mouth y, scale vs the sheet), searched on a half-size grey image."""
    flat = Image.new("RGB", rest.size, (128, 128, 128))
    flat.paste(rest, mask=rest.getchannel("A"))
    img = np.asarray(flat.convert("L").resize((CW // 2, CH // 2), Image.BILINEAR), np.float64)
    best = (-1, 0, 0, 1)
    for s in np.geomspace(0.6, 1.8, 22):  # waist-up poses: the face is never smaller than this
        w, h = round(tpl.width * s / 2), round(tpl.height * s / 2)
        if w < 16 or w >= img.shape[1] or h >= img.shape[0]:
            continue
        m = ncc(img, np.asarray(tpl.resize((w, h), Image.BILINEAR), np.float64))
        y, x = np.unravel_index(np.argmax(m), m.shape)
        if m[y, x] > best[0]:
            best = (float(m[y, x]), float(x * 2 + (MOUTH[0] - TPL[0]) * s), float(y * 2 + (MOUTH[1] - TPL[1]) * s), float(s))
    return best


def key_green(im):
    """Flat green screen -> alpha, with green spill pulled out of the edges."""
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    excess = g - np.maximum(r, b)
    alpha = np.clip(255 - (excess - 30) * 6, 0, 255).astype(np.uint8)
    a[..., 1] = np.where(excess > 0, np.maximum(r, b), g)  # despill
    out = Image.fromarray(a.astype(np.uint8)).convert("RGBA")
    out.putalpha(Image.fromarray(alpha).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8)))
    return out


def to_stage(im, mode="contain"):
    """Scale an image onto the 9:16 stage, bottom-centred (contain) or filling it (cover)."""
    s = (min if mode == "contain" else max)(CW / im.width, CH / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    c = Image.new(im.mode, (CW, CH), (0, 0, 0, 0) if im.mode == "RGBA" else 0)
    c.paste(im, ((CW - im.width) // 2, CH - im.height))
    return c


def load_calibration(sheet_path):
    cfg = Path(sheet_path).with_suffix(".json")
    if not cfg.exists():
        sys.exit(f"Missing {cfg}. Copy my/sheet.example.json there and set the boxes for your sheet (see README).")
    c = json.loads(cfg.read_text())
    keys = ("BOX", "MOUTH", "FACE_UP", "FACE_W", "TPL", "ART", "SEED", "LIP", "LINE", "DARK")
    globals().update({k: tuple(c[k]) if isinstance(c[k], list) else c[k] for k in keys if k in c})  # module constants are read by every step


def check(sheet_path):
    """Draw the calibration on the sheet so it can be eyeballed: BOX red, TPL yellow, MOUTH cyan dot, ART green, SEED magenta."""
    load_calibration(sheet_path)
    im = Image.open(sheet_path).convert("RGB")
    d = ImageDraw.Draw(im)
    bx, by = BOX[:2]
    d.rectangle(BOX, outline=(255, 0, 0), width=5)
    d.rectangle((bx + TPL[0], by + TPL[1], bx + TPL[2], by + TPL[3]), outline=(255, 220, 0), width=4)
    mx, my = bx + MOUTH[0], by + MOUTH[1]
    d.ellipse((mx - 8, my - 8, mx + 8, my + 8), fill=(0, 255, 255))
    d.line((mx - FACE_W / 2, my - FACE_UP, mx + FACE_W / 2, my - FACE_UP), fill=(0, 255, 255), width=4)  # face width, at face centre
    d.rectangle(ART, outline=(0, 255, 0), width=4)
    sx, sy = ART[0] + SEED[0], ART[1] + SEED[1]
    d.ellipse((sx - 6, sy - 6, sx + 6, sy + 6), fill=(255, 0, 255))
    out = Path(sheet_path).with_name(Path(sheet_path).stem + "-check.png")
    im.save(out)
    print(f"wrote {out}")


def main(sheet_path, poses_in, bgs_in, out):
    load_calibration(sheet_path)
    sheet = Image.open(sheet_path).convert("RGB")
    left = sheet.crop(BOX)
    tpl = left.crop(TPL).convert("L")
    sprites = mouth_sprites(sheet)
    out = Path(out)
    for p in sorted(Path(poses_in).iterdir()):
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        rest = to_stage(key_green(Image.open(p)))
        score, mx, my, s = find_mouth(rest, tpl)
        face = [mx, my - FACE_UP * s, FACE_W * s]
        if score < 0.45:  # mouth hidden (facepalm) or not found: the pose plays without lip-sync
            print(f"{p.stem}: no mouth found (score {score:.2f}); face position is a guess, check it")
            pack(rest, {}, [CW / 2, CH * 0.3, CW * 0.35], out / "poses" / p.stem)
            continue
        pack(rest, redraw_mouths(rest, mx, my, s, sprites), face, out / "poses" / p.stem)
        print(f"{p.stem}: mouth at ({mx:.0f}, {my:.0f}), scale {s:.2f}, score {score:.2f}")
    (out / "backgrounds").mkdir(parents=True, exist_ok=True)
    for p in sorted(Path(bgs_in).iterdir()) if bgs_in and Path(bgs_in).is_dir() else []:
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            to_stage(Image.open(p).convert("RGB"), "cover").save(out / "backgrounds" / f"{p.stem}.png")
            print(f"background {p.stem}")


if __name__ == "__main__":
    check(sys.argv[2]) if sys.argv[1:2] == ["--check"] else main(*sys.argv[1:5])
