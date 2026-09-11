"""Shared page-identifier enum used by both the GUI and the backend reset flow.

Historically defined in ``src/gui/pages/pages_list.py``; it moved here so the
backend (``device_manager`` reset pass) no longer imports the GUI package.
``src/gui/pages/pages_list.py`` re-exports both symbols for the GUI side.
"""

from enum import Enum

from src.devicemanagement.constants import Version


class Page(Enum):
    Home = 0
    Gestalt = 1
    EUEnabler = 2
    StatusBar = 3
    Springboard = 4
    InternalOptions = 5
    LiquidGlass = 6
    Daemons = 7
    Posterboard = 8
    Templates = 9
    Passcode = 10
    RiskyTweaks = 11
    Tweaks = 12
    Apply = 13
    Settings = 14

    def getPageName(self) -> str:
        name_map = [
            "Home",
            "Mobile Gestalt",
            "Eligibility",
            "Status Bar",
            "Springboard",
            "Internal",
            "Liquid Glass",
            "Daemons",
            "PosterBoard",
            "Templates",
            "Passcode",
            "Resolution Modifications",
            "Tweaks",
            "Apply",
            "Settings"
        ]
        return name_map[self.value]

def get_resettable_pages(device_manager) -> list[Page]:
    device_ver = Version(device_manager.get_current_device_version())
    page_list: list[Page] = [Page.Springboard, Page.InternalOptions, Page.Daemons]

    # Status Bar is broken on iOS 27 (no write permissions for Speakeasy flags)
    # so the feature is hidden on iOS 27+
    if device_ver < Version("27.0"):
        page_list.insert(0, Page.StatusBar)

    return page_list