from pathlib import Path

from opal_pkgs.pack import FAILED, exe, pack, tree, version

FILES = Path(__file__).parent / "files"

# build.openvpn.net lists the tarballs. .asc is the security-list signature.
LATEST = (
    "https://build.openvpn.net/downloads/releases/",
    r"openvpn-(2\.\d+\.\d+)\.tar\.gz",
    ".asc",
)


def pack_pkg():
    if "openvpn-openssl" in FAILED:
        return
    built = tree("openvpn-openssl") / "src" / "openvpn" / "openvpn"
    openvpn = exe(
        built,
        {"libc.so", "libgcc_s.so.1", "libcrypto.so.1.1", "libssl.so.1.1"},
        needed_required=("libgcc_s.so.1", "libssl.so.1.1", "libcrypto.so.1.1"),
    )
    banner = f"OpenVPN {version('openvpn-openssl')}".encode()
    if banner not in openvpn or b"[LZO]" not in openvpn or b"[LZ4]" not in openvpn:
        raise SystemExit("openvpn banner does not match the pin")
    if b"[DCO]" in openvpn:
        raise SystemExit("openvpn was built with ovpn-dco")
    # Same paths the stock package owns. Omitting one makes opkg delete it.
    pack(
        "openvpn-openssl",
        "openvpn-openssl",
        "mips_siflower",
        """
    Depends: libc, kmod-tun, libopenssl
    Provides: openvpn, openvpn-crypto
    License: GPL-2.0
    Section: net
    Description: Open source VPN solution using OpenSSL
    """,
        [
            ("usr/sbin/openvpn", openvpn, 0o755),
            ("etc/init.d/openvpn", (FILES / "openvpn.init").read_bytes(), 0o755),
            ("lib/functions/openvpn.sh", (FILES / "openvpn.sh").read_bytes(), 0o644),
            (
                "usr/share/openvpn/openvpn.options",
                (FILES / "openvpn.options").read_bytes(),
                0o644,
            ),
            (
                "etc/hotplug.d/openvpn/01-user",
                (FILES / "01-user").read_bytes(),
                0o644,
            ),
            (
                "lib/upgrade/keep.d/openvpn",
                (FILES / "keep.d").read_bytes(),
                0o644,
            ),
            (
                "usr/libexec/openvpn-hotplug",
                (FILES / "openvpn-hotplug").read_bytes(),
                0o755,
            ),
            ("etc/openvpn.user", (FILES / "openvpn.user").read_bytes(), 0o644),
            ("etc/config/openvpn", (FILES / "openvpn.config").read_bytes(), 0o600),
        ],
        ["/etc/config/openvpn", "/etc/openvpn.user"],
    )
