from pathlib import Path

from opal_pkgs.pack import (
    FAILED,
    load_exports,
    load_names,
    pack,
    so,
    tree,
)

LATEST = (
    "https://openssl-library.org/source/old/1.1.1/index.html",
    r"openssl-(1\.1\.1w)\.tar\.gz",
    ".asc",
)
# 1.1.1 is public-EOL. New CVE fixes are Freexian ELTS debian revisions, not
# new upstream tarballs. update() fails when the pool is ahead of this pin.
FREEXIAN = (
    "https://deb.freexian.com/extended-lts/pool/main/o/openssl/",
    r"openssl_1\.1\.1w-0(?:\+|%2B)deb11u(\d+)\.debian\.tar\.xz",
    8,
)

ABI = Path(__file__).resolve().parent / "abi"
LIBSSL_VERDEFS = [
    "libssl.so.1.1",
    "OPENSSL_1_1_0",
    "OPENSSL_1_1_0d",
    "OPENSSL_1_1_1",
    "OPENSSL_1_1_1a",
]
LIBCRYPTO_VERDEFS = [
    "libcrypto.so.1.1",
    "OPENSSL_1_1_0",
    "OPENSSL_1_1_0a",
    "OPENSSL_1_1_0c",
    "OPENSSL_1_1_0d",
    "OPENSSL_1_1_0f",
    "OPENSSL_1_1_0g",
    "OPENSSL_1_1_0h",
    "OPENSSL_1_1_0i",
    "OPENSSL_1_1_0j",
    "OPENSSL_1_1_1",
    "OPENSSL_1_1_1b",
    "OPENSSL_1_1_1c",
    "OPENSSL_1_1_1d",
    "OPENSSL_1_1_1e",
    "OPENSSL_1_1_1h",
]


def api_exports(path):
    """Stock fixtures include VERDEF node names as absolute symbols; zig does not."""
    return {
        (name, ver)
        for name, ver in load_exports(path)
        if name != ver and not name.startswith("GCC_") and not name.startswith("GLIBC_")
    }


def pack_pkg():
    if "libopenssl" in FAILED:
        return
    root = tree("libopenssl")
    libc = load_names(ABI / "libc.exports")
    libgcc = load_names(ABI / "libgcc_s.exports")
    crypto_exports = api_exports(ABI / "openssl-1.1.1i.libcrypto.exports")
    ssl_exports = api_exports(ABI / "openssl-1.1.1i.libssl.exports")
    crypto_names = {name for name, _ver in crypto_exports}
    crypto = so(
        root / "libcrypto.so.1.1",
        "libcrypto.so.1.1",
        {"libc.so", "libgcc_s.so.1"},
        LIBCRYPTO_VERDEFS,
        crypto_exports,
        undef_allow=libc | libgcc,
    )
    ssl = so(
        root / "libssl.so.1.1",
        "libssl.so.1.1",
        {"libc.so", "libgcc_s.so.1", "libcrypto.so.1.1"},
        LIBSSL_VERDEFS,
        ssl_exports,
        undef_allow=libc | libgcc | crypto_names,
    )
    consumers = load_exports(ABI / "openssl-consumers.imports")
    missing = consumers - crypto_exports - ssl_exports
    if missing:
        sample = sorted(missing)[:5]
        raise SystemExit(f"libopenssl: consumer imports missing e.g. {sample}")
    pack(
        "libopenssl",
        "libopenssl",
        "mips_siflower",
        """
    Depends: libc
    License: OpenSSL
    Section: libs
    Description: OpenSSL 1.1.1w shared libraries (ABI-compatible with 1.1.1i, Freexian ELTS 1.1.1w-0+deb11u8)
    """,
        [
            ("usr/lib/libcrypto.so.1.1", crypto, 0o644),
            ("usr/lib/libssl.so.1.1", ssl, 0o644),
        ],
    )
