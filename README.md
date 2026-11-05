# opal-pkgs

Newer upstream releases of the userspace on a GL.iNet Opal (GL-SFT1200) running firmware 4.8.3. Each package replaces the stock package of the same name.

On the router:

```sh
echo 'src/gz opal https://kgrubb.github.io/opal-pkgs' >> /etc/opkg/customfeeds.conf
opkg update
opkg list-upgradable | awk '{print $1}' | xargs -r opkg upgrade
```

Every published ipk stays in the feed. Reinstall an older file by URL with `--force-downgrade`.
