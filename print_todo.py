from escpos.printer import Network
from datetime import datetime

p = Network("192.168.1.83", port=9100, profile="TM-T88III")

# Initialize
p._raw(b'\x1b\x40')

# Header: center + bold + double size
p._raw(b'\x1b\x61\x01')       # center
p._raw(b'\x1b\x45\x01')       # bold on
p._raw(b'\x1d\x21\x11')       # double width + height
p.text("TO DO\n")
p._raw(b'\x1d\x21\x00')       # normal size
p._raw(b'\x1b\x45\x00')       # bold off

# Date
now = datetime.now().strftime("%a %b %d, %Y")
p.text(f"{now}\n")
p.text("------------------------\n")

# Left align for items
p._raw(b'\x1b\x61\x00')       # left

items = [
    "pack clothes",
    "take a shower",
    "charge the jumpstarter",
    "pack two cig packs",
]

for item in items:
    p.text(f"[ ] {item}\n")

p.text("\n\n")

# Cut
p._raw(b'\x1d\x56\x00')

p.close()
print("Done!")
