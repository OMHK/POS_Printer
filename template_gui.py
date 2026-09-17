"""
Template-based printing GUI for the Posiflex PP-6900 (see CLAUDE.md).

Pick a template, fill in its fields, preview, and print - over the raw
TCP:9100 socket, same as template_print.py (the CLI version).

Run:
    python template_gui.py
"""

import tkinter as tk
from tkinter import messagebox, ttk

from escpos.exceptions import Error as EscposError

from template_core import build_lines, load_templates, print_lines, resolve_default


class TemplateApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Thermal Print Templates")
        self.geometry("560x680")
        self.minsize(480, 480)

        self.templates = load_templates()
        self.current_template = None
        self.field_widgets = {}   # name -> Entry
        self.list_widgets = {}    # name -> Text

        self._build_layout()
        if self.templates:
            self.template_combo.current(0)
            self._on_template_selected()

    # ---------- layout ----------

    def _build_layout(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Template:").pack(side="left")
        self.template_combo = ttk.Combobox(
            top, state="readonly",
            values=[t["name"] for t in self.templates],
        )
        self.template_combo.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.template_combo.bind("<<ComboboxSelected>>", lambda e: self._on_template_selected())

        self.warning_label = ttk.Label(self, foreground="#b00020", wraplength=520, padding=(10, 0))
        self.warning_label.pack(fill="x")

        self.form_frame = ttk.Frame(self, padding=10)
        self.form_frame.pack(fill="both", expand=False)

        preview_frame = ttk.LabelFrame(self, text="Preview", padding=8)
        preview_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.preview_text = tk.Text(preview_frame, height=10, wrap="word", state="disabled")
        self.preview_text.pack(fill="both", expand=True)

        btn_frame = ttk.Frame(self, padding=10)
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="Preview", command=self._update_preview).pack(side="left")
        ttk.Button(btn_frame, text="Print", command=self._on_print).pack(side="right")

        self.status_label = ttk.Label(self, padding=(10, 0, 10, 10))
        self.status_label.pack(fill="x")

    # ---------- template form ----------

    def _on_template_selected(self):
        idx = self.template_combo.current()
        if idx < 0:
            return
        self.current_template = self.templates[idx]
        self._render_form()
        self._update_preview()
        self.status_label.config(text="")

    def _render_form(self):
        for child in self.form_frame.winfo_children():
            child.destroy()
        self.field_widgets.clear()
        self.list_widgets.clear()

        template = self.current_template
        if template.get("status") == "blocked":
            self.warning_label.config(text=f"⚠ {template['status_note']}")
        else:
            self.warning_label.config(text="")

        row = 0
        for element in template["elements"]:
            etype = element["type"]

            if etype in ("field", "qr", "barcode"):
                ttk.Label(self.form_frame, text=element["label"]).grid(row=row, column=0, sticky="w", pady=4)
                entry = ttk.Entry(self.form_frame, width=40)
                entry.insert(0, resolve_default(element.get("default", "")))
                entry.grid(row=row, column=1, sticky="ew", pady=4, padx=(8, 0))
                entry.bind("<KeyRelease>", lambda e: self._update_preview())
                self.field_widgets[element["name"]] = entry
                row += 1

            elif etype in ("list", "numbered_list"):
                hint = " (auto-numbered, one per line)" if etype == "numbered_list" else " (one per line)"
                ttk.Label(self.form_frame, text=f"{element['label']}{hint}").grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
                row += 1
                text = tk.Text(self.form_frame, height=4, width=40)
                text.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 4))
                text.bind("<KeyRelease>", lambda e: self._update_preview())
                self.list_widgets[element["name"]] = text
                row += 1

            elif etype == "auto":
                value = resolve_default(element.get("default", ""))
                ttk.Label(
                    self.form_frame,
                    text=f"Auto: {value}",
                    foreground="#888888",
                ).grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
                row += 1

            elif etype == "image":
                ttk.Label(
                    self.form_frame,
                    text=f"{element['label']}: image printing works now (see raster.py) but this GUI "
                         "doesn't have a file picker for it yet - use the web app (app.py) or the CLI.",
                    foreground="#888888",
                    wraplength=440,
                ).grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
                row += 1

            elif etype == "line_items":
                ttk.Label(
                    self.form_frame,
                    text="Line items (name/qty/price table): not editable in this GUI yet - "
                         "use the web app (app.py) or the CLI.",
                    foreground="#888888",
                    wraplength=440,
                ).grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
                row += 1

            elif etype == "table":
                ttk.Label(
                    self.form_frame,
                    text=f"{element.get('label', 'Table')}: custom table not editable in this GUI yet - "
                         "use the web app (app.py) or the CLI.",
                    foreground="#888888",
                    wraplength=440,
                ).grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
                row += 1

            # auto_total, section_header, divider, thick_divider, spacer, text: no form widget needed

        self.form_frame.columnconfigure(1, weight=1)

    def _collect_values(self):
        values = {}
        for name, entry in self.field_widgets.items():
            values[name] = entry.get().strip()
        for name, text in self.list_widgets.items():
            content = text.get("1.0", "end").strip()
            values[name] = [line.strip() for line in content.splitlines() if line.strip()]
        return values

    # ---------- preview / print ----------

    def _update_preview(self):
        if not self.current_template:
            return
        values = self._collect_values()
        lines = build_lines(self.current_template, values)

        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")
        for op in lines:
            if op["kind"] == "image":
                self.preview_text.insert("end", f"[IMG {op['align'][0].upper()}] <image, {len(op['bytes'])} bytes>\n")
                continue
            if op["kind"] == "qr":
                self.preview_text.insert("end", f"[QR {op['align'][0].upper()}] {op['data']}\n")
                continue
            if op["kind"] == "barcode":
                self.preview_text.insert("end", f"[BARCODE {op['align'][0].upper()}] ({op['bc_type']}) {op['data']}\n")
                continue
            marker = "".join([
                "B" if op["bold"] else "-",
                "D" if op["double"] else "-",
                {"left": "L", "center": "C", "right": "R"}[op["align"]],
            ])
            self.preview_text.insert("end", f"[{marker}] {op['text']}\n")
        self.preview_text.config(state="disabled")

    def _on_print(self):
        if not self.current_template:
            return

        if self.current_template.get("status") == "blocked":
            if not messagebox.askyesno(
                "Unverified template",
                f"{self.current_template['status_note']}\n\nContinue anyway?",
            ):
                return

        values = self._collect_values()
        lines = build_lines(self.current_template, values)
        if not lines:
            messagebox.showinfo("Nothing to print", "Fill in at least one field first.")
            return

        if not messagebox.askyesno("Print", "Send this to the printer now?"):
            return

        try:
            print_lines(lines)
        except OSError as e:
            self.status_label.config(text=f"Could not reach printer - {e}", foreground="#b00020")
            return
        except EscposError as e:
            self.status_label.config(text=f"Print failed - {e}", foreground="#b00020")
            return

        self.status_label.config(text="Printed.", foreground="#1a7a1a")


def main():
    app = TemplateApp()
    if not app.templates:
        messagebox.showerror("No templates", "No templates found in templates/")
    app.mainloop()


if __name__ == "__main__":
    main()
