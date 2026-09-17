"""
Shared template-loading and printing logic for the Posiflex PP-6900 apps
(template_print.py CLI, template_gui.py GUI, app.py web app). See CLAUDE.md
for the hardware/protocol background these commands are based on.
"""

import io
import json
import time
from datetime import datetime
from pathlib import Path

from escpos.constants import QR_ECLEVEL_M
from escpos.printer import Network
from PIL import Image

from raster import image_to_raster

PRINTER_HOST = "192.168.1.83"
PRINTER_PORT = 9100
LINE_WIDTH = 42  # chars per line at default (non-double) size - measured 2026-09-14, see CLAUDE.md
MAX_IMAGE_WIDTH = 512  # dots (64mm) - measured print head max, see CLAUDE.md

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Column layout for "line_items" - Name | Qty | Price | Total, sized to fit
# exactly in LINE_WIDTH with single-space gaps between columns.
LI_QTY_W, LI_PRICE_W, LI_TOTAL_W = 3, 7, 7
LI_NAME_W = LINE_WIDTH - LI_QTY_W - LI_PRICE_W - LI_TOTAL_W - 3  # 3 single-space gaps

# Known-working raw ESC/POS commands (see CLAUDE.md) - do not use p.set(),
# it's unreliable on this printer/library combination.
INIT = b"\x1b\x40"
BOLD_ON, BOLD_OFF = b"\x1b\x45\x01", b"\x1b\x45\x00"
ALIGN = {"left": b"\x1b\x61\x00", "center": b"\x1b\x61\x01", "right": b"\x1b\x61\x02"}
DOUBLE_ON, DOUBLE_OFF = b"\x1d\x21\x11", b"\x1d\x21\x00"
CUT = b"\x1d\x56\x00"


def load_templates():
    templates = []
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            templates.append(json.load(f))
    return templates


def _li_row(name, qty, price, total):
    """Format one line-items row (or header) into the fixed 4-column layout."""
    return f"{str(name)[:LI_NAME_W]:<{LI_NAME_W}} {str(qty):>{LI_QTY_W}} {price:>{LI_PRICE_W}} {total:>{LI_TOTAL_W}}"


def table_column_widths(columns):
    """columns: list of str, or {"label":, "width":} dicts for an explicit width.
    Returns a list of ints that always sums (with the N-1 single-space gaps
    between them) to exactly LINE_WIDTH - unspecified columns split whatever
    space is left evenly, so a "table" element never leaves the blank-margin
    gap the LINE_WIDTH=32 bug caused (see CLAUDE.md)."""
    n = len(columns)
    explicit = {i: c["width"] for i, c in enumerate(columns) if isinstance(c, dict) and "width" in c}
    remaining = LINE_WIDTH - (n - 1) - sum(explicit.values())
    auto = [i for i in range(n) if i not in explicit]
    widths = [0] * n
    for i, w in explicit.items():
        widths[i] = w
    if auto:
        base, extra = divmod(remaining, len(auto))
        for j, i in enumerate(auto):
            widths[i] = base + (extra if j == len(auto) - 1 else 0)
    return widths


def _table_row(widths, cells):
    parts = [f"{str(c)[:w]:<{w}}" for w, c in zip(widths, cells)]
    return " ".join(parts)


def items_total(items):
    total = 0
    for it in items:
        try:
            total += float(it.get("qty", 0)) * float(it.get("price", 0))
        except (TypeError, ValueError):
            pass
    return total


def resolve_default(default):
    if default == "today":
        return datetime.now().strftime("%a %b %d, %Y")
    if default == "now":
        return datetime.now().strftime("%I:%M %p")
    return default or ""


def build_lines(template, values, styles=None):
    """values: {field_name: str} for "field", "qr" and "barcode" elements,
               {list_name: [str, ...]} for "list" / "numbered_list" elements,
               {image_name: bytes} raw image file bytes for "image" elements,
               {table_name: [[cell, cell, ...], ...]} one row list per row for "table" elements.
    styles: optional list, aligned by index with template["elements"], of
            {"align":, "bold":, "double":} overrides for that element (used by
            the web app's per-line formatting toolbar). None/{} entries fall
            back to the template's own formatting. Ignored for "image"/"qr"/"barcode".
    Returns an ordered list of print ops, each a dict:
      {"kind": "text", "text": str, "align":, "bold":, "double":}
      {"kind": "image", "bytes": raw image bytes, "align":}

    Supported element types:
      text           — static text line (bold/double/align from element)
      field          — user-supplied single-line value
      list           — user-supplied multi-line list with optional prefix
      numbered_list  — like list but auto-prefixed with "1. ", "2. ", ...
      section_header — bold left-aligned subheading (text from element["text"])
      divider        — dashed rule (--- * LINE_WIDTH)
      thick_divider  — heavy rule (=== * LINE_WIDTH)
      spacer         — N blank lines
      auto           — auto-filled value from element["default"] ("today"/"now"/literal)
      image          — user-supplied image, rendered via raster.py (GS v 0)
      qr             — user-supplied text/URL, rendered as a native QR code
      barcode        — user-supplied code, rendered via element["bc_type"] (default CODE128)
      line_items     — user-supplied [{"name","qty","price"}, ...], rendered as a
                       4-column Name/Qty/Price/Total table with a header row
      auto_total     — grand total computed from a "line_items" element's values,
                       referenced by element["items_name"]
      table          — user-defined columns (element["columns"]: list of str, or
                       {"label","width"} dicts for an explicit column width),
                       user-supplied rows (values[name]: list of row lists,
                       one cell per column) added/removed freely at fill time.
                       Column widths auto-split evenly to fill LINE_WIDTH exactly.
    """
    styles = styles or []
    ops = []
    for i, element in enumerate(template["elements"]):
        etype = element["type"]
        style = (styles[i] if i < len(styles) else None) or {}
        default_bold = element.get("bold", etype == "section_header")
        align = style.get("align", element.get("align", "left"))
        bold = style.get("bold", default_bold)
        double = style.get("double", element.get("double", False))

        if etype == "text":
            ops.append({"kind": "text", "text": element["text"], "align": align, "bold": bold, "double": double})

        elif etype == "field":
            value = values.get(element["name"], "")
            if value:
                ops.append({"kind": "text", "text": value, "align": align, "bold": bold, "double": double})

        elif etype == "list":
            prefix = element.get("prefix", "")
            for item in values.get(element["name"], []):
                ops.append({"kind": "text", "text": f"{prefix}{item}", "align": align, "bold": bold, "double": double})

        elif etype == "numbered_list":
            for n, item in enumerate(values.get(element["name"], []), 1):
                ops.append({"kind": "text", "text": f"{n}. {item}", "align": align, "bold": bold, "double": double})

        elif etype == "section_header":
            ops.append({"kind": "text", "text": element["text"], "align": align, "bold": bold, "double": double})

        elif etype == "divider":
            ops.append({"kind": "text", "text": "-" * LINE_WIDTH, "align": "left", "bold": False, "double": False})

        elif etype == "thick_divider":
            ops.append({"kind": "text", "text": "=" * LINE_WIDTH, "align": "left", "bold": False, "double": False})

        elif etype == "spacer":
            for _ in range(element.get("lines", 1)):
                ops.append({"kind": "text", "text": "", "align": "left", "bold": False, "double": False})

        elif etype == "auto":
            value = resolve_default(element.get("default", ""))
            if value:
                ops.append({"kind": "text", "text": value, "align": align, "bold": bold, "double": double})

        elif etype == "image":
            img_bytes = values.get(element["name"])
            if img_bytes:
                ops.append({"kind": "image", "bytes": img_bytes, "align": align})

        elif etype == "qr":
            value = values.get(element["name"], "")
            if value:
                ops.append({"kind": "qr", "data": value, "align": align})

        elif etype == "barcode":
            value = values.get(element["name"], "")
            if value:
                ops.append({"kind": "barcode", "data": value, "align": align, "bc_type": element.get("bc_type", "CODE128")})

        elif etype == "line_items":
            items = values.get(element["name"], [])
            if items:
                header = _li_row("Item", "Qty", "Price", "Total")
                ops.append({"kind": "text", "text": header, "align": "left", "bold": True, "double": False})
                for it in items:
                    name = it.get("name", "")
                    if not name:
                        continue
                    try:
                        qty = float(it.get("qty", 0))
                        price = float(it.get("price", 0))
                    except (TypeError, ValueError):
                        qty, price = 0, 0
                    qty_display = str(int(qty)) if qty == int(qty) else f"{qty:g}"
                    row = _li_row(name, qty_display, f"{price:.2f}", f"{qty * price:.2f}")
                    ops.append({"kind": "text", "text": row, "align": "left", "bold": False, "double": False})

        elif etype == "auto_total":
            items = values.get(element["items_name"], [])
            total = items_total(items)
            label = element.get("label", "TOTAL")
            text = f"{label:<{LINE_WIDTH - LI_TOTAL_W - 1}} {total:>{LI_TOTAL_W}.2f}"
            ops.append({"kind": "text", "text": text, "align": align, "bold": bold, "double": double})

        elif etype == "table":
            columns = element.get("columns", [])
            rows = [r for r in values.get(element["name"], []) if any(str(c).strip() for c in r)]
            if columns and rows:
                widths = table_column_widths(columns)
                labels = [c.get("label", "") if isinstance(c, dict) else str(c) for c in columns]
                ops.append({"kind": "text", "text": _table_row(widths, labels), "align": "left", "bold": True, "double": False})
                for row in rows:
                    cells = (list(row) + [""] * len(columns))[:len(columns)]
                    ops.append({"kind": "text", "text": _table_row(widths, cells), "align": "left", "bold": False, "double": False})

    return ops


def prepare_image_for_print(raw_bytes, max_width=MAX_IMAGE_WIDTH):
    """Raw image file bytes -> 1-bit PIL Image, downscaled to fit the paper
    width if needed (aspect ratio preserved), dithered for print.

    Images with an alpha channel (logos exported as transparent PNG/WEBP)
    must be composited onto a white background before dropping to grayscale -
    PIL's .convert("L") ignores alpha and keeps whatever RGB values sit
    underneath it, which for most transparent exports is (0, 0, 0). Skipping
    this step prints the entire transparent area as solid black.
    """
    img = Image.open(io.BytesIO(raw_bytes))
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(background, img)
    img = img.convert("L")
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, max(1, round(img.height * ratio))))
    return img.convert("1")


def print_lines(lines):
    p = Network(PRINTER_HOST, port=PRINTER_PORT, profile="TM-T88III")
    p._raw(INIT)
    current_align = "left"
    p._raw(ALIGN[current_align])
    printed_image = False

    try:
        for op in lines:
            align = op["align"]
            if align != current_align:
                p._raw(ALIGN[align])
                current_align = align

            if op["kind"] == "text":
                if op["bold"]:
                    p._raw(BOLD_ON)
                if op["double"]:
                    p._raw(DOUBLE_ON)

                p.text(f"{op['text']}\n")

                if op["double"]:
                    p._raw(DOUBLE_OFF)
                if op["bold"]:
                    p._raw(BOLD_OFF)

            elif op["kind"] == "image":
                img = prepare_image_for_print(op["bytes"])
                command, _, _ = image_to_raster(img)
                p._raw(command)
                p.text("\n")
                printed_image = True

            elif op["kind"] == "qr":
                # native=True sends raw GS ( k commands (same reliability class as
                # raster.py) - align comes from our own ALIGN switch above, not the
                # library's center= param, which isn't implemented for native mode.
                p.qr(op["data"], native=True, size=6, ec=QR_ECLEVEL_M)
                printed_image = True

            elif op["kind"] == "barcode":
                data = op["data"]
                if op["bc_type"] in ("CODE128", "GS1-128") and not data[:2] in ("{A", "{B", "{C"):
                    # CODE128 requires a subset-selector prefix ({A/{B/{C) per the ESC/POS
                    # spec - {B (subset B, printable ASCII) covers the common case.
                    data = "{B" + data
                p.barcode(data, op["bc_type"], height=64, width=2, pos="BELOW", align_ct=False)
                printed_image = True
    finally:
        # However this loop ends - success or a mid-job error (e.g. an invalid
        # barcode value) - always feed and cut so nothing is left dangling on
        # the roll for the next print job to run into.
        if printed_image:
            # A cut sent right after a large raster block can come out ragged if the
            # printer is still busy - give it feed margin and time (see CLAUDE.md).
            p.text("\n\n\n\n\n\n")
            time.sleep(1.5)
        p._raw(CUT)
        p.close()
