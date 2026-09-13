"""Physical test print #3: just the gradient circle, printed bigger (128px
instead of 64) so the dithering is actually visible to a phone camera, plus
a delay before the cut command in case the printer was still catching up on
the raster data (large bitmaps take real time to print; a cut command that
arrives while it's still busy may get dropped or garbled)."""

import time

from escpos.printer import Network

from raster import build_gradient_circle, image_to_raster

img = build_gradient_circle(size=128)
command, w, h = image_to_raster(img)
print(f"sending GRADIENT CIRCLE: {w}x{h} ({len(command)} bytes)")

p = Network("192.168.1.83", port=9100, profile="TM-T88III")
p._raw(b"\x1b\x40")      # init
p._raw(b"\x1b\x61\x01")  # center
p.text("GRADIENT CIRCLE (128px)\n")
p._raw(command)
p.text("\n\n\n\n\n\n")   # generous feed past the print head to the cutter

time.sleep(1.5)           # let the printer actually finish before cutting
p._raw(b"\x1d\x56\x00")  # cut
p.close()
print("Sent.")
