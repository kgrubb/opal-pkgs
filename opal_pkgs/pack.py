"""Pack the trees built by opal-pkgs build into replacement ipks in out/."""

import gzip
import importlib.util
import io
import struct
import tarfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
OUT = ROOT / "out"
PINS = {
    line.split("\t")[0]: line.split("\t")
    for line in (ROOT / "versions").read_text().splitlines()
    if line and not line.startswith("#")
}
FAILED = set()

POSTINST = b"""#!/bin/sh
[ "${IPKG_NO_SCRIPT}" = "1" ] && exit 0
[ -x ${IPKG_INSTROOT}/lib/functions.sh ] || exit 0
. ${IPKG_INSTROOT}/lib/functions.sh
default_postinst $0 $@
"""
PRERM = b"""#!/bin/sh
[ -x ${IPKG_INSTROOT}/lib/functions.sh ] || exit 0
. ${IPKG_INSTROOT}/lib/functions.sh
default_prerm $0 $@
"""


def version(name):
    return PINS[name][1]


def tree(name):
    return WORK / f"{name}-{version(name)}"


def elf(path):
    data = Path(path).read_bytes()
    if data[:6] != b"\x7fELF\x01\x01" or struct.unpack_from("<H", data, 18)[0] != 8:
        raise SystemExit(f"{path}: not a 32-bit little-endian MIPS ELF")
    (phoff,) = struct.unpack_from("<I", data, 28)
    size, count = struct.unpack_from("<HH", data, 42)
    if any(
        struct.unpack_from("<I", data, phoff + i * size)[0] == 3 for i in range(count)
    ):
        raise SystemExit(f"{path}: dynamically linked")
    if b"clock_gettime64" in data:
        raise SystemExit(f"{path}: needs time64 syscalls")
    return data


def tgz(entries):
    """entries: (path, bytes, mode) for files, (path, target) for symlinks."""
    buf = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w") as tf,
    ):
        for path, *rest in entries:
            info = tarfile.TarInfo("./" + path)
            info.uname = info.gname = "root"
            if len(rest) == 1:
                info.type, info.linkname, info.mode = tarfile.SYMTYPE, rest[0], 0o777
                tf.addfile(info)
            else:
                info.size, info.mode = len(rest[0]), rest[1]
                tf.addfile(info, io.BytesIO(rest[0]))
    return buf.getvalue()


def ipk(members):
    """This opkg is the 2017 one and installs the gzip tar its own packages use."""
    buf = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w") as tf,
    ):
        for name, data in members:
            info = tarfile.TarInfo("./" + name)
            info.size, info.mode = len(data), 0o644
            info.uname = info.gname = "root"
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def set_release(pin, release):
    PINS[pin][2] = release
    lines = (ROOT / "versions").read_text().splitlines()
    for i, line in enumerate(lines):
        cols = line.split("\t")
        if cols and cols[0] == pin:
            cols[2] = release
            lines[i] = "\t".join(cols)
    (ROOT / "versions").write_text("\n".join(lines) + "\n")


def settle(feed, release, name_for, blob_for):
    """Bump the release while the feed already has that filename with different bytes."""
    start = int(release)
    while True:
        blob = blob_for(release)
        dest = feed / name_for(release)
        if not dest.exists() or dest.read_bytes() == blob:
            return release, blob
        nxt = int(release) + 1
        if nxt > start + 20:
            raise SystemExit(f"{dest.name}: release bump did not settle")
        release = str(nxt)


def pack(package, pin, arch, control, entries, conffiles=()):
    def name_for(rel):
        return f"{package}_{version(pin).replace('-', '')}-{rel}_{arch}.ipk"

    def blob_for(rel):
        full = f"{version(pin).replace('-', '')}-{rel}"
        size = sum(len(e[1]) for e in entries if len(e) == 3)
        body = f"Package: {package}\nVersion: {full}\n{textwrap.dedent(control).strip()}\nArchitecture: {arch}\nInstalled-Size: {size}\n"
        meta = [
            ("control", body.encode(), 0o644),
            ("postinst", POSTINST, 0o755),
            ("prerm", PRERM, 0o755),
        ]
        if conffiles:
            meta.append(
                ("conffiles", "".join(f"{c}\n" for c in conffiles).encode(), 0o644)
            )
        return ipk(
            [
                ("debian-binary", b"2.0\n"),
                ("data.tar.gz", tgz(entries)),
                ("control.tar.gz", tgz(meta)),
            ]
        )

    release, blob = settle(ROOT / "feed", PINS[pin][2], name_for, blob_for)
    if release != PINS[pin][2]:
        print(f"{pin} release -> {release}")
        set_release(pin, release)
    path = OUT / name_for(release)
    path.write_bytes(blob)
    print(path.name)


def load_recipes():
    """Each shipped package is pkg/<pin>/pack.py."""
    found = []
    for directory in sorted(ROOT.joinpath("pkg").iterdir()):
        script = directory / "pack.py"
        if not script.is_file():
            continue
        spec = importlib.util.spec_from_file_location(
            "opal_" + directory.name.replace("-", "_"), script
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        found.append((directory.name, mod))
    return found


def main():
    OUT.mkdir(exist_ok=True)
    failed = (
        set((WORK / "failed").read_text().split())
        if (WORK / "failed").exists()
        else set()
    )
    # Recipes call these by name. They are defined in this file, so hand them over before packing.
    shared = {
        "FAILED": failed,
        "pack": pack,
        "elf": elf,
        "tree": tree,
        "version": version,
        "WORK": WORK,
        "ROOT": ROOT,
        "PINS": PINS,
    }
    for _name, mod in load_recipes():
        for key, value in shared.items():
            setattr(mod, key, value)
        mod.pack_pkg()
