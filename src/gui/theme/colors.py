from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ThemeColors:
    """All named color slots used across the application."""

    # Surfaces
    bg_primary: str
    bg_secondary: str
    bg_tertiary: str
    bg_input: str
    bg_elevated: str

    # Text
    text_primary: str
    text_secondary: str
    text_disabled: str
    text_inverse: str

    # Accent
    accent: str
    accent_hover: str
    accent_pressed: str

    # Semantic
    success: str
    error: str
    warning: str

    # Borders / dividers
    border: str
    divider: str

    # Interactive
    scrollbar: str
    scrollbar_pressed: str
    selection: str

    # Special
    card_border: str
    surface_hover: str
    danger_text: str

    def with_accent(self, accent: str, hover: str, pressed: str) -> "ThemeColors":
        return replace(self, accent=accent, accent_hover=hover, accent_pressed=pressed)


# ---------------------------------------------------------------------------
# Dark palette (matches the current hardcoded colors exactly)
# ---------------------------------------------------------------------------
DARK = ThemeColors(
    bg_primary="#1e1e1e",
    bg_secondary="#1C1C1E",
    bg_tertiary="#2C2C2E",
    bg_input="#1C1C1E",
    bg_elevated="#1e1e1e",

    text_primary="#FFFFFF",
    text_secondary="#8E8E93",
    text_disabled="#787878",
    text_inverse="#FFFFFF",

    accent="#007AFF",
    accent_hover="#0066CC",
    accent_pressed="#0055AA",

    success="#30D158",
    error="#FF453A",
    warning="#FFD60A",

    border="#3A3A3C",
    divider="#3A3A3C",

    scrollbar="#3b3b3b",
    scrollbar_pressed="#535353",
    selection="#007AFF",

    card_border="#3A3A3C",
    surface_hover="#2C2C2E",
    danger_text="#FF453A",
)


# ---------------------------------------------------------------------------
# Light palette (iOS Settings-style)
# ---------------------------------------------------------------------------
LIGHT = ThemeColors(
    bg_primary="#F2F2F7",
    bg_secondary="#FFFFFF",
    bg_tertiary="#E5E5EA",
    bg_input="#FFFFFF",
    bg_elevated="#FFFFFF",

    text_primary="#000000",
    text_secondary="#8E8E93",
    text_disabled="#C7C7CC",
    text_inverse="#FFFFFF",

    accent="#007AFF",
    accent_hover="#0066CC",
    accent_pressed="#0055AA",

    success="#34C759",
    error="#FF3B30",
    warning="#FF9500",

    border="#C6C6C8",
    divider="#C6C6C8",

    scrollbar="#C7C7CC",
    scrollbar_pressed="#AEAEB2",
    selection="#007AFF",

    card_border="#00000000",
    surface_hover="#E5E5EA",
    danger_text="#FF3B30",
)


# ---------------------------------------------------------------------------
# Accent presets: (normal, hover, pressed)
# ---------------------------------------------------------------------------
ACCENT_PRESETS = {
    "blue":     ("#007AFF", "#0066CC", "#0055AA"),
    "purple":   ("#AF52DE", "#9B47C4", "#893DAB"),
    "pink":     ("#FF2D55", "#E6284D", "#CC2244"),
    "red":      ("#FF3B30", "#E6352B", "#CC2F26"),
    "orange":   ("#FF9500", "#E68600", "#CC7700"),
    "yellow":   ("#FFCC00", "#E6B800", "#CCA300"),
    "green":    ("#34C759", "#2EAF4E", "#289944"),
    "teal":     ("#5AC8FA", "#50B4E6", "#46A0D2"),
}
