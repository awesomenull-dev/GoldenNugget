"""HotLoad: fetch safety rules (dangerous/broken tweaks) from a remote JSON.

The remote JSON lists tweaks that are currently dangerous or broken, scoped to
specific iOS versions / device types. GoldenNugget caches a local copy in the
settings folder, checks for updates on every launch, and warns/blocks the user
from enabling flagged tweaks.

A kill switch in GoldenNugget settings turns the whole system off. When off,
fetches are skipped and no rules are applied.
"""

import json
import os
import time
from typing import Optional

import urllib.request

from PySide6.QtCore import QStandardPaths

RULES_URL = ("https://raw.githubusercontent.com/awesomenull-dev/"
             "GoldenNugget/main/hotload_rules.json")
RULES_FILENAME = "hotload_rules.json"
KILL_SWITCH_KEY = "hotload_enabled"


def _settings_dir() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if not base.endswith("GoldenNugget") and not base.endswith("GoldenNugget/"):
        base = os.path.join(base, "GoldenNugget")
    os.makedirs(base, exist_ok=True)
    return base


def _rules_path() -> str:
    return os.path.join(_settings_dir(), RULES_FILENAME)


class HotLoad:
    def __init__(self, settings=None):
        self.settings = settings
        self._rules = {"version": 0, "rules": []}
        self._load_local()

    # --- storage ---------------------------------------------------------
    def _load_local(self):
        try:
            with open(_rules_path(), "r", encoding="utf-8") as f:
                parsed = json.load(f)
            if isinstance(parsed, dict) and "rules" in parsed:
                self._rules = parsed
        except Exception:
            self._rules = {"version": 0, "rules": []}

    def is_enabled(self) -> bool:
        if self.settings is None:
            return True
        try:
            return bool(self.settings.value(KILL_SWITCH_KEY, True, type=bool))
        except Exception:
            return True

    def set_enabled(self, enabled: bool):
        if self.settings is None:
            return
        self.settings.setValue(KILL_SWITCH_KEY, bool(enabled))
        try:
            self.settings.sync()
        except Exception:
            pass

    # --- fetching --------------------------------------------------------
    def update(self, url: Optional[str] = None) -> bool:
        """Fetch fresh rules and cache them in the settings folder. On any
        failure the existing local copy is kept (rules always load locally).

        Returns True when a rule set was fetched successfully, False otherwise.
        """
        if not self.is_enabled():
            return False
        url = url or RULES_URL
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GoldenNugget"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            parsed = json.loads(data.decode("utf-8"))
            if not isinstance(parsed, dict) or "rules" not in parsed:
                return False
            parsed["_fetched_at"] = int(time.time())
            path = _rules_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=2)
            self._rules = parsed
            return True
        except Exception as e:
            print(f"[HotLoad] update failed: {e}")
            return False

    # --- matching --------------------------------------------------------
    def rule_for(self, tweak_id, device_version=None, device_model=None) -> Optional[dict]:
        """Return the first applicable rule for a tweak (by its TweakID name),
        or None when it is not flagged for this device/iOS. The kill switch
        being off returns None for everything."""
        if not self.is_enabled():
            return None
        tweak_name = getattr(tweak_id, "name", str(tweak_id))
        for rule in self._rules.get("rules", []):
            try:
                if rule.get("tweak") != tweak_name:
                    continue
                if rule.get("disabled", True) is False:
                    continue
                if not self._version_applicable(rule, device_version):
                    continue
                if not self._model_applicable(rule, device_model):
                    continue
                return rule
            except Exception:
                continue
        return None

    def blocked_names(self, device_version=None, device_model=None) -> set:
        """Set of TweakID names currently flagged as blocked for this setup."""
        names = set()
        for rule in self._rules.get("rules", []):
            try:
                if rule.get("disabled", True) is False:
                    continue
                if not self._version_applicable(rule, device_version):
                    continue
                if not self._model_applicable(rule, device_model):
                    continue
                names.add(rule.get("tweak"))
            except Exception:
                continue
        return names

    # --- helpers ---------------------------------------------------------
    @staticmethod
    def _compare(v1, v2):
        a = [int(x) for x in str(v1).replace(",", ".").split(".") if x.isdigit()]
        b = [int(x) for x in str(v2).replace(",", ".").split(".") if x.isdigit()]
        a += [0] * (len(b) - len(a))
        b += [0] * (len(a) - len(b))
        return (a > b) - (a < b)

    def _version_applicable(self, rule: dict, device_version) -> bool:
        lo = rule.get("min_version")
        hi = rule.get("max_version")
        if lo is None and hi is None:
            return True
        if device_version is None:
            return False
        v = str(device_version)
        if lo is not None and self._compare(v, str(lo)) < 0:
            return False
        if hi is not None and self._compare(v, str(hi)) > 0:
            return False
        return True

    def _model_applicable(self, rule: dict, device_model) -> bool:
        only = rule.get("only_models")
        if not only:
            return True
        if device_model is None:
            return False
        model = str(device_model)
        return any(model.startswith(p) for p in only)


def confirm_flagged(rule: dict, parent=None) -> bool:
    """Show the warning for a flagged tweak. Returns True (Countiune Anyway)
    to allow, or False (Cancel) to block."""
    from PySide6.QtWidgets import QMessageBox

    tweak = rule.get("tweak", "this tweak")
    reason = rule.get("reason")
    if reason:
        reason_txt = str(reason)
    else:
        reason_txt = "This feature is currently flagged as dangerous or broken."
    text = (f"GoldenNugget safety rules have flagged \"{tweak}\" as currently "
            f"dangerous or broken.\n\n{reason_txt}\n\n"
            "It is recommended not to enable it. Do you still want to enable it?")
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Disabled Feature Warning")
    box.setText(text)
    continue_btn = box.addButton("Countiune Anyway", QMessageBox.ButtonRole.AcceptRole)
    cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel_btn)
    box.exec()
    return box.clickedButton() is continue_btn
