from dataclasses import dataclass
from io import BytesIO

# Mode bitfield (re-exported from the shared light module so src.utils
# stays the single definition site; anything here is already heavy anyway)
from src.utils.file_to_restore import _FileMode

@dataclass
class MbdbRecord:
    domain: str
    filename: str
    link: str
    hash: bytes
    key: bytes
    mode: _FileMode
    inode: int
    user_id: int
    group_id: int
    mtime: int
    atime: int
    ctime: int
    size: int
    flags: int
    properties: list

    def to_bytes(self) -> bytes:
        d = BytesIO()

        d.write(len(self.domain).to_bytes(2, "big"))
        d.write(self.domain.encode("utf-8"))

        d.write(len(self.filename).to_bytes(2, "big"))
        d.write(self.filename.encode("utf-8"))

        d.write(len(self.link).to_bytes(2, "big"))
        d.write(self.link.encode("utf-8"))

        d.write(len(self.hash).to_bytes(2, "big"))
        d.write(self.hash)

        d.write(len(self.key).to_bytes(2, "big"))
        d.write(self.key)

        d.write(self.mode.to_bytes(2, "big"))
        #d.write(self.unknown2.to_bytes(4, "big"))
        #d.write(self.unknown3.to_bytes(4, "big"))
        d.write(self.inode.to_bytes(8, "big"))
        d.write(self.user_id.to_bytes(4, "big"))
        d.write(self.group_id.to_bytes(4, "big"))
        d.write(self.mtime.to_bytes(4, "big"))
        d.write(self.atime.to_bytes(4, "big"))
        d.write(self.ctime.to_bytes(4, "big"))
        d.write(self.size.to_bytes(8, "big"))
        d.write(self.flags.to_bytes(1, "big"))

        d.write(len(self.properties).to_bytes(1, "big"))

        for name, value in self.properties:
            d.write(len(name).to_bytes(2, "big"))
            d.write(name.encode("utf-8"))

            d.write(len(value).to_bytes(2, "big"))
            d.write(value.encode("utf-8"))

        return d.getvalue()
    
@dataclass
class Mbdb:
    records: list[MbdbRecord]

    def to_bytes(self) -> bytes:
        d = BytesIO()

        d.write(b"mbdb")
        d.write(b"\x05\x00")

        for record in self.records:
            d.write(record.to_bytes())

        return d.getvalue()