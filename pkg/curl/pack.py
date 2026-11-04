LATEST = ('https://curl.se/download/', 'curl-(\\d+\\.\\d+\\.\\d+)\\.tar\\.xz', '.asc')

def pack_pkg():
    if "curl" not in FAILED:
        pack("curl", "curl", "mips_siflower", """
    Depends: libc, ca-bundle
    License: MIT
    Section: net
    Description: Static curl with mbedTLS for the GL-SFT1200. The system libcurl stays for GL programs.
    """, [("usr/bin/curl", elf(tree("curl") / "src" / "curl"), 0o755)])
