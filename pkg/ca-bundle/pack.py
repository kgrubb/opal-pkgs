import re
import subprocess

# curl.se publishes no signature for the CA bundle, so HTTPS is the only check.
LATEST = ('https://curl.se/docs/caextract.html', 'cacert-(\\d{4}-\\d{2}-\\d{2})\\.pem', None)

def pack_pkg():
    if "ca-bundle" not in FAILED and "ca-certificates" not in FAILED:
        pem = (ROOT / ".cache" / PINS["ca-bundle"][4].replace("{v}", version("ca-bundle")).rsplit("/", 1)[1]).read_bytes()
        pack("ca-bundle", "ca-bundle", "all", """
    Depends: libc
    Provides: ca-certs
    License: MPL-2.0
    Section: base
    Description: Mozilla CA bundle for the GL-SFT1200
    """, [("etc/ssl/certs/ca-certificates.crt", pem, 0o644), ("etc/ssl/cert.pem", pem, 0o644)])

        # curl's cacert.pem puts each Mozilla label above its certificate, underlined with '='
        # and followed by '#' comment lines.
        certs, hashes = [], {}
        for label, cert in re.findall(rb"\n([^\n]+)\n=+\n(?:#[^\n]*\n)*(-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----)", pem, re.S):
            name = re.sub(r"[^A-Za-z0-9._+-]", "_", label.decode().strip().replace(" ", "_")) + ".crt"
            digest = subprocess.run(["openssl", "x509", "-noout", "-subject_hash"], input=cert, capture_output=True, check=True).stdout.decode().strip()
            certs += [(f"etc/ssl/certs/{name}", cert + b"\n", 0o644), (f"etc/ssl/certs/{digest}.{hashes.get(digest, 0)}", name)]
            hashes[digest] = hashes.get(digest, 0) + 1
        if len(certs) != 2 * pem.count(b"-----BEGIN CERTIFICATE-----") or len({c[0] for c in certs}) != len(certs):
            raise SystemExit("cacert.pem certificates did not all map to unique files")
        pack("ca-certificates", "ca-certificates", "all", """
    Depends: libc
    Provides: ca-certs
    License: MPL-2.0
    Section: base
    Description: Mozilla CA certificates for the GL-SFT1200
    """, certs)
