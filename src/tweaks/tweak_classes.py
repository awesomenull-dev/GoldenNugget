from typing import Optional, Callable

from .basic_plist_locations import FileLocation

_on_tweak_change: Optional[Callable[[], None]] = None

def set_tweak_change_callback(callback: Optional[Callable[[], None]]):
    """Register a callback to be invoked when any tweak changes."""
    global _on_tweak_change
    _on_tweak_change = callback

def _notify_tweak_change():
    if _on_tweak_change:
        try:
            _on_tweak_change()
        except Exception:
            pass  # Never let callback errors break tweak changes

class Tweak:
    def __init__(
            self,
            key: str,
            value: any = 1,
            owner: int = 501, group: int = 501
        ):
        self.key = key
        self.value = value
        self.owner = owner
        self.group = group
        self.enabled = False

    def set_enabled(self, value: bool):
        if self.enabled != value:
            self.enabled = value
            _notify_tweak_change()
    def set_value(self, new_value: any, toggle_enabled: bool = True):
        self.value = new_value
        if toggle_enabled:
            self.enabled = True
        _notify_tweak_change()

    def apply_tweak(self):
        raise NotImplementedError
    
class NullifyFileTweak(Tweak):
    def __init__(
            self,
            file_location: FileLocation,
            owner: int = 501, group: int = 501
        ):
        super().__init__(key=None, value=None, owner=owner, group=group)
        self.file_location = file_location

    def apply_tweak(self, other_tweaks: dict):
        if self.enabled:
            other_tweaks[self.file_location] = b""
    

class BasicPlistTweak(Tweak):
    def __init__(
            self,
            file_location: FileLocation,
            key: str,
            value: any = True,
            owner: int = 501, group: int = 501
        ):
        super().__init__(key=key, value=value, owner=owner, group=group)
        self.file_location = file_location

    def apply_tweak(self, other_tweaks: dict) -> dict:
        if not self.enabled:
            return other_tweaks
        if self.file_location in other_tweaks:
            other_tweaks[self.file_location][self.key] = self.value
        else:
            other_tweaks[self.file_location] = {self.key: self.value}
        return other_tweaks
    
class AdvancedPlistTweak(BasicPlistTweak):
    def __init__(
        self,
        file_location: FileLocation,
        keyValues: dict,
        owner: int = 501, group: int = 501,
        never_enable: Optional[set] = None,
        allowed_keys: Optional[set] = None
    ):
        super().__init__(file_location=file_location, key=None, value=keyValues, owner=owner, group=group)
        self.never_enable = set(never_enable or ())
        # If set, only keys in this set are ever applied / stored (interface-
        # visible daemons). Keys outside it are dropped, never written.
        self.allowed_keys = set(allowed_keys) if allowed_keys is not None else None

    def _filter_keys(self, values: dict) -> dict:
        """Drop keys that are hard-protected or not interface-visible."""
        out = {}
        for key, value in values.items():
            if key in self.never_enable:
                continue
            if self.allowed_keys is not None and key not in self.allowed_keys:
                continue
            out[key] = value
        return out

    def set_multiple_values(self, keys: list[str], value: any):
        for key in keys:
            if value and value is not False and value is not None and key in self.never_enable:
                continue  # hard-protected: this key must never be enabled
            if self.allowed_keys is not None and key not in self.allowed_keys:
                continue  # not exposed in the UI: never introduce it
            self.value[key] = value
        _notify_tweak_change()

    def apply_tweak(self, other_tweaks: dict) -> dict:
        if not self.enabled:
            return other_tweaks
        other_tweaks[self.file_location] = self._filter_keys(self.value)
        return other_tweaks
