"""Single source of truth for absolute-device-path -> backup-domain mapping.

Previously this table lived in two places — `DeviceManager.get_domain_for_path`
(device_manager.py) and `_BACKUP_DOMAIN_MAPPINGS` (original_plist.py) — with
the risk that one drifted and a reset wrote plists into the wrong domain.
Both call sites now use this module.
"""
from typing import Optional, Tuple

# Absolute path prefix -> (domain, container). ``container`` marks the
# Sys(SHARED)Container domains whose first path segment becomes part of the
# domain name (e.g. ``/var/containers/Data/SystemGroup/<group>/...`` maps to
# ``SysContainerDomain-<group>``).
_BACKUP_DOMAIN_MAPPINGS: Tuple[Tuple[str, str, bool], ...] = (
    ("/var/Managed Preferences/", "ManagedPreferencesDomain", False),
    ("/var/root/", "RootDomain", False),
    ("/var/preferences/", "SystemPreferencesDomain", False),
    ("/var/MobileDevice/", "MobileDeviceDomain", False),
    ("/var/mobile/", "HomeDomain", False),
    ("/var/db/", "DatabaseDomain", False),
    ("/var/containers/Shared/SystemGroup/", "SysSharedContainerDomain-", True),
    ("/var/containers/Data/SystemGroup/", "SysContainerDomain-", True),
)


def split_path_into_domain(path: str) -> Tuple[Optional[str], Optional[str]]:
    """Map an absolute device path to ``(domain, relative_path)``.

    Returns ``(None, None)`` when no prefix matches.
    """
    for prefix, domain, is_container in _BACKUP_DOMAIN_MAPPINGS:
        if path.startswith(prefix):
            rest = path[len(prefix):]
            if is_container:
                group, sep, rel = rest.partition("/")
                if not sep:
                    return domain + group, ""
                return domain + group, rel
            return domain, rest
    return None, None
