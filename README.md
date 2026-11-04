# opal-pkgs

opkg feed for the GL.iNet Opal (GL-SFT1200) on firmware 4.8.3. Each package
replaces the stock package of the same name.

```sh
echo 'src/gz opal https://kgrubb.github.io/opal-pkgs' >> /etc/opkg/customfeeds.conf
opkg update
opkg upgrade ethtool
```

Upgrade by package name. A bare `opkg upgrade` also replaces running services
such as `dropbear` and `dnscrypt-proxy2`.

To publish a package, add its `.ipk` to `packages/` and push to `main`. The
workflow rebuilds `Packages.gz` and deploys the feed.
