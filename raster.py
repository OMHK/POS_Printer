"""
GS v 0 raster bitmap encoding for the Posiflex PP-6900.

Previous attempts (see CLAUDE.md) got a working 8x8 test but a transposition/
bit-ordering bug when scaling up to a real image (checkerboard -> diamond
pattern). That symptom is consistent with packing the pixel data in the wrong
order - most likely column-major (all rows of byte-column 0, then all rows of
byte-column 1, ...) instead of the row-major order the command actually
expects (each full row left-to-right, top row first).

This module implements the encoding directly against the documented format:

    GS v 0 m xL xH yL yH d1...dk

    m       : 0 = normal (only mode used here)
    xL, xH  : width in BYTES (not pixels), little-endian 16-bit
    yL, yH  : height in pixels/dots, little-endian 16-bit
    d1..dk  : xL+xH*256 bytes per row, one row after another (row-major),
              each byte = 8 horizontal pixels, MSB = leftmost pixel,
              bit=1 means "print this dot" (black)

decode_raster() is the exact inverse, used to self-check the encoder locally
(round-trip) before spending paper on the physical printer.
"""

from PIL import Image

RASTER_CMD = b"\x1d\x76\x30"


def image_to_raster(img: Image.Image, threshold=128):
    """Returns (command_bytes, width_px, height_px) for GS v 0, mode 0.
    Width is padded up to a multiple of 8 (padding pixels are white)."""
    img = img.convert("L")
    width, height = img.size
    width_bytes = (width + 7) // 8
    padded_width = width_bytes * 8

    px = img.load()
    data = bytearray()
    for y in range(height):
        for bx in range(width_bytes):
            byte = 0
            for bit in range(8):
                x = bx * 8 + bit
                if x < width:
                    dot = px[x, y] < threshold  # dark pixel -> print
                else:
                    dot = False  # padding column, blank
                byte = (byte << 1) | (1 if dot else 0)
            data.append(byte)

    xL, xH = width_bytes & 0xFF, (width_bytes >> 8) & 0xFF
    yL, yH = height & 0xFF, (height >> 8) & 0xFF
    header = RASTER_CMD + bytes([0, xL, xH, yL, yH])
    return header + bytes(data), padded_width, height


def decode_raster(command_bytes, threshold_out=0):
    """Inverse of image_to_raster() - parses a full GS v 0 command and
    returns a PIL Image, for local self-verification (no printer needed)."""
    assert command_bytes[:3] == RASTER_CMD, "not a GS v 0 command"
    m = command_bytes[3]
    assert m == 0, f"only mode 0 supported, got {m}"
    xL, xH, yL, yH = command_bytes[4:8]
    width_bytes = xL + (xH << 8)
    height = yL + (yH << 8)
    data = command_bytes[8:]
    assert len(data) == width_bytes * height, (
        f"data length {len(data)} != width_bytes({width_bytes}) * height({height})"
    )

    width = width_bytes * 8
    img = Image.new("L", (width, height), 255)
    px = img.load()
    for y in range(height):
        for bx in range(width_bytes):
            byte = data[y * width_bytes + bx]
            for bit in range(8):
                x = bx * 8 + bit
                dot = (byte >> (7 - bit)) & 1
                px[x, y] = 0 if dot else 255
    return img


def build_letter_F(cell=8):
    """Block letter 'F' - unlike a checkerboard, this looks wrong under any
    flip, rotation, or transpose, so it's an unambiguous orientation test."""
    grid = [
        "1111111",
        "1000000",
        "1000000",
        "1000000",
        "1111110",
        "1000000",
        "1000000",
        "1000000",
        "1000000",
    ]
    cols, rows = len(grid[0]), len(grid)
    img = Image.new("L", (cols, rows), 255)
    px = img.load()
    for y, row in enumerate(grid):
        for x, bit in enumerate(row):
            px[x, y] = 0 if bit == "1" else 255
    return img.resize((cols * cell, rows * cell), Image.NEAREST)


def build_gradient_circle(size=64):
    """Radial gradient circle, dithered to 1-bit - a stress test closer to a
    real photo (arbitrary per-pixel bit patterns across multiple bytes per
    row), which is the scenario that originally triggered the bug."""
    img = Image.new("L", (size, size), 255)
    px = img.load()
    cx, cy, r = size / 2, size / 2, size / 2
    for y in range(size):
        for x in range(size):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            px[x, y] = 255 if d > r else int(255 * (d / r))
    return img.convert("1")  # Floyd-Steinberg dithering


def build_test_pattern(cols=4, rows=3, block=8, corner_marker=True):
    """cols x rows grid of `block`x`block` alternating squares (asymmetric
    grid, not a square image, so any row/column transposition is obvious).
    corner_marker adds a solid mark in the top-left block only, so any
    rotation/flip is also unambiguous."""
    width, height = cols * block, rows * block
    img = Image.new("L", (width, height), 255)
    px = img.load()
    for cy in range(rows):
        for cx in range(cols):
            black = (cx + cy) % 2 == 0
            if black:
                for y in range(cy * block, cy * block + block):
                    for x in range(cx * block, cx * block + block):
                        px[x, y] = 0
    if corner_marker:
        # 2px white notch cut into the top-left corner - breaks the symmetry
        # a checkerboard alone still has (rotation/transpose leaves a pure
        # checkerboard looking identical).
        for y in range(2):
            for x in range(2):
                px[x, y] = 255
    return img
