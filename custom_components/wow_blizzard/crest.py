"""Compose a guild crest (tabard) from Blizzard's emblem and border masks."""
from __future__ import annotations

import io
from typing import Optional, Tuple

RGB = Tuple[int, int, int]


def _tint(image, color: RGB):
    """Color a grayscale mask, keeping its shading and transparency.

    The mask is normalized so its brightest visible pixel gets the full color.
    """
    from PIL import Image

    image = image.convert("RGBA")
    gray, alpha = image.getchannel("R"), image.getchannel("A")
    visible = Image.composite(gray, Image.new("L", gray.size, 0), alpha)
    brightest = max(1, visible.getextrema()[1])
    channels = [gray.point(lambda v, c=c: min(255, v * c // brightest)) for c in color]
    return Image.merge("RGBA", (*channels, alpha))


def compose_crest(emblem_png: bytes, border_png: bytes, background: RGB, emblem: RGB, border: RGB) -> Optional[bytes]:
    """PNG of the crest: background inside the border, emblem centred, border on top.

    Returns None if Pillow is not available.
    """
    try:
        from PIL import Image
    except ImportError:
        return None

    border_image = Image.open(io.BytesIO(border_png)).convert("RGBA")
    emblem_image = Image.open(io.BytesIO(emblem_png)).convert("RGBA")
    width, height = border_image.size

    # The border is open at the top, so fill each row between its outer edges
    alpha = border_image.getchannel("A").load()
    inside = Image.new("L", (width, height), 0)
    fill = inside.load()
    for y in range(height):
        xs = [x for x in range(width) if alpha[x, y]]
        if len(xs) > 1:
            for x in range(xs[0], xs[-1] + 1):
                fill[x, y] = 255

    crest = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    crest.paste(Image.new("RGBA", (width, height), (*background, 255)), (0, 0), inside)
    tinted = _tint(emblem_image, emblem)
    crest.alpha_composite(tinted, ((width - tinted.width) // 2, (height - tinted.height) // 2))
    crest.alpha_composite(_tint(border_image, border), (0, 0))

    out = io.BytesIO()
    crest.save(out, format="PNG")
    return out.getvalue()
