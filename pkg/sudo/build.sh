# sudoers is linked into sudo, so the package ships no plugin .so files.
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
