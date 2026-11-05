from pathlib import Path

from opal_pkgs.pack import FAILED, elf, pack, tree, version

FILES = Path(__file__).parent / "files"

LATEST = (
    "https://sourceforge.net/projects/net-snmp/rss?path=/net-snmp",
    "net-snmp-(\\d+(?:\\.\\d+)+)\\.tar\\.gz",
    ".asc",
)


def pack_pkg():
    if "net-snmp" not in FAILED:
        snmpd = elf(tree("net-snmp") / "agent" / "snmpd")
        if version("net-snmp").encode() not in snmpd or b"ieee802dot11" not in snmpd:
            raise SystemExit("snmpd is the wrong version or lost the 802.11 MIB")
        if b"/usr/local/" in snmpd:
            raise SystemExit("snmpd would look for its config under /usr/local")
        pack(
            "snmpd",
            "net-snmp",
            "mips_siflower",
            """
    Depends: libc
    License: BSD-3-Clause
    Section: net
    Description: Static net-snmp agent for the GL-SFT1200
    """,
            [
                ("usr/sbin/snmpd", snmpd, 0o755),
                ("etc/snmp/snmpd.conf", "/var/run/snmpd.conf"),
                ("etc/config/snmpd", (FILES / "snmpd.config").read_bytes(), 0o644),
                ("etc/init.d/snmpd", (FILES / "snmpd.init").read_bytes(), 0o755),
            ],
            ["/etc/config/snmpd"],
        )
