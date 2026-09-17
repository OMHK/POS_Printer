"""
Template-based printing CLI for the Posiflex PP-6900 (see CLAUDE.md).

Pick a template from templates/*.json, fill in its fields, preview it,
then print it over the raw TCP:9100 socket.

Run:
    python template_print.py
"""

import sys
from pathlib import Path

from escpos.exceptions import Error as EscposError

from template_core import build_lines, load_templates, print_lines, resolve_default


def prompt_field(element):
    label = element["label"]
    default = resolve_default(element.get("default", ""))
    suffix = f" [{default}]" if default else ""
    value = input(f"  {label}{suffix}: ").strip()
    return value or default


def prompt_list(element):
    label = element["label"]
    numbered = element["type"] == "numbered_list"
    hint = " (auto-numbered)" if numbered else ""
    print(f"  {label}{hint} (blank line to finish):")
    items = []
    while True:
        line = input("    - ").strip()
        if not line:
            break
        items.append(line)
    return items


def prompt_image(element):
    label = element["label"]
    while True:
        path = input(f"  {label} (file path, blank to skip): ").strip()
        if not path:
            return None
        p = Path(path)
        if not p.is_file():
            print(f"  no such file: {path}")
            continue
        return p.read_bytes()


def prompt_line_items(element):
    label = element.get("label", "Items")
    print(f"  {label} - enter each item (blank name to finish):")
    items = []
    while True:
        name = input("    item name: ").strip()
        if not name:
            break
        qty = input("    qty [1]: ").strip() or "1"
        price = input("    price: ").strip() or "0"
        try:
            items.append({"name": name, "qty": float(qty), "price": float(price)})
        except ValueError:
            print("    qty/price must be numbers - skipping this item")
    return items


def prompt_table(element):
    columns = element.get("columns")
    if columns:
        labels = [c.get("label", "") if isinstance(c, dict) else str(c) for c in columns]
        print(f"  {element.get('label', 'Table')} - columns: {', '.join(labels)} (blank first cell to finish):")
        rows = []
        while True:
            first = input(f"    {labels[0]}: ").strip()
            if not first:
                break
            row = [first]
            for label in labels[1:]:
                row.append(input(f"    {label}: ").strip())
            rows.append(row)
        return rows

    # Ad-hoc grid: no fixed columns, so ask how many, then the header labels,
    # then data rows - the header row itself is what build_lines bolds.
    n_raw = input(f"  {element.get('label', 'Table')} - how many columns? [{element.get('default_cols', 3)}]: ").strip()
    try:
        n = int(n_raw) if n_raw else element.get("default_cols", 3)
    except ValueError:
        n = element.get("default_cols", 3)
    print(f"  Enter {n} header labels:")
    headers = [input(f"    header {i + 1}: ").strip() or f"Col {i + 1}" for i in range(n)]
    print("  Rows (blank first cell to finish):")
    rows = [headers]
    while True:
        first = input(f"    {headers[0]}: ").strip()
        if not first:
            break
        row = [first]
        for h in headers[1:]:
            row.append(input(f"    {h}: ").strip())
        rows.append(row)
    return rows if len(rows) > 1 else []


def collect_values(template):
    values = {}
    for element in template["elements"]:
        etype = element["type"]
        if etype in ("field", "qr", "barcode"):
            values[element["name"]] = prompt_field(element)
        elif etype in ("list", "numbered_list"):
            values[element["name"]] = prompt_list(element)
        elif etype == "image":
            img_bytes = prompt_image(element)
            if img_bytes:
                values[element["name"]] = img_bytes
        elif etype == "line_items":
            values[element["name"]] = prompt_line_items(element)
        elif etype == "table":
            values[element["name"]] = prompt_table(element)
        # auto, auto_total, section_header, divider, thick_divider, spacer, text: no user input needed
    return values


def show_preview(lines):
    print("\n--- preview " + "-" * 20)
    for op in lines:
        if op["kind"] == "image":
            print(f"[IMG {op['align'][0].upper()}] <image, {len(op['bytes'])} bytes>")
            continue
        if op["kind"] == "qr":
            print(f"[QR {op['align'][0].upper()}] {op['data']!r}")
            continue
        if op["kind"] == "barcode":
            print(f"[BARCODE {op['align'][0].upper()}] ({op['bc_type']}) {op['data']!r}")
            continue
        marker = "".join([
            "B" if op["bold"] else "-",
            "D" if op["double"] else "-",
            {"left": "L", "center": "C", "right": "R"}[op["align"]],
        ])
        print(f"[{marker}] {op['text']}")
    print("-" * 33 + "\n")


def choose(prompt, options):
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    while True:
        raw = input(f"{prompt}: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print("  invalid choice")


def main():
    templates = load_templates()
    if not templates:
        print("No templates found in templates/")
        return

    print("Available templates:")
    idx = choose("Select a template", [t["name"] for t in templates])
    template = templates[idx]

    if template.get("status") == "blocked":
        print(f"\n[!] {template['status_note']}\n")
        if input("This template is flagged as unverified - continue anyway? (y/N): ").strip().lower() != "y":
            return

    print(f"\n== {template['name']} ==")
    values = collect_values(template)
    lines = build_lines(template, values)
    show_preview(lines)

    choice = input("Print this now? (y/N): ").strip().lower()
    if choice != "y":
        print("Not printed.")
        return

    try:
        print_lines(lines)
    except OSError as e:
        print(f"Could not reach printer - {e}")
        sys.exit(1)
    except EscposError as e:
        print(f"Print failed - {e}")
        sys.exit(1)

    print("Printed.")


if __name__ == "__main__":
    main()
