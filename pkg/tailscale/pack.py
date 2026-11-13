from pathlib import Path

from opal_pkgs.pack import FAILED, elf, pack, tree, version

FILES = Path(__file__).parent / "files"

# The tag archive has no maintainer signature, so HTTPS is the only check.
LATEST = (
    "https://github.com/tailscale/tailscale/releases/latest",
    "/releases/tag/v(\\d+\\.\\d+\\.\\d+)",
    None,
)


def pack_pkg():
    if "tailscale" not in FAILED:
        built = elf(tree("tailscale") / "tailscaled")
        if version("tailscale").encode() not in built:
            raise SystemExit("tailscale version string does not match the pin")
        pack(
            "tailscale",
            "tailscale",
            "mips_siflower",
            """
    Depends: libc, ca-bundle, kmod-tun
    License: BSD-3-Clause
    Section: net
    Description: Tailscale client and subnet router
    """,
            [
                ("usr/sbin/tailscaled", built, 0o755),
                ("usr/sbin/tailscale", "tailscaled"),
                (
                    "etc/init.d/tailscale",
                    (FILES / "tailscale.init").read_bytes(),
                    0o755,
                ),
                (
                    "etc/config/tailscale",
                    (FILES / "tailscale.config").read_bytes(),
                    0o644,
                ),
            ],
            ["/etc/config/tailscale", "/etc/tailscale/tailscaled.state"],
        )
