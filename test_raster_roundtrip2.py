"""Round-trip check for the letter-F and gradient-circle test patterns
before printing them for real."""

from raster import build_letter_F, build_gradient_circle, image_to_raster, decode_raster

for name, img in [("letter_F", build_letter_F(cell=8)), ("gradient", build_gradient_circle(size=64))]:
    command, w, h = image_to_raster(img)
    decoded = decode_raster(command)
    decoded.resize((w * 4, h * 4)).save(f"scratch_{name}_big.png")
    print(f"{name}: {img.size} -> encoded {len(command)} bytes, decoded {decoded.size}")
