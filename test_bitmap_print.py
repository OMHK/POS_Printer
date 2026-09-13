"""Physical test print for the GS v 0 raster encoder in raster.py.
Sends a 4x3 grid of 16px checkerboard blocks with a corner notch (same
pattern already verified correct via local round-trip decode) to the real
printer, to confirm the hardware renders it the same way.
"""

from escpos.printer import Network

from raster import build_test_pattern, image_to_raster

img = build_test_pattern(cols=4, rows=3, block=16)
command, w, h = image_to_raster(img)
print(f"sending {w}x{h} bitmap ({len(command)} bytes)")

p = Network("192.168.1.83", port=9100, profile="TM-T88III")
p._raw(b"\x1b\x40")          # init
p._raw(b"\x1b\x61\x01")      # center
p._raw(command)
p.text("\n")
p._raw(b"\x1d\x56\x00")      # cut
p.close()
print("Sent.")
