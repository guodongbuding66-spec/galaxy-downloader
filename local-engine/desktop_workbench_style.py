"""The Orbit shell's visual primitives. Controls remain native ttk buttons."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from types import MappingProxyType

from PIL import Image, ImageDraw, ImageTk

from desktop_design_tokens import COLOR, font

ORBIT = MappingProxyType({
    "shell": "#F3F5F9",
    "nav": "#111A2D",
    "nav_hover": "#202D46",
    "nav_selected": "#283A61",
    "nav_text": "#D2DCEF",
    "nav_quiet": "#98AACB",
    "hero": "#152343",
    "hero_line": "#33496F",
    "hero_text": "#F7FAFF",
    "hero_quiet": "#BDD0ED",
    "white": "#FFFFFF",
    "inset": "#F4F7FC",
    "line": "#E0E7F1",
    "focus": "#4876ED",
})


def _rounded(master, fill, *, background, outline=None, radius=9):
    size, scale = 44, 3
    image = Image.new("RGB", (size * scale, size * scale), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((1, 1, size * scale - 2, size * scale - 2), radius * scale, fill=fill, outline=outline, width=2 * scale)
    return ImageTk.PhotoImage(image.resize((size, size), Image.Resampling.LANCZOS), master=master)


def configure_orbit(window):
    """Create per-interpreter image elements, retaining images for Tk's lifetime."""
    style = ttk.Style(window)
    images = []
    groups = {
        "Primary": (COLOR["accent"], COLOR["accent_hover"], "#153888", "#E6EBF5", COLOR["on_accent"]),
        "Header": (ORBIT["inset"], "#E8EFFA", "#DCE6F8", "#F2F4F8", COLOR["text_primary"]),
        "Secondary": (ORBIT["inset"], "#E8EFFA", "#DCE6F8", "#F2F4F8", COLOR["text_primary"]),
        "Quiet": (ORBIT["white"], ORBIT["inset"], "#E8EFFA", ORBIT["white"], COLOR["text_secondary"]),
        "Tab": (ORBIT["white"], ORBIT["inset"], "#E8EFFA", ORBIT["white"], COLOR["text_secondary"]),
        "Nav": (ORBIT["nav"], ORBIT["nav_hover"], ORBIT["nav_selected"], ORBIT["nav"], ORBIT["nav_text"]),
        "Danger": (ORBIT["white"], "#FCE9EC", "#FADBE0", ORBIT["white"], COLOR["danger"]),
    }
    for key, (normal, hover, pressed, disabled, foreground) in groups.items():
        background = {"Nav": ORBIT["nav"], "Header": ORBIT["shell"]}.get(key, ORBIT["white"])
        element = f"Orbit.{key}.plate"
        variants = [
            _rounded(window, fill, background=background, outline=outline, radius=3 if key == "Tab" else 9)
            for fill, outline in ((normal, None), (hover, None), (pressed, None), (disabled, None), (normal, ORBIT["focus"]), (pressed, ORBIT["focus"]))
        ]
        images.extend(variants)
        style.element_create(
            element, "image", variants[0],
            ("disabled", variants[3]), ("pressed", "focus", variants[5]),
            ("selected", "focus", variants[5]), ("focus", variants[4]),
            ("pressed", variants[2]), ("selected", variants[2]),
            ("active", variants[1]), border=12, padding=0, sticky="nsew",
        )
        name = f"Orbit.{key}.TButton"
        style.layout(name, [(element, {"sticky": "nsew", "children": [("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "w" if key == "Nav" else ""})]})]})])
        style.configure(name, foreground=foreground, font=font("body_sm", bold=key not in ("Quiet", "Nav")), padding=(12, 6), anchor="w" if key == "Nav" else "center")
        style.map(name, foreground=[("disabled", ORBIT["nav_quiet"] if key == "Nav" else "#687893"), ("selected", COLOR["accent"] if key == "Tab" else foreground)])
    style.configure("Orbit.Vertical.TScrollbar", background="#D1DBEA", troughcolor=ORBIT["shell"], bordercolor=ORBIT["shell"], arrowcolor="#546580", width=11, arrowsize=10)
    window._orbit_style_images = images
    window.option_add("*TCombobox*Listbox.background", ORBIT["white"])
    window.option_add("*TCombobox*Listbox.foreground", COLOR["text_primary"])
    window.option_add("*TCombobox*Listbox.selectBackground", COLOR["accent"])
    window.option_add("*TCombobox*Listbox.selectForeground", ORBIT["white"])


def button(parent, text, command, *, kind="Secondary", icon=None, **kwargs):
    control = ttk.Button(parent, text=text, command=command, style=f"Orbit.{kind}.TButton", takefocus=True, **kwargs)
    control.bind("<Return>", lambda _event: (control.invoke(), "break")[1])
    if icon:
        color = ORBIT["nav_text"] if kind == "Nav" else COLOR["on_accent"] if kind == "Primary" else COLOR["accent"]
        control._orbit_icon = icon_image(control, icon, color)
        control.configure(image=control._orbit_icon, compound="left")
    return control


_GLYPHS = {
    "download": (((8, 2), (8, 10)), ((4, 7), (8, 11), (12, 7)), ((2, 12), (2, 15), (14, 15), (14, 12))),
    "queue": (((3, 4), (14, 4)), ((3, 8), (14, 8)), ((3, 12), (11, 12))),
    "history": (((3, 3), (3, 7), (7, 7)), ((3, 7), (5, 3), (11, 2), (14, 5), (14, 11), (11, 14), (5, 14), (2, 11)), ((8, 5), (8, 9), (11, 10))),
    "library": (((2, 4), (2, 14), (14, 14), (14, 6), (8, 6), (6, 4), (2, 4)),),
    "tools": (((3, 3), (13, 13)), ((12, 2), (14, 4), (4, 14), (2, 12), (12, 2))),
    "settings": (((2, 4), (14, 4)), ((2, 8), (14, 8)), ((2, 12), (14, 12)), ((6, 2), (6, 6)), ((11, 6), (11, 10)), ((5, 10), (5, 14))),
    "arrow": (((2, 8), (14, 8)), ((9, 3), (14, 8), (9, 13))),
    "image": (((2, 2), (14, 2), (14, 14), (2, 14), (2, 2)), ((2, 12), (6, 7), (9, 10), (11, 7), (14, 11))),
}


def icon_image(master, glyph, color, *, size=18, pad=6):
    scale = 3
    canvas = Image.new("RGBA", ((size + pad) * scale, size * scale))
    draw = ImageDraw.Draw(canvas)
    for points in _GLYPHS[glyph]:
        draw.line([(round(x * size * scale / 16), round(y * size * scale / 16)) for x, y in points], fill=color, width=round(1.55 * scale), joint="curve")
    return ImageTk.PhotoImage(canvas.resize((size + pad, size), Image.Resampling.LANCZOS), master=master)
