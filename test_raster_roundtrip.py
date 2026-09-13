"""Local self-check for raster.py - no printer involved.
Encodes a test pattern, decodes it back, and verifies pixel-for-pixel that
the round trip is lossless. Also saves the original and decoded images so
they can be inspected visually.
"""

from PIL import Image, ImageOps

from raster import build_test_pattern, image_to_raster, decode_raster

img = build_test_pattern(cols=5, rows=3, block=8)
img.save("scratch_original.png")
print(f"original size: {img.size}")

command, padded_w, h = image_to_raster(img)
print(f"encoded: {len(command)} bytes total, padded_width={padded_w}, height={h}")

decoded = decode_raster(command)
decoded.save("scratch_decoded.png")
print(f"decoded size: {decoded.size}")

# Pad the original the same way the encoder does, for a fair pixel compare.
padded_original = Image.new("L", (padded_w, h), 255)
padded_original.paste(img, (0, 0))
padded_original = padded_original.point(lambda p: 0 if p < 128 else 255)

diff = ImageOps.invert(padded_original.convert("L")) if False else None
mismatches = sum(
    1 for y in range(h) for x in range(padded_w)
    if padded_original.getpixel((x, y)) != decoded.getpixel((x, y))
)
print(f"mismatched pixels: {mismatches} / {padded_w * h}")
print("ROUND TRIP OK" if mismatches == 0 else "ROUND TRIP MISMATCH")
