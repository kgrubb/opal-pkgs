from opal_pkgs.pack import FAILED, elf, pack, tree

LATEST = ("https://curl.se/download/", "curl-(\\d+\\.\\d+\\.\\d+)\\.tar\\.xz", ".asc")


def pack_pkg():
    if "curl" not in FAILED:
        pack(
            "curl",
            "curl",
            "mips_siflower",
            """
    Depends: libc, ca-bundle
    License: MIT
    Section: net
    Description: command line tool for transferring data with URL syntax (mbedTLS)
    """,
            [("usr/bin/curl", elf(tree("curl") / "src" / "curl"), 0o755)],
        )
