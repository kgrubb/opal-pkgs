#!/bin/sh
# Build every package pinned in ./versions into out/.
set -eu
cd "$(dirname "$0")"
ROOT=$(pwd)
CACHE=$ROOT/.cache
WORK=$ROOT/work
JOBS=$(getconf _NPROCESSORS_ONLN)
mkdir -p "$CACHE" "$WORK"

field() { awk -F '\t' -v n="$1" -v f="$2" '$1 == n { print $f }' versions; }
ver() { field "$1" 2; }

# Download a pinned source once, verify it, and print its path.
src() {
  url=$(field "$1" 5 | sed "s/{v}/$(ver "$1")/g")
  file=$CACHE/${url##*/}
  [ -f "$file" ] || curl -fsSL --retry 3 -o "$file" "$url"
  echo "$(field "$1" 4)  $file" | shasum -a 256 -c - >&2
  echo "$file"
}

# Extract a pinned tarball into work/<name>-<version> once.
unpack() {
  dir=$WORK/$1-$(ver "$1")
  if [ ! -d "$dir" ]; then
    file=$(src "$1")
    mkdir -p "$dir"
    tar -xf "$file" -C "$dir" --strip-components=1
  fi
}

case $(uname -sm) in
  "Linux x86_64") zig=zig-x86_64-linux ;;
  "Darwin arm64") zig=zig-aarch64-macos ;;
  *) echo "unsupported build host: $(uname -sm)" >&2; exit 1 ;;
esac
unpack "$zig"
export ZIG="$WORK/$zig-$(ver "$zig")/zig"
export SYSROOT="$WORK/sysroot"
export PATH="$ROOT/bin:$PATH"
# Keep host libraries out of cross builds.
export PKG_CONFIG_LIBDIR=/nonexistent
CC=mipsel-musl-cc

# musl 1.1.20 keeps a 32-bit time_t. Newer musl calls time64 syscalls that Linux 4.14 lacks.
if [ ! -f "$SYSROOT/lib/libc.a" ]; then
  unpack musl
  (
    cd "$WORK/musl-$(ver musl)"
    CC=mipsel-cc ./configure --prefix="$SYSROOT" --target=mipsel --build=mipsel --disable-shared
    make -j"$JOBS" AR=mipsel-linux-musl-ar RANLIB=mipsel-linux-musl-ranlib
    make install
  )
fi
printf '%s\n' '#include <time.h>' 'int time_t_is_32bit[1/(sizeof(time_t)==4)];' |
  $CC -x c -c -o /dev/null -

unpack dropbear
(
  cd "$WORK/dropbear-$(ver dropbear)"
  if [ ! -x dropbear ]; then
    ./configure --host=mipsel-linux-musl CC=$CC \
      --disable-zlib --disable-pam --disable-lastlog \
      --disable-utmp --disable-utmpx --disable-wtmp --disable-wtmpx \
      --disable-pututline --disable-pututxline
    # CFLAGS stays unset on the make line so libtommath keeps its CFLAGS += -I../src.
    make -j"$JOBS" STATIC=1 PROGRAMS="dropbear dbclient dropbearkey" \
      LDFLAGS="-Wl,-z,now -Wl,-z,relro -Wl,--gc-sections"
  fi
)

# Netlink ethtool needs Linux 5.6, so this build uses the ioctl interface.
unpack ethtool
(
  cd "$WORK/ethtool-$(ver ethtool)"
  if [ ! -x ethtool ]; then
    ./configure --host=mipsel-linux-musl --disable-netlink CC=$CC CFLAGS="-Os -I$ROOT/kheaders"
    make -j"$JOBS"
  fi
)

unpack i2c-tools
(
  cd "$WORK/i2c-tools-$(ver i2c-tools)"
  # CFLAGS comes from the environment so the makefile's CFLAGS += still applies.
  if [ ! -x tools/i2cget ]; then
    CC=$CC CFLAGS="-Os -I$ROOT/kheaders" make -j"$JOBS" \
      AR=mipsel-linux-musl-ar USE_STATIC_LIB=1 BUILD_DYNAMIC_LIB=0
  fi
)

# sudoers is linked into sudo, so the package ships no plugin .so files.
unpack sudo
(
  cd "$WORK/sudo-$(ver sudo)"
  if [ ! -x src/sudo ]; then
    ./configure --host=mipsel-linux-musl CC=$CC CFLAGS="-Os" \
      --prefix=/usr --sbindir=/usr/sbin --libexecdir=/usr/lib/sudo \
      --sysconfdir=/etc --with-rundir=/var/run/sudo --with-vardir=/var/lib/sudo \
      --with-editor=/bin/vi --without-pam --without-sendmail --disable-zlib \
      --disable-shared --enable-static-sudoers --disable-shared-libutil
    make -j"$JOBS"
  fi
)

unpack dnscrypt-proxy
# Unpinned because the lists change daily. dnscrypt-proxy checks each minisig before use.
lists=$WORK/dnscrypt-lists
mkdir -p "$lists"
for f in public-resolvers.md relays.md odoh-servers.md; do
  for g in "$f" "$f.minisig"; do
    curl -fsSL --retry 3 -o "$lists/$g" "https://download.dnscrypt.info/resolvers-list/v3/$g"
  done
done

src cacert >/dev/null

python3 pack.py
