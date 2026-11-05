from opal_pkgs.pack import FAILED, elf, pack, tree

LATEST = (
    "https://www.kernel.org/pub/software/utils/i2c-tools/",
    "i2c-tools-([\\d.]+)\\.tar\\.xz",
    ".sign",
)


def pack_pkg():
    if "i2c-tools" not in FAILED:
        pack(
            "i2c-tools",
            "i2c-tools",
            "mips_siflower",
            """
    Depends: libc
    License: GPL-2.0
    Section: utils
    Description: I2C tools for Linux
    """,
            [
                (f"usr/sbin/{tool}", elf(tree("i2c-tools") / "tools" / tool), 0o755)
                for tool in ("i2cdetect", "i2cdump", "i2cget", "i2cset", "i2ctransfer")
            ],
        )
