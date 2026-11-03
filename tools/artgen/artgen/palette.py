"""Master palette. Every pixel the generator writes comes from here (validate.py checks it).

Ramps run dark → light. Light comes from the top-left, so the light end goes on top/left faces.
"""

from __future__ import annotations


def hx(s: str) -> tuple[int, int, int, int]:
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 255)


INK = hx("#2b1e2a")  # outline: warm near-black, never pure black

RAMPS: dict[str, list[str]] = {
    "grass": ["#2f6b3a", "#43873f", "#5fa447", "#82c055", "#a9d86b"],
    "leaf": ["#234a33", "#2f6a3d", "#438a43", "#64aa4c", "#8fc95c"],
    "pine": ["#1d3d36", "#28574a", "#367158", "#4f8f66"],
    "dirt": ["#5a3b2b", "#7a5236", "#9c6c43", "#bf8d58", "#ddb27a"],
    "sand": ["#a6855a", "#c9a670", "#e2c58c", "#f2e0ae"],
    "stone": ["#3d3f4f", "#585c6e", "#7a8092", "#a2a8b6", "#cdd1d9", "#eef0f2"],
    "wood": ["#3e261d", "#5c3826", "#7e4e31", "#a1683e", "#c58a52", "#e0ae73"],
    "roof_red": ["#5a2228", "#842f33", "#ad433b", "#d0624a", "#ea8a62"],
    "roof_blue": ["#26304f", "#34467a", "#4a64a3", "#6c8cc6", "#9ab4e0"],
    "roof_teal": ["#1f4245", "#2b605c", "#3a8075", "#58a48e"],
    "thatch": ["#6e5223", "#93702e", "#b8913c", "#d9b552", "#f0d679"],
    "plaster": ["#a8906f", "#c7b08b", "#e0cfab", "#f3e8cc", "#fff8e6"],
    "water": ["#1f3f6e", "#2a5d94", "#3b80ba", "#5ea5d6", "#94cdeb", "#d5f0fa"],
    "gold": ["#7a4a1b", "#b37a2a", "#e0ad3c", "#f7d66a", "#fff1b0"],
    "fire": ["#9e2f25", "#d4542e", "#f08a33", "#ffc04d", "#fff0a0"],
    "ui_paper": ["#7d5c3b", "#b58f61", "#dcc092", "#efdfbc", "#faf2dd"],
    "ui_wood": ["#3b2418", "#5a3624", "#7c4c31", "#9c6640", "#bd8653"],
    "flower_pink": ["#a8456f", "#e2709b", "#f7a8c4"],
    "flower_yellow": ["#b88a1e", "#f0c93b", "#fbe68a"],
    "flower_white": ["#a9a6b8", "#e6e3ee", "#ffffff"],
    "flower_purple": ["#5d3f8c", "#8d66c4", "#b99ae3"],
    "flower_red": ["#8a2430", "#cf3f3f", "#f07b6c"],
    "crop": ["#7a6a23", "#a99434", "#d4bd4a", "#f1df7c"],
    "cloth_cream": ["#a99a80", "#cfc3a8", "#ece3cc", "#fffaf0"],
    "shadow": ["#2b1e2a"],
    # Rarity / UI accents
    "rarity": ["#9aa0a6", "#4caf50", "#3d8bfd", "#a259ff", "#ff9f1c"],
    "accent": ["#e05a47", "#3f8f5f", "#3a6fb0", "#f2c14e"],
}

# Character recolour ramps: 4 shades, dark → light. Keys must match config/avatar.yaml.
SKIN = {
    "porcelain": ["#b88a7a", "#e0b3a0", "#f6d3c2", "#fff0e6"],
    "peach": ["#b07055", "#da9775", "#f2bb97", "#fcdcc0"],
    "honey": ["#8f5a37", "#c07f4f", "#e0a66f", "#f4c995"],
    "tan": ["#734428", "#9c6038", "#c3824f", "#dca673"],
    "umber": ["#4e2c1d", "#6e4029", "#8f5838", "#b07650"],
    "ebony": ["#2f1a14", "#45271c", "#5f3826", "#7d4e36"],
}
HAIR = {
    "black": ["#16121c", "#262033", "#3a3249", "#544a66"],
    "chestnut": ["#3d2216", "#5e3421", "#82492d", "#a8643f"],
    "auburn": ["#4f1d17", "#7a2c21", "#a6402d", "#c9613f"],
    "ginger": ["#7a3517", "#b4541f", "#df7a2e", "#f5a457"],
    "blonde": ["#8a6524", "#bb9236", "#e2bf57", "#f7e18f"],
    "platinum": ["#8f8a86", "#bdb7ad", "#e1dccf", "#fbf8ef"],
    "rose": ["#7a2f4f", "#ad4a72", "#d9739a", "#f5a6c4"],
    "teal": ["#174a4f", "#226b6f", "#2f9294", "#58c2bd"],
    "violet": ["#35215a", "#4f3283", "#7050b0", "#9b7fd6"],
    "silver": ["#4c5160", "#71788a", "#9da4b4", "#d0d5df"],
}
EYES = {
    "brown": ["#2b1e2a", "#5a3726", "#8a5a3a", "#ffffff"],
    "hazel": ["#2b1e2a", "#5e5a2a", "#8f8a45", "#ffffff"],
    "green": ["#2b1e2a", "#2f6a3d", "#4f9a55", "#ffffff"],
    "blue": ["#2b1e2a", "#2a5d94", "#4f8fd0", "#ffffff"],
    "grey": ["#2b1e2a", "#585c6e", "#8a90a0", "#ffffff"],
    "amber": ["#2b1e2a", "#a5631c", "#e09a2c", "#ffffff"],
}
OUTFIT = {
    "red": ["#5e1f24", "#8f2f30", "#c0473d", "#e2735a"],
    "orange": ["#6e3216", "#a24e20", "#d8742e", "#f2a254"],
    "mustard": ["#6b5216", "#9c7a22", "#cca434", "#ebcb5f"],
    "leaf": ["#2b5a2e", "#3f7d3a", "#5fa447", "#8cc663"],
    "forest": ["#1d3b2c", "#2a5640", "#3c7656", "#5b9a72"],
    "teal": ["#1d4a4c", "#286a69", "#368f86", "#5bb5a6"],
    "sky": ["#2f5788", "#4277b6", "#5f9ad8", "#93c3ef"],
    "navy": ["#1c2347", "#2a3566", "#3d4d8c", "#5e72b3"],
    "plum": ["#3c1f45", "#5a2e66", "#7d4590", "#a76bb8"],
    "rose": ["#7a2f4f", "#a8456f", "#d26d94", "#f0a3bf"],
    "cream": ["#9c8f76", "#c4b799", "#e3d8bd", "#fbf5e6"],
    "charcoal": ["#22222b", "#33343f", "#4a4c5a", "#6a6d7d"],
}

# Shade keys used inside recolourable character layers. The client swaps them for a ramp.
SHADE_KEYS = [hx("#404040"), hx("#707070"), hx("#a0a0a0"), hx("#d0d0d0")]


def ramp(name: str) -> list[tuple[int, int, int, int]]:
    return [hx(c) for c in RAMPS[name]]


def all_colors() -> set[tuple[int, int, int]]:
    out = {INK[:3]}
    for table in (RAMPS, SKIN, HAIR, EYES, OUTFIT):
        for colors in table.values():
            out.update(hx(c)[:3] for c in colors)
    out.update(k[:3] for k in SHADE_KEYS)
    return out
