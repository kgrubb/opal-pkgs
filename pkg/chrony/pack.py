from pathlib import Path

from opal_pkgs.pack import FAILED, elf, pack, tree

FILES = Path(__file__).parent / "files"

LATEST = (
    "https://chrony-project.org/download.html",
    "chrony-(\\d+\\.\\d+(?:\\.\\d+)?)\\.tar\\.gz",
    "https://chrony-project.org/releases/chrony-{v}-tar-gz-asc.txt",
)


def pack_pkg():
    if "chrony" not in FAILED:
        chronyd = elf(tree("chrony") / "chronyd")
        if b"+PRIVDROP" not in chronyd:
            raise SystemExit("chronyd was built without libcap and would stay root")
        pack(
            "chrony",
            "chrony",
            "mips_siflower",
            """
    Depends: libc
    Require-User: chrony=323:chrony=323
    License: GPL-2.0
    Section: net
    Description: NTP client and server
    """,
            [
                ("usr/sbin/chronyd", chronyd, 0o755),
                ("usr/bin/chronyc", elf(tree("chrony") / "chronyc"), 0o755),
                ("etc/init.d/chronyd", (FILES / "chronyd.init").read_bytes(), 0o755),
                (
                    "etc/hotplug.d/iface/20-chrony",
                    (FILES / "chrony.hotplug").read_bytes(),
                    0o755,
                ),
                ("etc/chrony/chrony.conf", (FILES / "chrony.conf").read_bytes(), 0o600),
                ("etc/config/chrony", (FILES / "chrony.config").read_bytes(), 0o600),
            ],
            ["/etc/chrony/chrony.conf", "/etc/config/chrony"],
        )
