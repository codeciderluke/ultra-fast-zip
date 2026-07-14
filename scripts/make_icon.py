"""Generate the Ultra Fast Zip app icon -> assets/icon.png, assets/icon.ico

Concept: dark rounded square + purple archive box + cyan lightning bolt (speed).
Brand palette: #0F1117 / #1E2430 / #7C5CFF / #8D72FF / #00D4FF
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
OUT_DIR = Path(__file__).resolve().parent.parent / "assets"


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def vertical_gradient_rounded(size, box, radius, top_color, bottom_color):
    """Return a rounded-rectangle layer filled with a vertical gradient."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(gradient)
    x0, y0, x1, y1 = box
    for y in range(int(y0), int(y1) + 1):
        t = (y - y0) / max(1, (y1 - y0))
        gdraw.line([(x0, y), (x1, y)], fill=lerp(top_color, bottom_color, t) + (255,))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    layer.paste(gradient, (0, 0), mask)
    return layer


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    # Background: dark rounded square with a thin border
    bg = vertical_gradient_rounded(
        SIZE, (56, 56, SIZE - 56, SIZE - 56), 230, (30, 36, 48), (13, 15, 22)
    )
    img = Image.alpha_composite(img, bg)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (56, 56, SIZE - 56, SIZE - 56), radius=230, outline=(58, 66, 88, 255), width=8
    )

    # Archive box (purple gradient)
    body = vertical_gradient_rounded(
        SIZE, (232, 430, SIZE - 232, 852), 56, (141, 114, 255), (98, 71, 213)
    )
    img = Image.alpha_composite(img, body)

    # Box lid (brighter purple, slightly wider)
    lid = vertical_gradient_rounded(
        SIZE, (196, 330, SIZE - 196, 470), 44, (168, 146, 255), (124, 92, 255)
    )
    img = Image.alpha_composite(img, lid)

    draw = ImageDraw.Draw(img)
    draw.rectangle((232, 470, SIZE - 232, 486), fill=(58, 40, 140, 140))

    # Lightning bolt (cyan) crossing the box
    bolt = [
        (598, 128),
        (368, 568),
        (506, 568),
        (420, 936),
        (716, 460),
        (568, 460),
        (700, 128),
    ]
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.polygon(bolt, fill=(0, 212, 255, 90))
    from PIL import ImageFilter

    glow = glow.filter(ImageFilter.GaussianBlur(28))
    img = Image.alpha_composite(img, glow)
    bolt_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(bolt_layer)
    bdraw.polygon(bolt, fill=(0, 212, 255, 255))
    # Highlight on the upper-left face
    bdraw.polygon([(598, 128), (368, 568), (506, 568), (540, 420), (652, 128)],
                  fill=(120, 236, 255, 255))
    img = Image.alpha_composite(img, bolt_layer)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    img.save(OUT_DIR / "icon.png")
    img.save(
        OUT_DIR / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"saved: {OUT_DIR / 'icon.png'}, {OUT_DIR / 'icon.ico'}")


if __name__ == "__main__":
    main()
