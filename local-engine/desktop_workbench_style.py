"""Native ttk workbench controls, styled from the shared desktop tokens."""
from __future__ import annotations

from tkinter import ttk
from types import MappingProxyType

from PIL import Image, ImageDraw, ImageTk

from desktop_design_tokens import COLOR, font

ORBIT = MappingProxyType({
    "shell": COLOR["bg"],
    "nav": COLOR["bg"],
    "nav_selected": COLOR["surface_elevated"],
    "nav_text": COLOR["text_secondary"],
    "nav_quiet": COLOR["text_subtle"],
    "inset": COLOR["bg"],
    "line": COLOR["border_subtle"],
})


def _rounded(master, fill, *, background, outline=None, radius=6):
    size, scale = 44, 3
    image = Image.new("RGB", (size * scale, size * scale), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((1, 1, size * scale - 2, size * scale - 2), radius * scale,
                           fill=fill, outline=outline, width=2 * scale)
    return ImageTk.PhotoImage(image.resize((size, size), Image.Resampling.LANCZOS), master=master)


def configure_orbit(window):
    style = ttk.Style(window)
    style.configure("Orbit.Vertical.TScrollbar", background=COLOR["border"], troughcolor=COLOR["bg"],
                    bordercolor=COLOR["bg"], arrowcolor=COLOR["text_subtle"], width=10, arrowsize=8)
    window._orbit_style_images = {}
    for key, value in (("background", COLOR["surface_raised"]), ("foreground", COLOR["text_primary"]),
                       ("selectBackground", COLOR["accent"]), ("selectForeground", COLOR["on_accent"])):
        window.option_add(f"*TCombobox*Listbox.{key}", value)


def _control_style(parent, kind):
    # Match the opaque anti-aliased edge to the actual containing surface.
    window = parent.winfo_toplevel()
    images = getattr(window, "_orbit_style_images", None)
    if images is None:
        configure_orbit(window)
        images = window._orbit_style_images
    background = parent.cget("background")
    key = (kind, background)
    name = f"Orbit.{kind}.{background.lstrip('#')}.TButton"
    if key in images:
        return name
    quiet, raised, pressed = COLOR["text_secondary"], COLOR["surface_elevated"], COLOR["secondary_hover"]
    normal, hover, down, disabled, ink = {
        "Primary": (COLOR["accent"], COLOR["accent_hover"], COLOR["accent_pressed"], raised, COLOR["on_accent"]),
        "Header": (background, raised, pressed, background, quiet),
        "Secondary": (raised, pressed, COLOR["border"], background, COLOR["text_primary"]),
        "Quiet": (background, raised, pressed, background, quiet),
        "Tab": (background, raised, pressed, background, quiet),
        "Nav": (background, COLOR["surface"], pressed, background, quiet),
        "Danger": (background, raised, pressed, background, COLOR["danger"]),
    }[kind]
    selected = raised if kind == "Nav" else normal
    variants = [_rounded(window, fill, background=background, outline=outline)
                for fill, outline in ((normal, None), (hover, None), (down, None), (disabled, None),
                                      (normal, COLOR["focus"]), (selected, None), (selected, COLOR["focus"]))]
    images[key] = variants
    style = ttk.Style(window)
    element = name.removesuffix(".TButton") + ".plate"
    style.element_create(element, "image", variants[0],
                         ("disabled", variants[3]), ("selected", "focus", variants[6]),
                         ("focus", variants[4]), ("pressed", variants[2]),
                         ("selected", variants[5]), ("active", variants[1]), border=8, padding=0, sticky="nsew")
    style.layout(name, [(element, {"sticky": "nsew", "children": [("Button.padding", {
        "sticky": "nsew", "children": [("Button.label", {"sticky": "w" if kind == "Nav" else ""})]})]})])
    style.configure(name, foreground=ink, font=font("body" if kind == "Primary" else "body_sm", bold=kind == "Primary"),
                    padding=(12, 8), anchor="w" if kind == "Nav" else "center")
    style.map(name, foreground=[("disabled", COLOR["text_subtle"]), ("selected", COLOR["text_primary"])])
    return name


def button(parent, text, command, *, kind="Secondary", icon=None, **kwargs):
    control = ttk.Button(parent, text=text, command=command, style=_control_style(parent, kind), takefocus=True, **kwargs)
    control.bind("<Return>", lambda _event: (control.invoke(), "break")[1])
    if icon:
        ink = COLOR["on_accent"] if kind == "Primary" else COLOR["text_secondary"]
        control._orbit_icons = (icon_image(control, icon, ink), icon_image(control, icon, COLOR["text_subtle"]))
        control.configure(image=(control._orbit_icons[0], "disabled", control._orbit_icons[1]), compound="left")
    return control


_GLYPHS = {
    "link": (((7, 5), (9, 3), (12, 3), (14, 5), (14, 7), (11, 10)), ((9, 11), (7, 13), (4, 13), (2, 11), (2, 9), (5, 6)), ((6, 10), (10, 6))),
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
