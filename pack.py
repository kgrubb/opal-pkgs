#!/usr/bin/env python3
"""Pack the trees built by build.sh into replacement ipks in out/."""
import gzip
import io
import re
import struct
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).parent
WORK = ROOT / "work"
FILES = ROOT / "files"
OUT = ROOT / "out"
PINS = {
    line.split("\t")[0]: line.split("\t")
    for line in (ROOT / "versions").read_text().splitlines()
    if line and not line.startswith("#")
}

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
    """Read a binary and refuse anything that will not run on the Opal's kernel and libc."""
    data = Path(path).read_bytes()
    if data[:6] != b"\x7fELF\x01\x01" or struct.unpack_from("<H", data, 18)[0] != 8:
        raise SystemExit(f"{path}: not a 32-bit little-endian MIPS ELF")
    phoff, = struct.unpack_from("<I", data, 28)
    size, count = struct.unpack_from("<HH", data, 42)
    if any(struct.unpack_from("<I", data, phoff + i * size)[0] == 3 for i in range(count)):
        raise SystemExit(f"{path}: dynamically linked")
    if b"clock_gettime64" in data:
        raise SystemExit(f"{path}: needs time64 syscalls")
    return data


def tgz(entries):
    """entries: (path, bytes, mode) for files, (path, target) for symlinks."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tf:
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


def ar(members):
    out = b"!<arch>\n"
    for name, data in members:
        out += f"{name:<16}{0:<12}{0:<6}{0:<6}{0o100644:<8o}{len(data):<10}`\n".encode()
        out += data + (b"\n" if len(data) % 2 else b"")
    return out


def pack(package, pin, arch, control, entries, conffiles=()):
    full = f"{version(pin).replace('-', '')}-{PINS[pin][2]}"
    size = sum(len(e[1]) for e in entries if len(e) == 3)
    control = f"Package: {package}\nVersion: {full}\n{control.strip()}\nArchitecture: {arch}\nInstalled-Size: {size}\n"
    meta = [("control", control.encode(), 0o644), ("postinst", POSTINST, 0o755), ("prerm", PRERM, 0o755)]
    if conffiles:
        meta.append(("conffiles", "".join(f"{c}\n" for c in conffiles).encode(), 0o644))
    path = OUT / f"{package}_{full}_{arch}.ipk"
    path.write_bytes(ar([("debian-binary", b"2.0\n"), ("control.tar.gz", tgz(meta)), ("data.tar.gz", tgz(entries))]))
    print(path.name)


OUT.mkdir(exist_ok=True)
dropbear = elf(tree("dropbear") / "dropbearmulti")
if f"SSH-2.0-dropbear_{version('dropbear')}".encode() not in dropbear:
    raise SystemExit("dropbear banner does not match the pinned version")
pack("dropbear", "dropbear", "mips_siflower", """
Depends: libc
Alternatives: 100:/usr/bin/ssh:/usr/sbin/dropbear, 100:/usr/bin/scp:/usr/sbin/dropbear
License: MIT
Section: net
Description: Static Dropbear SSH server and client for the GL-SFT1200
""", [
    ("usr/sbin/dropbear", dropbear, 0o755),
    ("usr/bin/dbclient", "../sbin/dropbear"),
    ("usr/bin/dropbearkey", "../sbin/dropbear"),
    ("etc/init.d/dropbear", (FILES / "dropbear.init").read_bytes(), 0o755),
    ("etc/config/dropbear", (FILES / "dropbear.config").read_bytes(), 0o644),
    # Empty like stock: opkg deletes an owned file the new package omits, conffile or not.
    ("etc/dropbear/dropbear_rsa_host_key", b"", 0o600),
], ["/etc/dropbear/dropbear_rsa_host_key", "/etc/config/dropbear"])

pack("ethtool", "ethtool", "mips_siflower", """
Depends: libc
License: GPL-2.0
Section: net
Description: Static ethtool (ioctl interface) for the GL-SFT1200
""", [("usr/sbin/ethtool", elf(tree("ethtool") / "ethtool"), 0o755)])

pack("i2c-tools", "i2c-tools", "mips_siflower", """
Depends: libc
License: GPL-2.0
Section: utils
Description: Static i2c-tools for the GL-SFT1200
""", [
    (f"usr/sbin/{tool}", elf(tree("i2c-tools") / "tools" / tool), 0o755)
    for tool in ("i2cdetect", "i2cdump", "i2cget", "i2cset", "i2ctransfer")
])

sudo = tree("sudo")
pack("sudo", "sudo", "mips_siflower", """
Depends: libc
License: ISC
Section: admin
Description: Static sudo with built-in sudoers for the GL-SFT1200
""", [
    ("usr/bin/sudo", elf(sudo / "src" / "sudo"), 0o4755),
    ("usr/sbin/visudo", elf(sudo / "plugins" / "sudoers" / "visudo"), 0o755),
    ("etc/sudoers", (FILES / "sudoers").read_bytes(), 0o440),
    ("etc/init.d/sudo", (FILES / "sudo.init").read_bytes(), 0o755),
    ("lib/upgrade/keep.d/sudo", (FILES / "sudo.keep").read_bytes(), 0o644),
], ["/etc/sudoers"])

dnscrypt = tree("dnscrypt-proxy")
lists = WORK / "dnscrypt-lists"
pack("dnscrypt-proxy2", "dnscrypt-proxy", "mips_siflower", """
Depends: libc, ca-bundle
Conflicts: dnscrypt-proxy
License: ISC
Section: net
Description: dnscrypt-proxy for the GL-SFT1200
""", [
    ("usr/sbin/dnscrypt-proxy", elf(dnscrypt / "dnscrypt-proxy"), 0o755),
    ("etc/init.d/dnscrypt-proxy", (FILES / "dnscrypt-proxy.init").read_bytes(), 0o755),
    ("etc/dnscrypt-proxy2/dnscrypt-proxy.toml", (FILES / "dnscrypt-proxy.toml").read_bytes(), 0o644),
    ("etc/dnscrypt-proxy2/blocked-names.txt", (dnscrypt / "example-blocked-names.txt").read_bytes(), 0o644),
] + [
    (f"etc/dnscrypt-proxy2/{f.name}", f.read_bytes(), 0o644) for f in sorted(lists.iterdir())
], ["/etc/dnscrypt-proxy2/dnscrypt-proxy.toml"])

pem = (ROOT / ".cache" / PINS["cacert"][4].replace("{v}", version("cacert")).rsplit("/", 1)[1]).read_bytes()
pack("ca-bundle", "cacert", "all", """
Depends: libc
Provides: ca-certs
License: MPL-2.0
Section: base
Description: Mozilla CA bundle for the GL-SFT1200
""", [("etc/ssl/certs/ca-certificates.crt", pem, 0o644), ("etc/ssl/cert.pem", pem, 0o644)])

# curl's cacert.pem puts each Mozilla label above its certificate, underlined with '='
# and followed by '#' comment lines.
certs, hashes = [], {}
for label, cert in re.findall(rb"\n([^\n]+)\n=+\n(?:#[^\n]*\n)*(-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----)", pem, re.S):
    name = re.sub(r"[^A-Za-z0-9._+-]", "_", label.decode().strip().replace(" ", "_")) + ".crt"
    digest = subprocess.run(["openssl", "x509", "-noout", "-subject_hash"], input=cert, capture_output=True, check=True).stdout.decode().strip()
    certs += [(f"etc/ssl/certs/{name}", cert + b"\n", 0o644), (f"etc/ssl/certs/{digest}.{hashes.get(digest, 0)}", name)]
    hashes[digest] = hashes.get(digest, 0) + 1
if len(certs) != 2 * pem.count(b"-----BEGIN CERTIFICATE-----") or len({c[0] for c in certs}) != len(certs):
    raise SystemExit("cacert.pem certificates did not all map to unique files")
pack("ca-certificates", "cacert", "all", """
Depends: libc
Provides: ca-certs
License: MPL-2.0
Section: base
Description: Mozilla CA certificates for the GL-SFT1200
""", certs)
