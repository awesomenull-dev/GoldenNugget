"""Lightweight FileToRestore definition, kept outside src.restore.

Importing anything under the src.restore package executes its __init__.py,
which pulls in pymobiledevice3. Tweak modules only need this class at import
time, so it lives here (light stdlib-only namespace package) to keep the
tweak -> restore import chain free of the device stack.
"""
from enum import IntFlag


class _FileMode(IntFlag):
    S_IFMT   = 0o0170000
    S_IFIFO  = 0o0010000
    S_IFCHR  = 0o0020000
    S_IFDIR  = 0o0040000
    S_IFBLK  = 0o0060000
    S_IFREG  = 0o0100000
    S_IFLNK  = 0o0120000
    S_IFSOCK = 0o0140000

    S_IRUSR  = 0o0000400
    S_IWUSR  = 0o0000200
    S_IXUSR  = 0o0000100

    S_IRGRP  = 0o0000040
    S_IWGRP  = 0o0000020
    S_IXGRP  = 0o0000010

    S_IROTH  = 0o0000004
    S_IWOTH  = 0o0000002
    S_IXOTH  = 0o0000001

    S_ISUID  = 0o0004000
    S_ISGID  = 0o0002000
    S_ISVTX  = 0o0001000


class FileToRestore:
    def __init__(self,
                 contents: str, restore_path: str, contents_path: str = None, domain: str = "",
                 owner: int = 501, group: int = 501, mode: _FileMode = None
                ):
        self.contents = contents
        self.contents_path = contents_path
        self.restore_path = restore_path
        self.domain = domain
        self.owner = owner
        self.group = group
        self.mode = mode