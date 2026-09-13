"""Physical test print #2: block letter 'F' (unambiguous orientation test)
and a dithered gradient circle (real-photo-style stress test), both already
verified correct via local round-trip decode."""

from escpos.printer import Network

from raster import build_letter_F, build_gradient_circle, image_to_raster

p = Network("192.168.1.83", port=9100, profile="TM-T88III")
p._raw(b"\x1b\x40")      # init
p._raw(b"\x1b\x61\x01")  # center

for label, img in [("LETTER F", build_letter_F(cell=8)), ("GRADIENT CIRCLE", build_gradient_circle(size=64))]:
    command, w, h = image_to_raster(img)
    print(f"sending {label}: {w}x{h} ({len(command)} bytes)")
    p.text(f"{label}\n")
    p._raw(command)
    p.text("\n\n")

p.text("\n\n\n\n")        # extra feed so the cutter clears the printed content
p._raw(b"\x1d\x56\x00")  # cut
p.close()
print("Sent.")
