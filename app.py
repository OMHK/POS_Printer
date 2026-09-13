"""
Template-based printing web app for the Posiflex PP-6900 (see CLAUDE.md).

Serves a single-page UI (web/index.html) backed by a small JSON API, all
built on the same template_core.py used by the CLI and Tkinter GUI.

Run:
    python app.py
Then open http://<this machine's address>:5051 from any browser on the LAN.
Port is overridable via the PORT env var (used by the autoPort dev-preview flow).

Deployed on HomeServer as a Docker container - see deploy.sh and
Printing_Closet_Setup.md for the persistent-data-volume setup (templates
and usb_devices.json live outside the image so they survive rebuilds).
"""

import base64
import json
import os
import re
from pathlib import Path

from escpos.exceptions import Error as EscposError
from flask import Flask, jsonify, request, send_from_directory

from template_core import TEMPLATES_DIR, build_lines, load_templates, print_lines

WEB_DIR = Path(__file__).parent / "web"
USB_DEVICES_FILE = Path(__file__).parent / "usb_devices.json"
SAFE_TEMPLATE_ID = re.compile(r"^[a-z0-9_-]+$")

app = Flask(__name__)


def get_template(template_id):
    for t in load_templates():
        if t["id"] == template_id:
            return t
    return None


def decode_image_values(template, values):
    """Image fields arrive from the browser as data: URLs (base64) - decode
    them to raw bytes before handing off to build_lines()."""
    image_names = {el["name"] for el in template["elements"] if el["type"] == "image"}
    out = dict(values)
    for name in image_names:
        v = out.get(name)
        if isinstance(v, str) and v.startswith("data:"):
            _, b64data = v.split(",", 1)
            out[name] = base64.b64decode(b64data)
    return out


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/api/templates")
def api_templates():
    return jsonify(load_templates())


@app.get("/api/usb-devices")
def api_usb_devices():
    """Read-only: known USB serial devices on HomeServer and which one the
    posiflex-bridge service is currently pointed at. This is purely
    informational - the app has no way to change the binding itself (see
    Printing_Closet_Setup.md incident, 2026-09-04). Update usb_devices.json
    by SSHing into HomeServer and running: ls -la /dev/serial/by-id/"""
    if not USB_DEVICES_FILE.exists():
        return jsonify({"current": None, "devices": []})
    with open(USB_DEVICES_FILE, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.post("/api/templates/save")
def api_templates_save():
    """Create or overwrite a template. The whole template object (id, name,
    elements, ...) comes from the client, already parsed/validated as JSON
    there - this just checks the shape and writes templates/<id>.json."""
    data = request.get_json(force=True)
    template = data.get("template")
    if not isinstance(template, dict):
        return jsonify({"error": "Request must include a 'template' object."}), 400

    tid = template.get("id", "")
    if not isinstance(tid, str) or not SAFE_TEMPLATE_ID.match(tid):
        return jsonify({"error": "Template 'id' must be lowercase letters, numbers, - or _ only."}), 400
    if not template.get("name"):
        return jsonify({"error": "Template must have a 'name'."}), 400
    if not isinstance(template.get("elements"), list):
        return jsonify({"error": "Template must have an 'elements' array."}), 400

    path = TEMPLATES_DIR / f"{tid}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return jsonify({"ok": True, "id": tid})


@app.post("/api/templates/delete")
def api_templates_delete():
    data = request.get_json(force=True)
    tid = data.get("id", "")
    if not isinstance(tid, str) or not SAFE_TEMPLATE_ID.match(tid):
        return jsonify({"error": "invalid id"}), 400
    path = TEMPLATES_DIR / f"{tid}.json"
    if not path.exists():
        return jsonify({"error": "no such template"}), 404
    path.unlink()
    return jsonify({"ok": True})


@app.post("/api/preview")
def api_preview():
    data = request.get_json(force=True)
    template = get_template(data.get("template_id"))
    if template is None:
        return jsonify({"error": "unknown template"}), 404
    lines = build_lines(template, data.get("values", {}), data.get("styles", []))
    return jsonify({"lines": lines})


@app.post("/api/print")
def api_print():
    data = request.get_json(force=True)
    template = get_template(data.get("template_id"))
    if template is None:
        return jsonify({"error": "unknown template"}), 404

    values = decode_image_values(template, data.get("values", {}))
    lines = build_lines(template, values, data.get("styles", []))
    if not lines:
        return jsonify({"error": "Nothing to print - fill in at least one field."}), 400

    try:
        print_lines(lines)
    except OSError as e:
        return jsonify({"error": f"Could not reach printer - {e}"}), 502
    except EscposError as e:
        return jsonify({"error": f"Print failed - {e}"}), 400

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5051)), debug=False)
