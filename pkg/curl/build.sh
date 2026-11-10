# mbedTLS is linked into curl. The router's libcurl and OpenSSL packages stay for the GL programs that load them.
# Protocols match the stock curl: file, ftp, ftps, http, https.
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
unpack zlib
# Separate tree from pkg/zlib's shared build.
z=$WORK/zlib-static-$(ver zlib)
if [ ! -f "$z/libz.a" ]; then
  rm -rf "$z"
  cp -a "$WORK/zlib-$(ver zlib)" "$z"
  (cd "$z" && CC=$CC CFLAGS="-Os" AR=mipsel-linux-musl-ar RANLIB=mipsel-linux-musl-ranlib CHOST=mipsel-linux \
    ./configure --static && make -j"$JOBS" libz.a) || exit 1
fi
cd "$WORK/curl-$(ver curl)"
if [ ! -x src/curl ]; then
  CPPFLAGS="-I$mbed/include -I$z" LDFLAGS="-L$mbed/library -L$z" ./configure --host=mipsel-linux-musl CC=$CC CFLAGS="-Os" \
    --disable-shared --with-mbedtls --with-zlib --without-brotli --without-zstd --without-libpsl \
    --without-nghttp2 --without-libidn2 --disable-ldap --disable-manual --disable-docs \
    --disable-dict --disable-gopher --disable-imap --disable-ipfs --disable-mqtt --disable-pop3 \
    --disable-rtsp --disable-smtp --disable-telnet --disable-tftp --disable-websockets \
    --enable-ipv6 --with-ca-bundle=/etc/ssl/certs/ca-certificates.crt --with-ca-path=/etc/ssl/certs &&
  # configure only warns when --with-zlib finds nothing.
  grep -q '^#define HAVE_LIBZ 1' lib/curl_config.h &&
  make -j"$JOBS"
fi
