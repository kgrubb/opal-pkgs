# Shared libcurl.so.4 with mbedTLS linked in statically so GL programs leave OpenSSL.
unpack mbedtls
unpack libcurl
# Separate tree from pkg/curl's non-PIC mbedtls.a.
mbed=$WORK/mbedtls-so-$(ver mbedtls)
if [ ! -f "$mbed/library/libmbedtls.a" ]; then
  rm -rf "$mbed"
  cp -a "$WORK/mbedtls-$(ver mbedtls)" "$mbed"
  sed -i.orig 's/defined(__linux__) && defined(__GLIBC__)/defined(__linux__)/' "$mbed/library/entropy_poll.c"
  grep -q '^#if ((defined(__linux__)) ||' "$mbed/library/entropy_poll.c" || exit 1
  # Drop the non-PIC .a files copied from pkg/curl's mbedtls tree.
  make -C "$mbed/library" clean >/dev/null 2>&1 || true
  make -C "$mbed/library" -j"$JOBS" CC=$CC AR=mipsel-linux-musl-ar CFLAGS="-Os -fPIC" static || exit 1
fi
# Out-of-tree so a prior static pkg/curl configure in the source tree is left alone.
build=$WORK/libcurl-build-$(ver libcurl)
src=$WORK/libcurl-$(ver libcurl)
so=$build/lib/.libs/libcurl.so.4.8.0
if [ ! -f "$so" ]; then
  rm -rf "$build"
  mkdir -p "$build"
  cd "$build"
  # zig reports host /usr/bin/ld so libtool disables shared; build a PIC .a then link .so ourselves.
  # musl 1.1.20 has no memset_explicit; zig's clang probe falsely detects it.
  CC=mipsel-musl-so-cc \
    CFLAGS="-Os -fPIC" \
    CPPFLAGS="-I$mbed/include" \
    LDFLAGS="-L$mbed/library" \
    ac_cv_func_memset_explicit=no \
    "$src/configure" --host=mipsel-linux-musl \
    --disable-shared --enable-static --disable-symbol-hiding \
    --with-mbedtls="$mbed" --without-zlib --without-brotli --without-zstd --without-libpsl \
    --without-nghttp2 --without-libidn2 --disable-ldap --disable-manual --disable-docs \
    --disable-dict --disable-gopher --disable-imap --disable-ipfs --disable-mqtt --disable-pop3 \
    --disable-rtsp --disable-smtp --disable-telnet --disable-tftp --disable-websockets \
    --enable-ipv6 --with-ca-bundle=/etc/ssl/certs/ca-certificates.crt --with-ca-path=/etc/ssl/certs || exit 1
  make -j"$JOBS" -C lib || exit 1
  mkdir -p "$build/lib/.libs"
  # version-script keeps mbedTLS out of the dynamic table (zig rejects --exclude-libs).
  mipsel-musl-so-cc -shared -o "$so" \
    -Wl,--whole-archive "$build/lib/.libs/libcurl.a" -Wl,--no-whole-archive \
    -L"$mbed/library" -lmbedtls -lmbedx509 -lmbedcrypto \
    -Wl,--version-script="$ROOT/pkg/libcurl/libcurl.vers" \
    -Wl,-soname,libcurl.so.4 || exit 1
  ln -sf libcurl.so.4.8.0 "$build/lib/.libs/libcurl.so.4"
fi
