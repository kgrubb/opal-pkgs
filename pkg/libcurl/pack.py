from pathlib import Path

from opal_pkgs.pack import FAILED, WORK, _dyn, load_names, pack, so, version

# Same upstream tarball and signature as pkg/curl.
LATEST = ("https://curl.se/download/", "curl-(\\d+\\.\\d+\\.\\d+)\\.tar\\.xz", ".asc")

OPENSSL_ABI = Path(__file__).resolve().parents[1] / "libopenssl" / "abi"
# GL libgl-utils only needs these. ddns loads libcurl via libgl-utils.
REQUIRED = {
    "curl_easy_cleanup",
    "curl_easy_init",
    "curl_easy_perform",
    "curl_easy_setopt",
    "curl_global_cleanup",
    "curl_global_init",
}


def pack_pkg():
    if "libcurl" in FAILED:
        return
    libs = WORK / f"libcurl-build-{version('libcurl')}" / "lib" / ".libs"
    so_path = next(libs.glob("libcurl.so.4.*.*"), None) or next(
        libs.glob("libcurl.so.4*"), None
    )
    if so_path is None:
        raise SystemExit("libcurl: shared library missing under lib/.libs")
    libc = load_names(OPENSSL_ABI / "libc.exports")
    libgcc = load_names(OPENSSL_ABI / "libgcc_s.exports")
    data = so(
        so_path,
        "libcurl.so.4",
        {"libc.so", "libgcc_s.so.1"},
        [],
        {(name, "") for name in REQUIRED},
        undef_allow=libc | libgcc,
    )
    needed = set(_dyn(so_path)["needed"])
    if needed & {"libssl.so.1.1", "libcrypto.so.1.1"}:
        raise SystemExit(f"libcurl: still NEEDED OpenSSL: {sorted(needed)}")
    real = so_path.name
    pack(
        "libcurl",
        "libcurl",
        "mips_siflower",
        """
    Depends: libc, ca-bundle
    License: MIT
    Section: libs
    Description: client-side URL transfer library (mbedTLS)
    """,
        [
            (f"usr/lib/{real}", data, 0o755),
            ("usr/lib/libcurl.so.4", real),
        ],
    )
