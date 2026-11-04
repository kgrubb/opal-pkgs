#!/usr/bin/env python3
"""Write the opkg Packages index for packages/*.ipk."""
import gzip
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).parent / "packages"
ARCHES = {"all", "mips_siflower"}


def members(raw):
    """Yield (name, bytes) from an ipk in either ar or tar.gz form."""
    if raw.startswith(b"!<arch>\n"):
        off = 8
        while off + 60 <= len(raw):
            name = raw[off:off + 16].decode().strip().rstrip("/")
            size = int(raw[off + 48:off + 58])
            yield name, raw[off + 60:off + 60 + size]
            off += 60 + size + size % 2
    else:
        with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
            for m in tf.getmembers():
                if m.isfile():
                    yield m.name.removeprefix("./"), tf.extractfile(m).read()


def control(raw):
    with tarfile.open(fileobj=io.BytesIO(dict(members(raw))["control.tar.gz"])) as tf:
        member = next(m for m in tf.getmembers() if m.name.removeprefix("./") == "control")
        return tf.extractfile(member).read().decode().strip()


def stanza(ipk):
    raw = ipk.read_bytes()
    text = control(raw)
    fields = dict(line.split(": ", 1) for line in text.splitlines() if ": " in line and not line.startswith(" "))
    for key in ("Package", "Version", "Architecture"):
        if key not in fields:
            raise SystemExit(f"{ipk.name}: control has no {key}")
    if fields["Architecture"] not in ARCHES:
        raise SystemExit(f"{ipk.name}: architecture {fields['Architecture']} does not run on the Opal")
    return f"{text}\nFilename: {ipk.name}\nSize: {len(raw)}\nSHA256sum: {hashlib.sha256(raw).hexdigest()}\n"


index = "\n".join(stanza(p) for p in sorted(ROOT.glob("*.ipk")))
if not index:
    raise SystemExit(f"no ipks in {ROOT}")
(ROOT / "Packages").write_text(index)
(ROOT / "Packages.gz").write_bytes(gzip.compress(index.encode(), mtime=0))
