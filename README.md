# opal-pkgs

Newer upstream releases of the userspace on a GL.iNet Opal (GL-SFT1200) running firmware 4.8.3. Each package replaces the stock package of the same name.

## Usage

To get the latest releases on your router, ssh into it and run the following:

```sh
echo 'src/gz opal https://kgrubb.github.io/opal-pkgs' >> /etc/opkg/customfeeds.conf
opkg update
opkg list-upgradable | awk '{print $1}' | xargs -r opkg upgrade
```

Every published ipk stays in the feed, so if you need to reinstall an older version, use the `--force-downgrade` option.

## Adding a package

```
pkg/<name>/
  build.sh    # configure and make
  pack.py     # ipk contents and the upstream version check
  files/      # configs and init scripts, omit if there are none
  key.gpg     # signer. a minisign key is key.pub
```

`pkg/ethtool` is a small one to copy.

`versions` is tab-separated:

```
name	version	release	sha256	url
```

`{v}` in the url is the version. Start the release at 1. Packing bumps it when the feed already has that filename with different bytes.

`build.sh` can call `unpack` and `ver`. `$WORK`, `$ROOT`, `$CC`, and `$JOBS` are set. If the script exits, that package is recorded and the next one still runs.

`LATEST` in `pack.py` is the announcement page, a version regex, and a signature suffix: `.asc`, `.sign`, `.minisig`, or none. `pack_pkg` calls `pack` with the opkg name, the directory name, `mips_siflower` or `all`, the control fields, and the files to install.

A library is only the `versions` row. The recipe that uses it calls `unpack name` and `ver name`.

`pkg/dnscrypt-proxy` ships `dnscrypt-proxy2`. `ca-certificates` is the second ipk from `pkg/ca-bundle`.
