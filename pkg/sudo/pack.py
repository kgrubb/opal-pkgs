LATEST = ('https://www.sudo.ws/dist/', 'sudo-(\\d+\\.\\d+\\.\\d+(?:p\\d+)?)\\.tar\\.gz', '.sig')

def pack_pkg():
    if "sudo" not in FAILED:
        sudo = tree("sudo")
        pack("sudo", "sudo", "mips_siflower", """
    Depends: libc
    License: ISC
    Section: admin
    Description: Static sudo with built-in sudoers for the GL-SFT1200
    """, [
        ("usr/bin/sudo", elf(sudo / "src" / "sudo"), 0o4755),
        ("usr/sbin/visudo", elf(sudo / "plugins" / "sudoers" / "visudo"), 0o755),
        ("etc/sudoers", (FILES / "sudoers").read_bytes(), 0o440),
        ("etc/init.d/sudo", (FILES / "sudo.init").read_bytes(), 0o755),
        ("lib/upgrade/keep.d/sudo", (FILES / "sudo.keep").read_bytes(), 0o644),
    ], ["/etc/sudoers"])
