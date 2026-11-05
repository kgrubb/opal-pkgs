from pathlib import Path

from opal_pkgs.pack import FAILED, WORK, elf, pack, tree

FILES = Path(__file__).parent / "files"

LATEST = (
    "https://github.com/DNSCrypt/dnscrypt-proxy/releases/latest",
    "/releases/tag/(\\d+\\.\\d+\\.\\d+)\\b",
    ".minisig",
)


def pack_pkg():
    if "dnscrypt-proxy" not in FAILED:
        dnscrypt = tree("dnscrypt-proxy")
        lists = WORK / "dnscrypt-lists"
        pack(
            "dnscrypt-proxy2",
            "dnscrypt-proxy",
            "mips_siflower",
            """
    Depends: libc, ca-bundle
    Conflicts: dnscrypt-proxy
    License: ISC
    Section: net
    Description: DNSCrypt proxy
    """,
            [
                ("usr/sbin/dnscrypt-proxy", elf(dnscrypt / "dnscrypt-proxy"), 0o755),
                (
                    "etc/init.d/dnscrypt-proxy",
                    (FILES / "dnscrypt-proxy.init").read_bytes(),
                    0o755,
                ),
                (
                    "etc/dnscrypt-proxy2/dnscrypt-proxy.toml",
                    (FILES / "dnscrypt-proxy.toml").read_bytes(),
                    0o644,
                ),
                (
                    "etc/dnscrypt-proxy2/blocked-names.txt",
                    (dnscrypt / "example-blocked-names.txt").read_bytes(),
                    0o644,
                ),
            ]
            + [
                (f"etc/dnscrypt-proxy2/{f.name}", f.read_bytes(), 0o644)
                for f in sorted(lists.iterdir())
            ],
            ["/etc/dnscrypt-proxy2/dnscrypt-proxy.toml"],
        )
