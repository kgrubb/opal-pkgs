LATEST = ('https://matt.ucc.asn.au/dropbear/releases/', 'dropbear-(\\d+\\.\\d+)\\.tar\\.bz2', '.asc')

def pack_pkg():
    if "dropbear" not in FAILED:
        dropbear = elf(tree("dropbear") / "dropbearmulti")
        if f"SSH-2.0-dropbear_{version('dropbear')}".encode() not in dropbear:
            raise SystemExit("dropbear banner does not match the pinned version")
        pack("dropbear", "dropbear", "mips_siflower", """
    Depends: libc
    Alternatives: 100:/usr/bin/ssh:/usr/sbin/dropbear, 100:/usr/bin/scp:/usr/sbin/dropbear
    License: MIT
    Section: net
    Description: Static Dropbear SSH server and client for the GL-SFT1200
    """, [
        ("usr/sbin/dropbear", dropbear, 0o755),
        ("usr/bin/dbclient", "../sbin/dropbear"),
        ("usr/bin/dropbearkey", "../sbin/dropbear"),
        ("etc/init.d/dropbear", (FILES / "dropbear.init").read_bytes(), 0o755),
        ("etc/config/dropbear", (FILES / "dropbear.config").read_bytes(), 0o644),
        # Empty like stock: opkg deletes an owned file the new package omits, conffile or not.
        ("etc/dropbear/dropbear_rsa_host_key", b"", 0o600),
    ], ["/etc/dropbear/dropbear_rsa_host_key", "/etc/config/dropbear"])
