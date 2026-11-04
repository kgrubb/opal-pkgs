unpack i2c-tools
cd "$WORK/i2c-tools-$(ver i2c-tools)"
# CFLAGS comes from the environment so the makefile's CFLAGS += still applies.
if [ ! -x tools/i2cget ]; then
  CC=$CC CFLAGS="-Os -I$ROOT/kheaders" make -j"$JOBS" \
    AR=mipsel-linux-musl-ar USE_STATIC_LIB=1 BUILD_DYNAMIC_LIB=0
fi
