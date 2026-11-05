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


def _cstr(data, offset):
    return data[offset : data.index(b"\0", offset)].decode()


def _dyn(path):
    """Parse a section-stripped MIPS32 LE ET_DYN. Raises SystemExit on refusal."""
    data = Path(path).read_bytes()
    if data[:6] != b"\x7fELF\x01\x01" or struct.unpack_from("<H", data, 18)[0] != 8:
        raise SystemExit(f"{path}: not a 32-bit little-endian MIPS ELF")
    e_type = struct.unpack_from("<H", data, 16)[0]
    if e_type != 3:
        raise SystemExit(f"{path}: not ET_DYN")
    e_flags = struct.unpack_from("<I", data, 36)[0]
    # EF_MIPS_ABI_O32 = 0x1000; EF_MIPS_ABI2 (n32) = 0x20.
    if e_flags & 0x20:
        raise SystemExit(f"{path}: not o32")
    if not (e_flags & 0x1000):
        raise SystemExit(f"{path}: missing EF_MIPS_ABI_O32")
    (phoff,) = struct.unpack_from("<I", data, 28)
    phentsize, phnum = struct.unpack_from("<HH", data, 42)
    loads, dyn_off, dyn_sz, has_interp, stack_x = [], None, 0, False, False
    for i in range(phnum):
        off = phoff + i * phentsize
        ptype, poff, pva, _pa, pfs, _pms, pfl, _al = struct.unpack_from(
            "<8I", data, off
        )
        if ptype == 1:
            loads.append((pva, poff, pfs))
        elif ptype == 2:
            dyn_off, dyn_sz = poff, pfs
        elif ptype == 3:
            has_interp = True
        elif ptype == 0x6474E551 and pfl & 1:
            stack_x = True
    if has_interp:
        raise SystemExit(f"{path}: has PT_INTERP")
    if dyn_off is None:
        raise SystemExit(f"{path}: no PT_DYNAMIC")

    def v2o(va):
        for base, file_off, filesz in loads:
            if base <= va < base + filesz:
                return va - base + file_off
        raise SystemExit(f"{path}: VA {va:#x} not in PT_LOAD")

    tags, needed = {}, []
    for i in range(0, dyn_sz, 8):
        tag, val = struct.unpack_from("<iI", data, dyn_off + i)
        if tag == 0:
            break
        if tag == 1:
            needed.append(val)
        else:
            tags.setdefault(tag, val)
    if 5 not in tags:
        raise SystemExit(f"{path}: no DT_STRTAB")
    stro = v2o(tags[5])
    name = lambda x: _cstr(data, stro + x)
    needed_names = [name(x) for x in needed]
    soname = name(tags[14]) if 14 in tags else None
    verdef = {}
    if 0x6FFFFFFC in tags:
        o = v2o(tags[0x6FFFFFFC])
        for _ in range(tags.get(0x6FFFFFFD, 0)):
            _ver, _flags, ndx, _cnt, _h, aux, nxt = struct.unpack_from(
                "<HHHHIII", data, o
            )
            verdef[ndx] = name(struct.unpack_from("<I", data, o + aux)[0])
            if not nxt:
                break
            o += nxt
    verneed = {}
    if 0x6FFFFFFE in tags:
        o = v2o(tags[0x6FFFFFFE])
        for _ in range(tags.get(0x6FFFFFFF, 0)):
            _ver, cnt, file, aux, nxt = struct.unpack_from("<HHIII", data, o)
            a = o + aux
            for _ in range(cnt):
                _h, _fl, other, n, anext = struct.unpack_from("<IHHII", data, a)
                verneed[other] = (name(file), name(n))
                if not anext:
                    break
                a += anext
            if not nxt:
                break
            o += nxt
    exports, undef = set(), []
    if 6 in tags and 0x70000011 in tags:
        so = v2o(tags[6])
        vs = v2o(tags[0x6FFFFFF0]) if 0x6FFFFFF0 in tags else None
        for i in range(tags[0x70000011]):
            n, _val, _sz, info, _oth, shn = struct.unpack_from(
                "<IIIBBH", data, so + 16 * i
            )
            if not n:
                continue
            ver = struct.unpack_from("<H", data, vs + 2 * i)[0] & 0x7FFF if vs else 0
            nm = name(n)
            bind = info >> 4
            if shn == 0:
                if bind in (1, 2):  # GLOBAL or WEAK
                    undef.append(
                        (
                            nm,
                            verneed.get(ver, ("", ""))[0],
                            verneed.get(ver, ("", ""))[1],
                        )
                    )
            elif bind in (1, 2):
                exports.add((nm, verdef.get(ver, "")))
    # MIPS ABI flags note (PT_MIPS_ABIFLAGS = 0x70000003)
    fp_abi = None
    for i in range(phnum):
        off = phoff + i * phentsize
        ptype, poff = struct.unpack_from("<II", data, off)[:2]
        if ptype == 0x70000003 and poff + 8 <= len(data):
            # version, isa_level, isa_rev, gpr_size, cpr1_size, cpr2_size, fp_abi
            fp_abi = data[poff + 7]
            break
    return {
        "data": data,
        "e_flags": e_flags,
        "needed": needed_names,
        "soname": soname,
        "verdef": [verdef[k] for k in sorted(verdef)],
        "exports": exports,
        "undef": undef,
        "tags": tags,
        "fp_abi": fp_abi,
        "stack_x": stack_x,
    }


def so(path, soname, needed_allow, verdefs, exports_required, undef_allow=None):
    """Refuse a shared object that the Opal's musl loader would reject or misbind."""
    info = _dyn(path)
    if info["soname"] != soname:
        raise SystemExit(f"{path}: SONAME {info['soname']!r} != {soname!r}")
    needed = set(info["needed"])
    allow = set(needed_allow)
    if not needed <= allow:
        raise SystemExit(f"{path}: NEEDED {sorted(needed)} not in {sorted(allow)}")
    if "libc.so" not in needed:
        raise SystemExit(f"{path}: NEEDED missing libc.so")
    tags = info["tags"]
    if 15 in tags or 29 in tags:
        raise SystemExit(f"{path}: has DT_RPATH/DT_RUNPATH")
    if 22 in tags:
        raise SystemExit(f"{path}: has DT_TEXTREL")
    flags_1 = tags.get(0x6FFFFFFB, 0)
    if not (flags_1 & 1):  # DF_1_NOW
        raise SystemExit(f"{path}: FLAGS_1 missing NOW")
    if info["stack_x"]:
        raise SystemExit(f"{path}: executable PT_GNU_STACK")
    if info["fp_abi"] is not None and info["fp_abi"] != 1:
        raise SystemExit(f"{path}: fp_abi={info['fp_abi']} (want 1)")
    if set(info["verdef"]) != set(verdefs):
        raise SystemExit(f"{path}: verdefs {info['verdef']} != {list(verdefs)}")
    required = set(exports_required)
    if not required <= info["exports"]:
        missing = sorted(required - info["exports"])[:5]
        raise SystemExit(f"{path}: missing exports e.g. {missing}")
    if undef_allow is not None:
        for nm, file, _ver in info["undef"]:
            if nm not in undef_allow:
                raise SystemExit(f"{path}: unresolved {nm} from {file or '?'}")
            if "time64" in nm:
                raise SystemExit(f"{path}: needs time64 syscalls ({nm})")
    return info["data"]


def load_exports(path):
    """Read a name\\tversion fixture into a set of (name, version) pairs."""
    out = set()
    for line in Path(path).read_text().splitlines():
        if not line:
            continue
        name, _, ver = line.partition("\t")
        out.add((name, ver))
    return out


def load_names(path):
    """Read the first column of a name\\t... fixture as a set of names."""
    return {
        line.split("\t", 1)[0] for line in Path(path).read_text().splitlines() if line
    }


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
        "so": so,
        "load_exports": load_exports,
        "load_names": load_names,
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
