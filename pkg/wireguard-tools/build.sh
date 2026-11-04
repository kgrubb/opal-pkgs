# The kernel module stays stock. PLATFORM=linux because the build host is not the router.
unpack wireguard-tools
cd "$WORK/wireguard-tools-$(ver wireguard-tools)/src"
if [ ! -x wg ]; then
  # -idirafter so this release's wireguard.h is used, and the toolchain fills in the other kernel headers.
  PLATFORM=linux CC=$CC CFLAGS="-Os -Iuapi/linux -idirafter ${ZIG%/*}/lib/libc/include/any-linux-any" \
    make -j"$JOBS" wg
fi
