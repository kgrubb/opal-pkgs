# opal-pkgs

opkg feed for the GL.iNet Opal (GL-SFT1200) on firmware 4.8.3. Each package
replaces the stock package of the same name.

```sh
echo 'src/gz opal https://kgrubb.github.io/opal-pkgs' >> /etc/opkg/customfeeds.conf
opkg update
opkg upgrade ethtool
```

Upgrade by package name. A bare `opkg upgrade` also replaces running services
such as `dropbear` and `dnscrypt-proxy2`. Every published ipk stays in the
feed, so an older build can be reinstalled by URL with `--force-downgrade`.

## How it works

- `versions` pins each upstream source by version and SHA-256.
- `build.sh` cross-compiles static binaries against musl 1.1.20, which keeps
  the 32-bit `time_t` that the router's Linux 4.14 kernel needs. `pack.py`
  turns them into ipks in `out/`.
- `.github/workflows/feed.yml` checks upstream every Monday. A new release
  must carry a valid signature from the maintainer key in `keys/`. CI then
  builds it, commits the new pin to `main` once the build passes, and
  publishes the new ipks. The CA bundle has no upstream signature and relies
  on HTTPS.
- The `feed` branch is what GitHub Pages serves. It is append-only: CI adds
  new filenames and never replaces or removes one.

Changing a package's files without an upstream release needs a bump in the
`release` column. Otherwise the filename already exists and the build is not
published.
