#!/usr/bin/env python3
"""Pack the trees built by build.sh into replacement ipks in out/."""
import gzip
import io
import re
import struct
import subprocess
import tarfile
import textwrap
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


def ipk(members):
    """This opkg is the 2017 one and installs the gzip tar its own packages use."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tf:
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
        meta = [("control", body.encode(), 0o644), ("postinst", POSTINST, 0o755), ("prerm", PRERM, 0o755)]
        if conffiles:
            meta.append(("conffiles", "".join(f"{c}\n" for c in conffiles).encode(), 0o644))
        return ipk([("debian-binary", b"2.0\n"), ("data.tar.gz", tgz(entries)), ("control.tar.gz", tgz(meta))])

    release, blob = settle(ROOT / "feed", PINS[pin][2], name_for, blob_for)
    if release != PINS[pin][2]:
        print(f"{pin} release -> {release}")
        set_release(pin, release)
    path = OUT / name_for(release)
    path.write_bytes(blob)
    print(path.name)


def main():
    OUT.mkdir(exist_ok=True)
    FAILED = set((WORK / "failed").read_text().split()) if (WORK / "failed").exists() else set()
    if "dropbear" not in FAILED:
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

    if "ethtool" not in FAILED:
        pack("ethtool", "ethtool", "mips_siflower", """
    Depends: libc
    License: GPL-2.0
    Section: net
    Description: Static ethtool (ioctl interface) for the GL-SFT1200
    """, [("usr/sbin/ethtool", elf(tree("ethtool") / "ethtool"), 0o755)])

    if "i2c-tools" not in FAILED:
        pack("i2c-tools", "i2c-tools", "mips_siflower", """
    Depends: libc
    License: GPL-2.0
    Section: utils
    Description: Static i2c-tools for the GL-SFT1200
    """, [
        (f"usr/sbin/{tool}", elf(tree("i2c-tools") / "tools" / tool), 0o755)
        for tool in ("i2cdetect", "i2cdump", "i2cget", "i2cset", "i2ctransfer")
    ])

    if "sudo" not in FAILED:
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

    if "dnscrypt-proxy" not in FAILED:
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

    if "wireguard-tools" not in FAILED:
        pack("wireguard-tools", "wireguard-tools", "mips_siflower", """
    Depends: libc, kmod-wireguard
    License: GPL-2.0
    Section: net
    Description: Static wg for the GL-SFT1200. The kernel module stays the stock one.
    """, [
        ("usr/bin/wg", elf(tree("wireguard-tools") / "src" / "wg"), 0o755),
        ("usr/bin/wireguard_watchdog", (FILES / "wireguard_watchdog").read_bytes(), 0o755),
        ("lib/netifd/proto/wireguard.sh", (FILES / "wireguard.sh").read_bytes(), 0o755),
    ])

    if "softflowd" not in FAILED:
        built = tree("softflowd")
        softflowd = elf(built / "softflowd")
        if version("softflowd").encode() not in softflowd:
            raise SystemExit("softflowd version string does not match the pin")
        pack("softflowd", "softflowd", "mips_siflower", """
    Depends: libc
    License: BSD-2-Clause
    Section: net
    Description: Static softflowd for the GL-SFT1200. libpcap is linked in, so the system libpcap stays.
    """, [
        ("usr/sbin/softflowd", softflowd, 0o755),
        ("usr/sbin/softflowctl", elf(built / "softflowctl"), 0o755),
        ("etc/init.d/softflowd", (FILES / "softflowd.init").read_bytes(), 0o755),
        ("etc/config/softflowd", (FILES / "softflowd.config").read_bytes(), 0o644),
    ], ["/etc/config/softflowd"])

    if "curl" not in FAILED:
        pack("curl", "curl", "mips_siflower", """
    Depends: libc, ca-bundle
    License: MIT
    Section: net
    Description: Static curl with mbedTLS for the GL-SFT1200. The system libcurl stays for GL programs.
    """, [("usr/bin/curl", elf(tree("curl") / "src" / "curl"), 0o755)])

    if "dnsmasq" not in FAILED:
        pack("dnsmasq-full", "dnsmasq", "mips_siflower", """
    Depends: libc, kmod-ipt-ipset
    Provides: dnsmasq
    Require-User: dnsmasq=453:dnsmasq=453 dnsmasq_vpn=456:dnsmasq=453
    License: GPL-2.0
    Section: net
    Description: Static dnsmasq with DHCP, DNSSEC, ipset, conntrack and ubus for the GL-SFT1200
    """, [
        ("usr/sbin/dnsmasq", elf(tree("dnsmasq") / "src" / "dnsmasq"), 0o755),
        ("etc/init.d/dnsmasq", (FILES / "dnsmasq.init").read_bytes(), 0o755),
        ("etc/config/dhcp", (FILES / "dhcp.config").read_bytes(), 0o600),
        ("etc/dnsmasq.conf", (FILES / "dnsmasq.conf").read_bytes(), 0o600),
        ("etc/hotplug.d/ntp/25-dnsmasqsec", (FILES / "dnsmasq.ntp-hotplug").read_bytes(), 0o600),
        ("lib/netifd/dhcplease", (FILES / "dhcplease").read_bytes(), 0o755),
        ("usr/lib/dnsmasq/dhcp-script.sh", (FILES / "dnsmasq-dhcp-script.sh").read_bytes(), 0o755),
        ("usr/share/acl.d/dnsmasq_acl.json", (FILES / "dnsmasq_acl.json").read_bytes(), 0o644),
        ("usr/share/dnsmasq/dhcpbogushostname.conf", (FILES / "dhcpbogushostname.conf").read_bytes(), 0o600),
        ("usr/share/dnsmasq/rfc6761.conf", (FILES / "rfc6761.conf").read_bytes(), 0o600),
        ("usr/share/dnsmasq/trust-anchors.conf", (tree("dnsmasq") / "trust-anchors.conf").read_bytes(), 0o600),
    ], ["/etc/config/dhcp", "/etc/dnsmasq.conf"])

    if "chrony" not in FAILED:
        chronyd = elf(tree("chrony") / "chronyd")
        if b"+PRIVDROP" not in chronyd:
            raise SystemExit("chronyd was built without libcap and would stay root")
        pack("chrony", "chrony", "mips_siflower", """
    Depends: libc
    Require-User: chrony=323:chrony=323
    License: GPL-2.0
    Section: net
    Description: Static chrony for the GL-SFT1200
    """, [
        ("usr/sbin/chronyd", chronyd, 0o755),
        ("usr/bin/chronyc", elf(tree("chrony") / "chronyc"), 0o755),
        ("etc/init.d/chronyd", (FILES / "chronyd.init").read_bytes(), 0o755),
        ("etc/hotplug.d/iface/20-chrony", (FILES / "chrony.hotplug").read_bytes(), 0o755),
        ("etc/chrony/chrony.conf", (FILES / "chrony.conf").read_bytes(), 0o600),
        ("etc/config/chrony", (FILES / "chrony.config").read_bytes(), 0o600),
    ], ["/etc/chrony/chrony.conf", "/etc/config/chrony"])

    if "cacert" not in FAILED:
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


if __name__ == "__main__":
    main()
