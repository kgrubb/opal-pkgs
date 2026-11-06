from pathlib import Path

from opal_pkgs.pack import FAILED, load_exports, load_names, pack, so, tree

# sqlite.org publishes no detached signature. update() checks the SHA3-256
# printed next to the tarball, and copies the /YYYY/ directory off the page.
LATEST = (
    "https://www.sqlite.org/download.html",
    r"sqlite-autoconf-(\d+)\.tar\.gz",
    None,
)

ABI = Path(__file__).resolve().parent / "abi"
ROUTER = Path(__file__).resolve().parents[1] / "zlib" / "abi"


def pack_pkg():
    if "libsqlite3" in FAILED:
        return
    root = tree("libsqlite3")
    data = so(
        root / "libsqlite3.so.0",
        "libsqlite3.so.0",
        {"libc.so", "libgcc_s.so.1"},
        [],
        # sqlite3one and sqlite3_fts*_may_be_corrupt are debug-only, not the API.
        load_exports(ABI / "libsqlite3.exports"),
        undef_allow=load_names(ROUTER / "libc.exports")
        | load_names(ROUTER / "libgcc_s.exports"),
    )
    pack(
        "libsqlite3",
        "libsqlite3",
        "mips_siflower",
        """
    Depends: libc
    License: Public-Domain
    Section: libs
    Description: SQLite (v3.x) database engine
    """,
        [("usr/lib/libsqlite3.so.0", data, 0o644)],
    )
