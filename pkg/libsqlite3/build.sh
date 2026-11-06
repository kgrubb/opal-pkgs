# Drop-in libsqlite3.so.0. Stock 3.31.1 has no symbol versions.
# Flags match the options string in the stock library.
# datetime() localtime has to call localtime_r. The libc fallback shares
# one buffer with every other thread in the process. Stock linked localtime_r.
unpack libsqlite3
cd "$WORK/libsqlite3-$(ver libsqlite3)"
if [ ! -f libsqlite3.so.0 ]; then
  # The libc stub exports soft-div that the router libc does not. --no-as-needed
  # records libgcc anyway, or 64-bit division is missing on the device.
  mipsel-musl-so-cc -shared -fPIC -Os \
    -Wl,-soname,libsqlite3.so.0 \
    -DSQLITE_ENABLE_FTS3 \
    -DSQLITE_ENABLE_FTS4 \
    -DSQLITE_ENABLE_FTS5 \
    -DSQLITE_ENABLE_GEOPOLY \
    -DSQLITE_ENABLE_RTREE \
    -DSQLITE_ENABLE_UNLOCK_NOTIFY \
    -DSQLITE_ENABLE_JSON1 \
    -DHAVE_LOCALTIME_R=1 \
    sqlite3.c -o libsqlite3.so.0 \
    -Wl,--no-as-needed "$SYSROOT_SO/lib/libgcc_s.so.1" || exit 1
fi
