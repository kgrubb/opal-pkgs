from pathlib import Path

from opal_pkgs.pack import FAILED, load_names, pack, so, tree

# OpenWrt 22.03 names the snapshot. The date is the opkg version.
# The archive commit is PKG_SOURCE_VERSION. No maintainer signature.
LATEST = (
    "https://raw.githubusercontent.com/openwrt/openwrt/openwrt-22.03/package/libs/ustream-ssl/Makefile",
    r"PKG_SOURCE_DATE:=(\d{4}-\d{2}-\d{2})",
    None,
)

OPENSSL_ABI = Path(__file__).resolve().parents[1] / "libopenssl" / "abi"
REQUIRED = {
    ("ustream_ssl_ops", ""),
    ("__ustream_ssl_session_free", ""),
}
# Resolved by the router's libubox.so at runtime.
UBOX = {
    "uloop_timeout_cancel",
    "uloop_timeout_set",
    "ustream_consume",
    "ustream_fill_read",
    "ustream_get_read_buf",
    "ustream_init_defaults",
    "ustream_reserve",
    "ustream_set_read_blocked",
    "ustream_write",
    "ustream_write_pending",
}


def pack_pkg():
    if "libustream-openssl" in FAILED:
        return
    so_path = tree("libustream-openssl") / "libustream-ssl.so"
    libc = load_names(OPENSSL_ABI / "libc.exports")
    libgcc = load_names(OPENSSL_ABI / "libgcc_s.exports")
    crypto = load_names(OPENSSL_ABI / "openssl-1.1.1i.libcrypto.exports")
    ssl = load_names(OPENSSL_ABI / "openssl-1.1.1i.libssl.exports")
    data = so(
        so_path,
        "libustream-ssl.so",
        {
            "libc.so",
            "libgcc_s.so.1",
            "libcrypto.so.1.1",
            "libssl.so.1.1",
            "libubox.so",
        },
        [],
        REQUIRED,
        undef_allow=libc | libgcc | crypto | ssl | UBOX,
    )
    pack(
        "libustream-openssl",
        "libustream-openssl",
        "mips_siflower",
        """
    Depends: libc, libubox, libopenssl
    License: ISC
    Section: libs
    Description: ustream SSL Library (openssl)
    """,
        [("lib/libustream-ssl.so", data, 0o644)],
    )
