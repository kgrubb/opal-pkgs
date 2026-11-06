# Drop-in for stock openvpn-openssl 2.6.12: OpenSSL, LZO, LZ4, ifconfig.
# Kernel 4.14 has no ovpn-dco. 2.7 would run a dns script these configs do not have.
# LZO 2.10 (2017) is the last upstream release.
unpack lzo
unpack lz4
unpack libcap-ng
unpack libopenssl
unpack openvpn-openssl
lzo=$WORK/lzo-$(ver lzo)
lz4=$WORK/lz4-$(ver lz4)
capng=$WORK/libcap-ng-$(ver libcap-ng)
ssl=$WORK/libopenssl-$(ver libopenssl)
src=$WORK/openvpn-openssl-$(ver openvpn-openssl)
# Host ranlib writes a Mach-O index and leaves an empty archive.
# -fno-pic: -fPIC makes a MIPS global GOT and musl fills it from the wrong dynsym order.
ar=mipsel-linux-musl-ar
ranlib=mipsel-linux-musl-ranlib
if [ ! -f "$lzo/src/.libs/liblzo2.a" ]; then
  (
    cd "$lzo"
    ./configure --host=mipsel-linux --disable-shared --enable-static \
      CC=$CC AR=$ar RANLIB=$ranlib CFLAGS="-Os -fno-pic"
    make -j"$JOBS" src/liblzo2.la
  )
fi
if [ ! -f "$lz4/lib/liblz4.a" ]; then
  # MULTITHREAD=0 keeps pthread out of the static library.
  make -C "$lz4/lib" -j"$JOBS" liblz4.a MULTITHREAD=0 \
    CC=$CC AR=$ar RANLIB=$ranlib CFLAGS="-Os -fno-pic"
fi
if [ ! -f "$capng/src/.libs/libcap-ng.a" ]; then
  if ! grep -q '__fsetlocking' "$capng/src/cap-ng.c"; then
    patch -d "$capng" -p1 < "$ROOT/pkg/openvpn-openssl/patches/musl-stdio.patch"
  fi
  # The git tag has no configure. These are the headers this musl sysroot has.
  cat > "$capng/config.h" <<'EOF'
#define HAVE_PTHREAD_H 1
#define HAVE_SYSCALL_H 1
#define HAVE_LINUX_SECUREBITS_H 1
#define HAVE_LINUX_MAGIC_H 1
#define HAVE_SYS_XATTR_H 1
EOF
  mkdir -p "$capng/src/.libs"
  # capability.h is a Linux UAPI header, not in the musl sysroot.
  kinc="-idirafter ${ZIG%/*}/lib/libc/include/any-linux-any -idirafter ${ZIG%/*}/lib/libc/include/mips-linux-any"
  (
    cd "$capng/src"
    $CC -c -Os -fno-pic -D_GNU_SOURCE -I. -I.. $kinc cap-ng.c
    $CC -c -Os -fno-pic -D_GNU_SOURCE -I. -I.. $kinc lookup_table.c
    $ar cr .libs/libcap-ng.a cap-ng.o lookup_table.o
    $ranlib .libs/libcap-ng.a
  )
fi
if [ ! -x "$src/src/openvpn/openvpn" ]; then
  mkdir -p "$src/pc"
  cat > "$src/pc/libcap-ng.pc" <<EOF
Name: libcap-ng
Description: libcap-ng
Version: $(ver libcap-ng)
Libs: -L$capng/src/.libs -lcap-ng
Cflags: -I$capng/src
EOF
  cd "$src"
  # git rev-parse walks up into this repo, so the binary would embed our commit.
  PKG_CONFIG_LIBDIR="$src/pc" \
    GIT=false \
    CC=mipsel-musl-so-cc \
    CFLAGS="-Os" \
    LZO_CFLAGS="-I$lzo/include" \
    LZO_LIBS="-L$lzo/src/.libs -llzo2" \
    LZ4_CFLAGS="-I$lz4/lib" \
    LZ4_LIBS="-L$lz4/lib -llz4" \
    OPENSSL_CFLAGS="-I$ssl/include" \
    OPENSSL_LIBS="-L$ssl -lssl -lcrypto" \
    ac_cv_func_getpeereid=no \
    ./configure --host=mipsel-linux-musl \
    --disable-plugins --disable-dco --disable-dns-updown-by-default \
    --with-crypto-library=openssl
  # musl 1.1.20 has the getpeereid symbol and no declaration. SO_PEERCRED is the fallback.
  make -j"$JOBS" -C src/compat
  make -j"$JOBS" -C src/openvpn openvpn
fi
