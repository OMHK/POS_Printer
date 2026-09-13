# Posiflex PP-6900 Printing Interface

A Posiflex PP-6900 thermal receipt printer, physically connected via USB to **HomeServer** (`192.168.1.83`), reachable from anywhere on the LAN as a plain network ESC/POS printer. This doc is the reference for printing to it — no need to re-derive any of this.

## How to print

Target: **`192.168.1.83:9100`** (raw TCP socket, ESC/POS protocol — the standard "raw/JetDirect" convention most POS software and printer libraries expect by default).

### From Python (recommended path)

```bash
pip install python-escpos
```

```python
from escpos.printer import Network

p = Network("192.168.1.83", port=9100, profile="TM-T88III")
p.text("Hello from Claude\n")
p.cut()
p.close()
```

### Known limitation: `.set()` formatting is unreliable

`p.set(bold=True, double_height=True, double_width=True, align="center")` does **not** reliably apply on this printer/library combination, even with an explicit `profile=`. Text prints, but stays plain/default-sized regardless. If bold or large text is genuinely needed, send raw ESC/POS bytes directly instead — this is confirmed working:

```python
p._raw(b'\x1b\x45\x01')   # bold on
p.text("Bold text\n")
p._raw(b'\x1b\x45\x00')   # bold off
```

Plain `p.text()` calls (no `.set()` styling) are fully reliable — use those whenever formatting isn't essential.

## Architecture (why TCP:9100 works, and why it's the right path)

- The printer connects to HomeServer via USB as a **CDC-ACM virtual serial device** (not USB-printer-class).
- A `socat` systemd service (`posiflex-bridge.service` on HomeServer, enabled — survives reboot) bridges `TCP:9100 → /dev/serial/by-id/usb-POSIFLEX_TECHNOLOGY_INC._PP-6900_Thermal_Printer_PPUSB0-if00`. **Do not** point this at a numbered `/dev/ttyACMx` path — HomeServer also has a 3D printer's Klipper controller on the same USB-serial class, and the numbering isn't stable across reconnects. A prior version hardcoded `/dev/ttyACM0` and silently started bridging to the Klipper board instead of the printer after a reconnect swapped the numbering — see `Printing_Closet_Setup.md` for the full incident.
- CUPS is **not** involved in this path at all — it's a direct raw socket. This matters because CUPS's ESC/POS driver for this printer is confirmed broken for graphics (see below); the raw socket path sidesteps that entirely.

## CUPS queues on HomeServer (alternate access — avoid unless you have a reason)

- `Posiflex_PP6900` — raw CUPS queue via the serial backend (`serial:/dev/ttyACM0?baud=9600`). Works, but offers nothing the TCP:9100 socket doesn't already do more simply.
- `Posiflex_PP6900_GUI` — CUPS queue using the `rastertoescpos` driver. **Confirmed broken for images/graphics** — produces garbled or transposed/diamond-pattern output. The printer itself *can* render bitmaps correctly (verified with hand-built raw `GS v 0` commands), so the bug is in this specific driver's command formatting, not the hardware. Don't use this queue for anything image-related. Prefer the raw TCP:9100 path for everything.

## Known-working ESC/POS command reference (empirically tested on this exact unit)

| Purpose | Bytes |
|---|---|
| Initialize | `\x1b\x40` |
| Bold on / off | `\x1b\x45\x01` / `\x1b\x45\x00` |
| Align center / left / right | `\x1b\x61\x01` / `\x1b\x61\x00` / `\x1b\x61\x02` |
| Double width+height on / off | `\x1d\x21\x11` / `\x1d\x21\x00` |
| Full cut | `\x1d\x56\x00` |

- **`ESC J n`** (dot-precise feed) — **unreliable on this firmware**. Sending a 480-dot feed produced only ~4.5mm of actual paper movement instead of the expected ~60mm. Avoid this command.
- **`ESC 3 n`** (custom line spacing) — **works correctly**, empirically calibrated with a caliper:
  - Default line spacing: **3.619mm/line**
  - `ESC 3 16` (`\x1b\x33\x10`): **0.9833mm/line** — reset to default with `ESC 2` (`\x1b\x32`)
  - Use this instead of `ESC J` for any precise vertical positioning needs.
- **Raster bitmap (`GS v 0`) — fixed and confirmed working.** The earlier transposition/diamond-pattern bug was in a hand-rolled encoder that packed pixel data column-major instead of row-major. The correct, verified-working encoder lives in `raster.py` (`image_to_raster()` / `decode_raster()`) in this project folder:
  - Format: `GS v 0 m xL xH yL yH d1...dk` — `m=0`, `xL/xH` = width **in bytes** (not pixels, little-endian 16-bit), `yL/yH` = height in dots (little-endian 16-bit), then `xL+xH*256` bytes per row, **row-major** (full row left-to-right, top row first), each byte 8 horizontal pixels **MSB-first**, bit=1 = print (black) dot. Width gets padded up to a multiple of 8.
  - Confirmed on real hardware with an asymmetric block letter "F" (correct orientation, not mirrored/rotated/transposed) and a 128px dithered gradient circle (clean radial dithering, no artifacts). A checkerboard alone is a weak test — it's symmetric under transpose, so it can pass even with an orientation bug; use an asymmetric shape instead.
  - **Cutter gotcha**: sending the cut command (`\x1d\x56\x00`) immediately after a large raster block can produce a ragged/torn cut instead of a clean one — the printer is likely still busy processing the bitmap. Fix: feed several blank lines *and* add a short delay (~1.5s) between the last raster write and the cut command. See `test_bitmap_print3.py` for a working example.
  - **Transparent-background gotcha**: a real logo (transparent PNG/WEBP) printed as a solid black rectangle - most exported transparent images leave RGB=(0,0,0) underneath the alpha=0 background, and `PIL.Image.convert("L")` drops alpha without compositing, so the "empty" area reads as black. Fix (already in `template_core.prepare_image_for_print()`): composite onto a white background first (`Image.alpha_composite`) whenever the source has an alpha channel, *then* convert to grayscale. Always test with a real transparent logo, not just synthetic opaque test patterns (the letter-F/gradient tests above didn't have alpha, so they didn't catch this).
  - **Max print width, measured**: the print head is **512 dots (64mm) wide at exactly 8 dots/mm**. Confirmed by printing solid bars at 384/448/576 requested dots and measuring with a caliper: 384→48.8mm and 448→56.2mm both match 8 dots/mm (no clipping), but 576 printed at only 64mm instead of the expected 72mm — the printer silently truncates any raster request wider than 512 dots rather than erroring or wrapping. `template_core.MAX_IMAGE_WIDTH = 512` reflects this; don't request wider raster images than that. See `test_paper_width.py` for the calibration print.
  - **Text width, measured**: default (non-double) font fits **42 characters per line**, not 32. The 32-char figure was an unverified guess inherited from the original (wrong) 384-dot print-width assumption, and was never re-checked after the 512-dot measurement above — it just silently underused ~1/4 of the paper's actual width for every divider and table for a while. Confirmed by printing `"{n}: " + "-"*n + "|"` for n=32/36/40/42/44/48 and finding exactly where it wraps: 36 fits (41 total chars on the line), 40+ all wrap with a remainder that consistently backs out to a 42-char line capacity. `template_core.LINE_WIDTH = 42` reflects this now. **Lesson**: dot-width and character-width are separate measurements — fixing one doesn't fix the other, re-verify both after any paper/font change.

## Label printing (60mm × 30mm labels, 2mm gap) — blocked, not abandoned

- No gap/black-mark sensor on this printer — label positioning was designed around calculated line-feed counts instead: **61 lines of content + 2 lines of gap**, both using `ESC 3 16` spacing (from the calibration above), giving ~0.05mm of drift per label — negligible over a realistic roll length.
- **Currently blocked**: the printer's paper sensor doesn't recognize the label roll as loaded paper at all (works fine with the continuous receipt roll). This is a hardware/sensor compatibility issue, not a software one — needs troubleshooting before label work can resume.
- If resumed: the positioning math above is already solved and doesn't need re-deriving.

## Other printers on HomeServer (unrelated to this interface — FYI only)

Samsung M2020 (laser) and Canon G3010 (inkjet) are also attached to HomeServer via CUPS, but were physically faulted as of last check (USB disconnect / E03 paper jam respectively) — not part of this printing setup and not affected by anything above.
