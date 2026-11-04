# opal-pkgs

Newer upstream releases of the userspace on a GL.iNet Opal (GL-SFT1200) running firmware 4.8.3. Each package replaces the stock package of the same name.

On the router:

```sh
echo 'src/gz opal https://kgrubb.github.io/opal-pkgs' >> /etc/opkg/customfeeds.conf
opkg update
opkg upgrade
```

`opkg upgrade` installs the newer build of every package the feed and the router already share. ssh, dns, and ntp restart when those packages update. Reconnect ssh after it finishes.

Every published ipk stays in the feed. Reinstall an older file by URL with `--force-downgrade`.

## How it works

- `versions` pins each upstream source by version and SHA-256.
- `build.sh` cross-compiles static binaries against musl 1.1.20, which keeps
  the 32-bit `time_t` that the router's Linux 4.14 kernel needs. `pack.py`
  turns them into ipks in `out/`.
- `.github/workflows/feed.yml` checks upstream every Monday. A new release
  must carry a valid signature from the maintainer key in `keys/`. The CA
  bundle, wireguard-tools, and softflowd have no upstream signature and rely on HTTPS.
  softflowd links its own libpcap, so the router's libpcap package is left as it is.
  curl, dnsmasq, chrony, and snmpd link their libraries in the same way, so the
  router's libcurl, libnettle, libubus, and libcap packages stay for GL programs.
  Nothing else uses libnetsnmp, so opkg removes it when snmpd is upgraded.
  snmpd carries OpenWrt's 802.11 MIB patch, pinned to a commit in openwrt/packages.
  One package failing leaves the others to publish, and the run goes red.
- The `feed` branch is what GitHub Pages serves. It is append-only: CI adds
  new filenames and never replaces or removes one. A rebuilt ipk whose bytes
  differ from the published file gets the next release number, so the new
  build is published under its own name.
