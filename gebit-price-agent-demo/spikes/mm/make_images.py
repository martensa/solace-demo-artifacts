"""Generate synthetic test images for the multimodal probes (no real brands)."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)


def font(size):
    for p in ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/System/Library/Fonts/Helvetica.ttc"]:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


# 1) Competitor shelf price tag (as if photographed in another store)
img = Image.new("RGB", (1280, 720), (205, 200, 190))
d = ImageDraw.Draw(img)
d.rectangle([180, 160, 1100, 560], fill=(255, 230, 0), outline=(40, 40, 40), width=6)
d.text((220, 190), "FRISCHMARKT", font=font(40), fill=(180, 0, 0))
d.text((220, 250), "Bio Vollmilch 3,8% 1 l", font=font(52), fill=(0, 0, 0))
d.text((220, 330), "1,19 €", font=font(150), fill=(0, 0, 0))
d.text((780, 470), "1 l = 1,19 €", font=font(34), fill=(0, 0, 0))
d.text((220, 500), "Art.-Nr. 4000417 012345", font=font(28), fill=(60, 60, 60))
img = img.rotate(4, expand=False, fillcolor=(205, 200, 190))
img.save(out / "competitor_tag.jpg", quality=85)

# 2) Synthetic product "packshot" on a counter (stand-in for a webcam frame)
img = Image.new("RGB", (1280, 720), (90, 90, 95))
d = ImageDraw.Draw(img)
d.rectangle([0, 520, 1280, 720], fill=(150, 120, 90))
d.rectangle([470, 140, 810, 600], fill=(120, 60, 30), outline=(20, 20, 20), width=4)
d.text((500, 180), "KAFFEE", font=font(60), fill=(255, 240, 200))
d.text((500, 260), "CREMA", font=font(60), fill=(255, 240, 200))
d.text((500, 360), "ganze Bohne", font=font(36), fill=(255, 240, 200))
d.text((500, 520), "1 kg", font=font(48), fill=(255, 255, 255))
img.save(out / "product_frame.jpg", quality=80)

# 3) Electronic shelf label (ESL) after a price change
img = Image.new("RGB", (960, 540), (230, 230, 230))
d = ImageDraw.Draw(img)
d.rectangle([140, 120, 820, 420], fill=(250, 250, 250), outline=(30, 30, 30), width=8)
d.text((170, 140), "Kaffee Crema ganze Bohne 1 kg", font=font(34), fill=(0, 0, 0))
d.text((170, 200), "12,99", font=font(130), fill=(200, 0, 0))
d.text((560, 250), "€", font=font(80), fill=(200, 0, 0))
d.text((170, 360), "1 kg = 12,99 €   AKTION", font=font(30), fill=(0, 0, 0))
img.save(out / "esl_after.png")
print("ok")
