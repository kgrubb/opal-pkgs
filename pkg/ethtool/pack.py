from opal_pkgs.pack import FAILED, elf, pack, tree

LATEST = (
    "https://www.kernel.org/pub/software/network/ethtool/",
    "ethtool-([\\d.]+)\\.tar\\.xz",
    ".sign",
)


def pack_pkg():
    if "ethtool" not in FAILED:
        pack(
            "ethtool",
            "ethtool",
            "mips_siflower",
            """
    Depends: libc
    License: GPL-2.0
    Section: net
    Description: Static ethtool (ioctl interface) for the GL-SFT1200
    """,
            [("usr/sbin/ethtool", elf(tree("ethtool") / "ethtool"), 0o755)],
        )
