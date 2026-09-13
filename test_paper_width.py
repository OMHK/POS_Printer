"""Physical test print to verify the printer's actual dot width, since
MAX_IMAGE_WIDTH=384 in template_core.py was a guess (58mm paper convention)
rather than a measurement. Prints solid black bars at three candidate
widths, left-aligned, each labeled - whichever bar's physical width (measure
with a ruler) matches "dots / 8 dots-per-mm" confirms the real max, and any
bar that gets clipped/wrapped tells us we went too wide.
"""

import time

from escpos.printer import Network
from PIL import Image

from raster import image_to_raster

WIDTHS = [384, 448, 576]

p = Network("192.168.1.83", port=9100, profile="TM-T88III")
p._raw(b"\x1b\x40")      # init
p._raw(b"\x1b\x61\x00")  # left align

for w in WIDTHS:
    img = Image.new("L", (w, 12), 0)  # solid black bar
    command, padded_w, h = image_to_raster(img)
    mm_if_8dpm = padded_w / 8
    print(f"sending {padded_w} dots wide bar (~{mm_if_8dpm:.1f}mm if 8 dots/mm)")
    p.text(f"{padded_w} dots wide:\n")
    p._raw(command)
    p.text("\n")

p.text("\n\n\n\n\n\n")
time.sleep(1.5)
p._raw(b"\x1d\x56\x00")  # cut
p.close()
print("Sent. Measure each bar's actual width with a ruler.")
