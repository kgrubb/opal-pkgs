from pathlib import Path

from opal_pkgs.pack import (
    FAILED,
    load_exports,
    load_names,
    pack,
    so,
    tree,
)

LATEST = (
    "https://github.com/madler/zlib/tags",
    r"v(1\.\d+\.\d+)",
    ".asc",
)

ABI = Path(__file__).resolve().parent / "abi"
# 1.3.1 adds ZLIB_1.2.12 on top of stock 1.2.11. Extra nodes are fine for musl.
VERDEFS = [
    "libz.so.1",
    "ZLIB_1.2.0",
    "ZLIB_1.2.0.2",
    "ZLIB_1.2.0.8",
    "ZLIB_1.2.2",
    "ZLIB_1.2.2.3",
    "ZLIB_1.2.2.4",
    "ZLIB_1.2.3.3",
    "ZLIB_1.2.3.4",
    "ZLIB_1.2.3.5",
    "ZLIB_1.2.5.1",
    "ZLIB_1.2.5.2",
    "ZLIB_1.2.7.1",
    "ZLIB_1.2.9",
    "ZLIB_1.2.12",
]


def api_exports(path):
    """Stock fixtures include VERDEF node names as absolute symbols; zig does not."""
    return {
        (name, ver)
        for name, ver in load_exports(path)
        if name != ver and not name.startswith("GCC_") and not name.startswith("GLIBC_")
    }


def pack_pkg():
    if "zlib" in FAILED:
        return
    root = tree("zlib")
    libc = load_names(ABI / "libc.exports")
    libgcc = load_names(ABI / "libgcc_s.exports")
    exports = api_exports(ABI / "zlib-1.2.11.libz.exports")
    data = so(
        root / "libz.so.1",
        "libz.so.1",
        {"libc.so", "libgcc_s.so.1"},
        VERDEFS,
        exports,
        undef_allow=libc | libgcc,
    )
    pack(
        "zlib",
        "zlib",
        "mips_siflower",
        """
    Depends: libc
    License: Zlib
    Section: libs
    Description: Shared zlib 1.3.1 for the GL-SFT1200 (ABI drop-in for 1.2.11).
    """,
        [
            ("usr/lib/libz.so.1", data, 0o644),
        ],
    )
