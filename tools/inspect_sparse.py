#!/usr/bin/env python3
"""Inspect a sparse backup directory (Manifest.mbdb + plists + payloads)."""
from pathlib import Path
import plistlib
import struct
import hashlib
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/gn_sparse_debug")
data = (root / "Manifest.mbdb").read_bytes()
print("mbdb header:", data[:6], "| size:", len(data))

off = 6
records = []

def read_str(buf, o):
    (l,) = struct.unpack_from(">H", buf, o)
    o += 2
    if l == 0xFFFF:
        return None, o
    s = buf[o:o + l]
    o += l
    return s.decode("utf-8", "replace"), o

while off < len(data):
    start = off
    try:
        domain, off = read_str(data, off)
        filename, off = read_str(data, off)
        link, off = read_str(data, off)
        (hlen,) = struct.unpack_from(">H", data, off); off += 2
        hsh = data[off:off + hlen]; off += hlen
        (klen,) = struct.unpack_from(">H", data, off); off += 2
        key = data[off:off + klen]; off += klen
        (mode,) = struct.unpack_from(">H", data, off); off += 2
        (inode,) = struct.unpack_from(">Q", data, off); off += 8
        uid, gid, mtime, atime, ctime = struct.unpack_from(">5I", data, off); off += 20
        (size,) = struct.unpack_from(">Q", data, off); off += 8
        flags = data[off]; off += 1
        (nprops,) = struct.unpack_from(">B", data, off); off += 1
        props = []
        for _ in range(nprops):
            n, off = read_str(data, off)
            v, off = read_str(data, off)
            props.append((n, v))
    except Exception as e:
        print(f"!! parse stop at offset {start}: {e}")
        break
    records.append(dict(start=start, domain=domain, filename=filename,
                        mode=mode, size=size, flags=flags))

print("parsed records:", len(records), f"| consumed {off}/{len(data)} bytes")
bad = [r for r in records if r["domain"] is None or r["filename"] is None]
print("records with None domain/filename:", len(bad))
for r in bad[:8]:
    print("   BAD:", {k: r[k] for k in ("start", "domain", "filename", "mode", "size", "flags")})

domains = {}
for r in records:
    domains.setdefault(r["domain"] or "<root>", 0)
    domains[r["domain"] or "<root>"] += 1
for d, c in sorted(domains.items()):
    print(f"  {c:4d}  {d}")

pb = [r for r in records if r["domain"] and "PosterBoard" in r["domain"]]
print("\nPosterBoard rows:", len(pb))
for r in pb[:12]:
    kind = "DIR " if (r["mode"] & 0o170000) == 0o040000 else "file"
    print(f"  {kind} mode={r['mode']:o} size={r['size']:<9} flags={r['flags']} {r['filename']}")

missing = []
present = 0
for r in records:
    if r["domain"] is None:
        continue
    fid = hashlib.sha1(f"{r['domain']}-{r['filename']}".encode()).hexdigest()
    if (root / fid).is_file():
        present += 1
    else:
        missing.append((r["domain"], r["filename"]))
print("\npayloads present:", present, "| missing:", len(missing))
for d, p in missing[:12]:
    print("  MISSING:", d, p)

mp = root / "Manifest.plist"
m = plistlib.loads(mp.read_bytes())
print("\nApplications:", m.get("Applications"))
