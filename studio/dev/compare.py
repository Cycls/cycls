"""Side-by-side of a viewport shot and a Cycles render + luminance stats per region."""
import sys
from PIL import Image, ImageStat
a, b, out = sys.argv[1], sys.argv[2], sys.argv[3]
va = Image.open(a).convert("RGB"); vb = Image.open(b).convert("RGB").resize(va.size, Image.LANCZOS)
w, h = va.size
side = Image.new("RGB", (w, h * 2)); side.paste(va, (0, 0)); side.paste(vb, (0, h)); side.save(out)
def lum(img, box):
    r = img.crop(box); s = ImageStat.Stat(r.convert("L")); return round(s.mean[0], 1)
boxes = {k: tuple(int(v * d) for v, d in zip(bx, (w, h, w, h))) for k, bx in {
  "all": (0, 0, 1, 1), "top": (0, 0, 1, .3), "floor": (0, .75, 1, 1),
  "pedestal": (.62, .45, .66, .65), "sphere": (.33, .52, .41, .64), "ring": (.63, .33, .67, .40)}.items()}
for k, bx in boxes.items(): print(f"{k:9s} viewport {lum(va, bx):6} cycles {lum(vb, bx):6}")
