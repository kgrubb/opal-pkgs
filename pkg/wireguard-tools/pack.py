from pathlib import Path

from opal_pkgs.pack import FAILED, elf, pack, tree

FILES = Path(__file__).parent / "files"

# The tag archive has no maintainer signature, so HTTPS is the only check.
LATEST = ("https://github.com/WireGuard/wireguard-tools/tags", "v(1\\.0\\.\\d+)", None)


def pack_pkg():
    if "wireguard-tools" not in FAILED:
        pack(
            "wireguard-tools",
            "wireguard-tools",
            "mips_siflower",
            """
    Depends: libc, kmod-wireguard
    License: GPL-2.0
    Section: net
    Description: Static wg for the GL-SFT1200. The kernel module stays the stock one.
    """,
            [
                ("usr/bin/wg", elf(tree("wireguard-tools") / "src" / "wg"), 0o755),
                (
                    "usr/bin/wireguard_watchdog",
                    (FILES / "wireguard_watchdog").read_bytes(),
                    0o755,
                ),
                (
                    "lib/netifd/proto/wireguard.sh",
                    (FILES / "wireguard.sh").read_bytes(),
                    0o755,
                ),
            ],
        )
