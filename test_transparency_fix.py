"""Local check for the transparent-background bug: builds an RGBA image with
a black shape on a fully-transparent (but RGB=black) background - matching
how many exported logo PNGs/WEBPs actually look - and confirms
prepare_image_for_print() now composites onto white instead of printing the
whole background as solid black."""

import io

from PIL import Image

from template_core import prepare_image_for_print

# Simulate a typical exported transparent logo: RGB is black everywhere
# (including the "empty" area), alpha=0 outside the shape, alpha=255 inside it.
img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
px = img.load()
for y in range(30, 70):
    for x in range(30, 70):
        px[x, y] = (0, 0, 0, 255)  # the actual logo shape, opaque black

buf = io.BytesIO()
img.save(buf, format="PNG")

result = prepare_image_for_print(buf.getvalue())
result.save("scratch_transparency_fixed.png")

# Sanity: corners (background) should be white/near-white, center should be black.
corner = result.getpixel((5, 5))
center = result.getpixel((50, 50))
print(f"corner (should be white/255): {corner}")
print(f"center (should be black/0): {center}")
print("PASS" if corner != 0 and center == 0 else "FAIL")
