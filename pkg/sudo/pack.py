from pathlib import Path

from opal_pkgs.pack import FAILED, elf, pack, tree

FILES = Path(__file__).parent / "files"

LATEST = (
    "https://www.sudo.ws/dist/",
    "sudo-(\\d+\\.\\d+\\.\\d+(?:p\\d+)?)\\.tar\\.gz",
    ".sig",
)


def pack_pkg():
    if "sudo" not in FAILED:
        sudo = tree("sudo")
        pack(
            "sudo",
            "sudo",
            "mips_siflower",
            """
    Depends: libc
    License: ISC
    Section: admin
    Description: execute a command as another user, with sudoers compiled in
    """,
            [
                ("usr/bin/sudo", elf(sudo / "src" / "sudo"), 0o4755),
                (
                    "usr/sbin/visudo",
                    elf(sudo / "plugins" / "sudoers" / "visudo"),
                    0o755,
                ),
                ("etc/sudoers", (FILES / "sudoers").read_bytes(), 0o440),
                ("etc/init.d/sudo", (FILES / "sudo.init").read_bytes(), 0o755),
                ("lib/upgrade/keep.d/sudo", (FILES / "sudo.keep").read_bytes(), 0o644),
            ],
            ["/etc/sudoers"],
        )
