# The tag archive has no maintainer signature. libpcap is pinned in versions and linked in.
LATEST = ('https://github.com/irino/softflowd/tags', 'softflowd-v(\\d+\\.\\d+\\.\\d+)', None)

def pack_pkg():
    if "softflowd" not in FAILED:
        built = tree("softflowd")
        softflowd = elf(built / "softflowd")
        if version("softflowd").encode() not in softflowd:
            raise SystemExit("softflowd version string does not match the pin")
        pack("softflowd", "softflowd", "mips_siflower", """
    Depends: libc
    License: BSD-2-Clause
    Section: net
    Description: Static softflowd for the GL-SFT1200. libpcap is linked in, so the system libpcap stays.
    """, [
        ("usr/sbin/softflowd", softflowd, 0o755),
        ("usr/sbin/softflowctl", elf(built / "softflowctl"), 0o755),
        ("etc/init.d/softflowd", (FILES / "softflowd.init").read_bytes(), 0o755),
        ("etc/config/softflowd", (FILES / "softflowd.config").read_bytes(), 0o644),
    ], ["/etc/config/softflowd"])
