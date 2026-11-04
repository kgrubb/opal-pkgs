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
printf '%s\n' '#include <time.h>' 'int time_t_is_32bit[1/(sizeof(time_t)==4)];' > "$WORK/time_t.c"
$CC -c -o "$WORK/time_t.o" "$WORK/time_t.c"

# A failed package is recorded and its pin put back, so the others still publish.
: > "$WORK/failed"
fail() {
  printf '%s\n' "$1" >> "$WORK/failed"
  echo "build failed: $1" >&2
  base=${VERSIONS_BASE:-}
  if [ -f "$base" ]; then
    awk -F '\t' -v n="$1" -f "$ROOT/restore.awk" "$base" versions > "$WORK/versions.new" && mv "$WORK/versions.new" versions
  fi
}

if ! (
  set -e
  unpack dropbear
  cd "$WORK/dropbear-$(ver dropbear)"
  if [ ! -x dropbearmulti ]; then
    ./configure --host=mipsel-linux-musl CC=$CC \
      --disable-zlib --disable-pam --disable-lastlog \
      --disable-utmp --disable-utmpx --disable-wtmp --disable-wtmpx \
      --disable-pututline --disable-pututxline
    # CFLAGS stays unset on the make line so libtommath keeps its CFLAGS += -I../src.
    # One multi-call binary, like stock OpenWrt: the ssh and scp alternatives point at it.
    make -j"$JOBS" STATIC=1 MULTI=1 PROGRAMS="dropbear dbclient dropbearkey scp" \
      LDFLAGS="-Wl,-z,now -Wl,-z,relro -Wl,--gc-sections"
  fi
); then fail dropbear; fi

# Netlink ethtool needs Linux 5.6, so this build uses the ioctl interface.
if ! (
  set -e
  unpack ethtool
  cd "$WORK/ethtool-$(ver ethtool)"
  if [ ! -x ethtool ]; then
    ./configure --host=mipsel-linux-musl --disable-netlink CC=$CC CFLAGS="-Os -I$ROOT/kheaders"
    make -j"$JOBS"
  fi
); then fail ethtool; fi

if ! (
  set -e
  unpack i2c-tools
  cd "$WORK/i2c-tools-$(ver i2c-tools)"
  # CFLAGS comes from the environment so the makefile's CFLAGS += still applies.
  if [ ! -x tools/i2cget ]; then
    CC=$CC CFLAGS="-Os -I$ROOT/kheaders" make -j"$JOBS" \
      AR=mipsel-linux-musl-ar USE_STATIC_LIB=1 BUILD_DYNAMIC_LIB=0
  fi
); then fail i2c-tools; fi

# sudoers is linked into sudo, so the package ships no plugin .so files.
if ! (
  set -e
  unpack sudo
  cd "$WORK/sudo-$(ver sudo)"
  if [ ! -x src/sudo ]; then
    ./configure --host=mipsel-linux-musl CC=$CC CFLAGS="-Os" \
      --prefix=/usr --sbindir=/usr/sbin --libexecdir=/usr/lib/sudo \
      --sysconfdir=/etc --with-rundir=/var/run/sudo --with-vardir=/var/lib/sudo \
      --with-editor=/bin/vi --without-pam --without-sendmail --disable-zlib \
      --disable-shared --enable-static-sudoers --disable-shared-libutil
    make -j"$JOBS"
  fi
); then fail sudo; fi

if ! (
  set -e
  unpack dnscrypt-proxy
  # Unpinned because the lists change daily. dnscrypt-proxy checks each minisig before use.
  lists=$WORK/dnscrypt-lists
  mkdir -p "$lists"
  for f in public-resolvers.md relays.md odoh-servers.md; do
    for g in "$f" "$f.minisig"; do
      curl -fsSL --retry 3 -o "$lists/$g" "https://download.dnscrypt.info/resolvers-list/v3/$g"
    done
  done
); then fail dnscrypt-proxy; fi

if ! ( set -e; src cacert >/dev/null ); then fail cacert; fi

# The kernel module stays stock. PLATFORM=linux because the build host is not the router.
if ! (
  set -e
  unpack wireguard-tools
  cd "$WORK/wireguard-tools-$(ver wireguard-tools)/src"
  if [ ! -x wg ]; then
    # -idirafter so this release's wireguard.h is used, and the toolchain fills in the other kernel headers.
    PLATFORM=linux CC=$CC CFLAGS="-Os -Iuapi/linux -idirafter ${ZIG%/*}/lib/libc/include/any-linux-any" \
      make -j"$JOBS" wg
  fi
); then fail wireguard-tools; fi

# libpcap is linked into softflowd. The router's libpcap package stays.
if ! (
  set -e
  if ! command -v autoreconf >/dev/null || ! command -v flex >/dev/null || ! command -v bison >/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq autoconf automake flex bison
  fi
  kinc="-idirafter ${ZIG%/*}/lib/libc/include/any-linux-any -idirafter ${ZIG%/*}/lib/libc/include/mips-linux-any"
  unpack libpcap
  unpack softflowd
  pcap=$WORK/libpcap-$(ver libpcap)
  if [ ! -f "$pcap/libpcap.a" ]; then
    (
      cd "$pcap"
      CFLAGS="-Os $kinc" ./configure --host=mipsel-linux-musl --disable-shared --without-libnl --with-pcap=linux CC=$CC
      make -j"$JOBS"
    )
  fi
  cd "$WORK/softflowd-$(ver softflowd)"
  if [ ! -x softflowd ]; then
    autoreconf -fi
    # --host=mipsel-linux-musl does not match the linux-gnu* check, so the interface index code is compiled out.
    CFLAGS="-Os -DLINUX $kinc" CPPFLAGS="-I$pcap" LDFLAGS="-L$pcap" \
      ./configure --host=mipsel-linux-musl CC=$CC
    make -j"$JOBS"
  fi
); then fail softflowd; fi

# mbedTLS is linked into curl. The router's libcurl and OpenSSL packages stay for the GL programs that load them.
# Protocols match the stock curl: file, ftp, ftps, http, https.
if ! (
  set -e
  unpack mbedtls
  unpack curl
  mbed=$WORK/mbedtls-$(ver mbedtls)
  # set -e does not apply inside an if condition, so each step that can fail exits on its own.
  if [ ! -f "$mbed/library/libmbedtls.a" ]; then
    # mbedTLS only calls getrandom() under glibc. Its fallback reads /dev/random, which blocks on kernel 4.14.
    sed -i.orig 's/defined(__linux__) && defined(__GLIBC__)/defined(__linux__)/' "$mbed/library/entropy_poll.c"
    grep -q '^#if ((defined(__linux__)) ||' "$mbed/library/entropy_poll.c" || exit 1
    make -C "$mbed/library" -j"$JOBS" CC=$CC AR=mipsel-linux-musl-ar CFLAGS="-Os" static || exit 1
  fi
  cd "$WORK/curl-$(ver curl)"
  if [ ! -x src/curl ]; then
    CPPFLAGS="-I$mbed/include" LDFLAGS="-L$mbed/library" ./configure --host=mipsel-linux-musl CC=$CC CFLAGS="-Os" \
      --disable-shared --with-mbedtls --without-zlib --without-brotli --without-zstd --without-libpsl \
      --without-nghttp2 --without-libidn2 --disable-ldap --disable-manual --disable-docs \
      --disable-dict --disable-gopher --disable-imap --disable-ipfs --disable-mqtt --disable-pop3 \
      --disable-rtsp --disable-smtp --disable-telnet --disable-tftp --disable-websockets \
      --enable-ipv6 --with-ca-bundle=/etc/ssl/certs/ca-certificates.crt --with-ca-path=/etc/ssl/certs &&
    make -j"$JOBS"
  fi
); then fail curl; fi

# Same compile options as the stock dnsmasq-full: ubus, conntrack, ipset, and DNSSEC through nettle's mini-gmp.
# libubox and libubus are the commits the router's ubusd runs, so the wire protocol matches.
if ! (
  set -e
  kinc="-idirafter ${ZIG%/*}/lib/libc/include/any-linux-any -idirafter ${ZIG%/*}/lib/libc/include/mips-linux-any"
  deps=$WORK/dnsmasq-deps
  for p in nettle libmnl libnfnetlink libnetfilter_conntrack libubox ubus dnsmasq; do unpack "$p"; done
  if [ ! -f "$deps/lib/libnetfilter_conntrack.a" ]; then
    (
      cd "$WORK/nettle-$(ver nettle)"
      CFLAGS="-Os" ./configure --host=mipsel-linux-musl CC=$CC --prefix="$deps" --libdir="$deps/lib" \
        --disable-shared --enable-mini-gmp --disable-documentation --disable-openssl &&
      make -j"$JOBS" install
    ) || exit 1
    for p in libmnl libnfnetlink libnetfilter_conntrack; do
      (
        cd "$WORK/$p-$(ver "$p")"
        CFLAGS="-Os $kinc" LIBMNL_CFLAGS="-I$deps/include" LIBMNL_LIBS="-L$deps/lib -lmnl" \
          LIBNFNETLINK_CFLAGS="-I$deps/include" LIBNFNETLINK_LIBS="-L$deps/lib -lnfnetlink" \
          ./configure --host=mipsel-linux-musl CC=$CC --prefix="$deps" --disable-shared --enable-static &&
        make -j"$JOBS" install
      ) || exit 1
    done
  fi
  if [ ! -f "$deps/lib/libubus.a" ]; then
    mkdir -p "$deps/include/libubox"
    (
      cd "$WORK/libubox-$(ver libubox)"
      for f in avl avl-cmp blob blobmsg uloop usock ustream ustream-fd vlist utils safe_list runqueue md5 kvlist ulog base64; do
        $CC -Os -I. $kinc -c -o "$f.o" "$f.c" || exit 1
      done
      cp ./*.h "$deps/include/libubox/" && mipsel-linux-musl-ar rcs "$deps/lib/libubox.a" ./*.o
    ) || exit 1
    (
      cd "$WORK/ubus-$(ver ubus)"
      for f in libubus libubus-io libubus-obj libubus-sub libubus-req libubus-acl; do
        $CC -Os -I. -I"$deps/include" $kinc -DUBUS_UNIX_SOCKET='"/var/run/ubus.sock"' -DUBUS_MAX_MSGLEN=1048576 \
          -c -o "$f.o" "$f.c" || exit 1
      done
      cp libubus.h ubusmsg.h ubus_common.h "$deps/include/" && mipsel-linux-musl-ar rcs "$deps/lib/libubus.a" ./*.o
    ) || exit 1
  fi
  cd "$WORK/dnsmasq-$(ver dnsmasq)"
  if [ ! -x src/dnsmasq ]; then
    make -j"$JOBS" CC=$CC COPTS="-DHAVE_UBUS -DHAVE_CONNTRACK -DHAVE_DNSSEC -DNO_GMP -DNO_ID" \
      CFLAGS="-Os -I$deps/include $kinc" LDFLAGS="-L$deps/lib" \
      ubus_libs="-lubus -lubox" ct_cflags= ct_libs="-lnetfilter_conntrack -lnfnetlink -lmnl" \
      nettle_cflags= nettle_libs="-lhogweed -lnettle" gmp_libs=
  fi
); then fail dnsmasq; fi

# Paths and user match the stock chrony. libcap is linked in so chronyd still drops root to the chrony user.
if ! (
  set -e
  unpack libcap
  unpack chrony
  cap=$WORK/libcap-$(ver libcap)/libcap
  if [ ! -f "$cap/libcap.a" ]; then
    # The capability name table is generated with GNU sed syntax. chronyd parses those names to drop root.
    make -C "$cap" CC=$CC BUILD_CC=cc AR=mipsel-linux-musl-ar RANLIB=mipsel-linux-musl-ranlib \
      BUILD_SED="$(command -v gsed || echo sed)" COPTS=-Os GOLANG=no SHARED=no USE_GPERF=no libcap.a || exit 1
    grep -q '^{"cap_chown",0},$' "$cap/cap_names.list.h" || { rm -f "$cap/libcap.a"; exit 1; }
  fi
  cd "$WORK/chrony-$(ver chrony)"
  if [ ! -x chronyd ]; then
    CC=$CC CFLAGS="-Os" CPPFLAGS="-I$cap/include -I$cap/include/uapi" LDFLAGS="-L$cap" ./configure \
      --host-system=Linux --host-release=4.14.90 --host-machine=mips \
      --prefix=/usr --sysconfdir=/etc/chrony --localstatedir=/var --chronyrundir=/var/run/chrony \
      --with-user=chrony --disable-readline --disable-rtc --disable-sechash --disable-nts --without-seccomp &&
    make -j"$JOBS"
  fi
); then fail chrony; fi

python3 pack.py || fail pack
if [ -s "$WORK/failed" ] && [ ! -f "${VERSIONS_BASE:-}" ]; then
  exit 1
fi
