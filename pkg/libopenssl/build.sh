# Shared libssl/libcrypto 1.1.1w for the Opal. no-asm: zig's clang misassembles MIPS asm.
# Also builds apps/openssl for the openssl-util ipk.
unpack libopenssl
cd "$WORK/libopenssl-$(ver libopenssl)"
if [ ! -f libssl.so.1.1 ]; then
  for p in "$ROOT"/pkg/libopenssl/patches/*.patch; do
    patch -p1 < "$p" || exit 1
  done
  unset CFLAGS CPPFLAGS LDFLAGS LDLIBS
  CC=mipsel-musl-so-cc AR=mipsel-linux-musl-ar RANLIB=mipsel-linux-musl-ranlib \
    ./Configure linux-mipsel-openwrt --prefix=/usr --libdir=lib --openssldir=/etc/ssl \
    shared no-asm -DOPENSSL_PREFER_CHACHA_OVER_GCM \
    no-rfc3779 no-camellia no-aria no-ec2m no-idea no-comp no-seed \
    no-whirlpool no-mdc2 no-sm2 no-sm3 no-sm4 no-blake2 \
    no-afalgeng no-hw-padlock no-gost || exit 1
  SOURCE_DATE_EPOCH=1694441316 make -j"$JOBS" build_libs || exit 1
fi
# libapps is a static lib linked into the executable, so Configure builds it
# with -fPIC. lld's MIPS global GOT is not in dynsym order and musl fills it
# from that order, so those calls land in the wrong function.
# shortcut: the compile line is the line after an apps/ target. redo this if
# the generated makefile stops looking like that.
perl -pi -e 's/\$\(LIB_CFLAGS\)/\$\(BIN_CFLAGS\)/ if $apps; $apps = /^apps\//' Makefile || exit 1
rm -f apps/*.o apps/libapps.a apps/openssl
SOURCE_DATE_EPOCH=1694441316 make -j"$JOBS" build_apps || exit 1
