# Printing Closet — HomeServer Setup

Three printers, all USB-attached to **HomeServer** (`192.168.1.83`), all shared over the LAN via CUPS. This is the master reference — see the linked per-printer docs for deep troubleshooting history where noted.

## Overview

| Printer | Type | Queue name | Status |
|---|---|---|---|
| Samsung M2020 Series | Mono laser | `Samsung_M2020_Series` | Working — see `Samsung_M2020_Printer_Notes.md` |
| Canon G3010 series | Inkjet (MegaTank) | `Canon_G3010_series` | Working |
| Posiflex PP-6900 | Thermal receipt printer | `Posiflex_PP6900` | Working — see `CLAUDE.md` (Posiflex printing interface) |

CUPS admin/web UI: `https://192.168.1.83:631` (self-signed cert — expected, accept the browser warning). Remote admin enabled, gated by the `anon` system login.

## Samsung M2020 Series

- **Connection:** USB, standard printer-class device (`usb://Samsung/M2020%20Series?serial=0727B8GF3F00GFB`)
- **Driver:** official Samsung/HP Unified Linux Driver (`uld-samsung/Samsung_M2020_Series.ppd`), installed via `~/uld/install.sh` from `uld_V1.00.39_01.17.tar.gz` (HP's official SL-M2020 driver page)
- **Firmware:** V3.00.01.24 — this specific version fix resolved a long-standing intermittent USB communication fault. **Full incident history, what was ruled out, and the fix itself are documented in `Samsung_M2020_Printer_Notes.md` — read that before touching this printer's setup again.**
- **Print from any app:** send to the `Samsung_M2020_Series` CUPS queue over the LAN, or add via IPP at `ipp://192.168.1.83:631/printers/Samsung_M2020_Series`

## Canon G3010 series

- **Connection:** USB, standard printer-class device (`usb://Canon/G3010%20series?serial=068533&interface=1`)
- **Driver:** `cnijfilter2` (Canon's official Linux driver), installed via the `ppa:thierry-f/fork-michael-gruz` PPA, plus the model-specific package (found via `apt search cnijfilter2 | grep -i g30`)
- **Known issue, resolved:** hit a Canon **E03** error (paper-feed sensor fault) during setup — a physical paper-path/sensor issue, cleared by checking the paper path for jams/debris and reseating paper. Not a software problem.
- **Print from any app:** send to the `Canon_G3010_series` CUPS queue, or via IPP at `ipp://192.168.1.83:631/printers/Canon_G3010_series`

## Posiflex PP-6900 (receipt printer)

- **Different architecture from the other two** — connects as a CDC-ACM virtual serial device, not USB-printer-class. Full details, the ESC/POS command reference, and known driver limitations are in **`CLAUDE.md`** — that's the primary reference for this one.
- **Two ways to print to it:**
  - Raw TCP socket at `192.168.1.83:9100` (via the `posiflex-bridge` systemd service, bridging to `/dev/serial/by-id/usb-POSIFLEX_TECHNOLOGY_INC._PP-6900_Thermal_Printer_PPUSB0-if00` — **not** a numbered `/dev/ttyACMx` path, see incident below) — this is what POS apps (Loyverse, etc.) and `python-escpos` should target directly
  - CUPS raw queue `Posiflex_PP6900` — **fixed 2026-09-11**, now points at `serial:/dev/serial/by-id/usb-POSIFLEX_TECHNOLOGY_INC._PP-6900_Thermal_Printer_PPUSB0-if00?baud=9600` instead of the numbered path. No longer at risk from the renumbering incident below.
- **Avoid** the `Posiflex_PP6900_GUI` queue (`rastertoescpos` CUPS driver) — confirmed broken for anything graphical

### Incident: silent print failures from a numbered `/dev/ttyACMx` device path (2026-09-04)

HomeServer has **two** USB CDC-ACM devices: the Posiflex printer and a 3D printer's Klipper (rp2040) controller board. Both show up as `/dev/ttyACM0` / `/dev/ttyACM1`, and Linux doesn't guarantee which one gets which number — it depends on enumeration order, which can change on any USB reconnect/power-cycle.

`posiflex-bridge.service` was hardcoded to `/dev/ttyACM0`. After enough USB reconnects during a testing session, the two devices swapped numbering, so the bridge was silently forwarding ESC/POS bytes to the *Klipper board* instead of the printer — with zero error surfaced anywhere. The TCP socket accepts fine (that's the bridge's listening socket, unrelated to what's on the other end), `sendall()` returns successfully, and the printer app reports "printed" — but nothing physically prints, because the bytes never reached the printer at all. Diagnosed by comparing `udevadm info -q property -n /dev/ttyACM0` / `ttyACM1` (`ID_SERIAL=Klipper_rp2040_...` vs `ID_SERIAL=POSIFLEX_TECHNOLOGY_INC...`).

**Fix**: point the bridge at `/dev/serial/by-id/usb-POSIFLEX_TECHNOLOGY_INC._PP-6900_Thermal_Printer_PPUSB0-if00` instead — udev's by-id symlinks are keyed to the device's actual USB identity (vendor/product/serial), not enumeration order, so this can't happen again regardless of what else gets plugged in or reconnected.

**Lesson**: never hardcode a numbered `/dev/ttyACMx` or `/dev/ttyUSBx` path in any service config on a machine with more than one USB-serial device — always use the corresponding `/dev/serial/by-id/...` symlink (`ls -la /dev/serial/by-id/` to find it).

## Template printing web app (thermal-print-webapp)

The Flask app in the `POS_Printer` repo (https://github.com/OMHK/POS_Printer) that lets the Posiflex be driven from a browser/phone. Runs on HomeServer as a Docker container, reachable at `http://192.168.1.83:5051`.

**Deploying/updating it** (2026-09-14 onward):
```bash
cd ~/thermal-print-webapp && ./deploy.sh
```
That pulls the latest git commit, rebuilds the image, and restarts the container. No more manual `scp` + `docker build` + `docker run` — everything needed is in the repo (`Dockerfile`, `deploy.sh`).

To push code changes from a dev machine: commit + `git push` to the repo, then run `deploy.sh` on HomeServer (or SSH in and do it remotely: `ssh anon@192.168.1.83 'cd ~/thermal-print-webapp && ./deploy.sh'`).

**Data persistence — important**: `templates/*.json` and `usb_devices.json` are **not** baked into the Docker image. They're bind-mounted from `~/thermal-print-data/` on HomeServer's host filesystem:
```
docker run ... -v ~/thermal-print-data/templates:/app/templates -v ~/thermal-print-data/usb_devices.json:/app/usb_devices.json ...
```
This is deliberate: the app's "Manage Templates" tab lets anyone on the LAN create/edit/delete templates live, and those writes land inside whatever container is currently running. Without this bind mount, a `docker build`+restart (i.e. every deploy) would silently **wipe** any templates created or edited since the last deploy — the container's writable layer doesn't survive being replaced. `deploy.sh` already does this correctly; don't remove the `-v` flags if editing it by hand. Verified 2026-09-14 by creating a template via the live app, redeploying, and confirming it survived.

The in-repo `templates/` directory is just the seed set for a fresh clone/local dev — it is not the live source of truth once deployed. If you want to pull live-created templates back into git for backup, copy from `~/thermal-print-data/templates/` on HomeServer, not from the repo checkout.

## Common notes across all three

- All three queues are shared (`printer-is-shared`) and browsable — other devices on the LAN should auto-discover them via mDNS/Bonjour without manual IP entry, same as any shared network printer
- `_anon_ThinkPad_T480`-suffixed duplicate queue entries you may see are normal — CUPS auto-generates these as "implicit class" mirrors when a shared printer discovers itself over the network loopback. Harmless, safe to ignore
- If a printer shows "Unplugged or turned off" in `lpstat -p`, check the physical USB connection on HomeServer first — that status is CUPS reporting the device genuinely isn't on the USB bus, not a driver problem
