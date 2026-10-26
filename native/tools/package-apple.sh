#!/bin/sh
# Local or CI packaging. Supply platform-specific static dependency SDKs.
set -eu
[ "$(uname -s)" = Darwin ] || { echo 'Apple packaging requires macOS and full Xcode.' >&2; exit 1; }
XPN_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
XPN_APPLE_SDKS=${XPN_APPLE_SDKS:-$XPN_ROOT/build/apple-deps/sdk}
XPN_OUTPUT=$XPN_ROOT/clients/apple/Frameworks/XPNNative.xcframework
if [ -e "$XPN_OUTPUT" ] && [ "${XPN_REPLACE_FRAMEWORK:-0}" != 1 ]; then
    echo 'Framework exists. Set XPN_REPLACE_FRAMEWORK=1 to replace it after a successful build (old copy is retained).' >&2; exit 1;
fi
case "${XPN_APPLE_TARGETS:-all}" in
    all) XPN_SLICES='ios-arm64 simulator-arm64 macos-arm64 macos-x86_64';;
    macos) XPN_SLICES='macos-arm64 macos-x86_64';;
    ios) XPN_SLICES='ios-arm64 simulator-arm64';;
    *) echo 'XPN_APPLE_TARGETS must be all, macos or ios.' >&2; exit 1;;
esac
XPN_BUILD=$(mktemp -d)
trap 'rm -rf "$XPN_BUILD"' EXIT INT TERM
for XPN_SLICE in $XPN_SLICES; do
    case "$XPN_SLICE" in
        ios-arm64) XPN_SDK=iphoneos; XPN_ARCH=arm64; XPN_TARGET=arm64-apple-ios17.0;;
        simulator-arm64) XPN_SDK=iphonesimulator; XPN_ARCH=arm64; XPN_TARGET=arm64-apple-ios17.0-simulator;;
        macos-arm64) XPN_SDK=macosx; XPN_ARCH=arm64; XPN_TARGET=arm64-apple-macos14.0;;
        macos-x86_64) XPN_SDK=macosx; XPN_ARCH=x86_64; XPN_TARGET=x86_64-apple-macos14.0;;
    esac
    XPN_PREFIX=$XPN_APPLE_SDKS/$XPN_SLICE
    for XPN_LIB in ssl crypto websockets curl jansson; do
        test -f "$XPN_PREFIX/lib/lib$XPN_LIB.a" || {
            echo "Missing $XPN_PREFIX/lib/lib$XPN_LIB.a; run apple-dependencies.sh for these targets first." >&2; exit 1;
        }
    done
    mkdir -p "$XPN_BUILD/$XPN_SLICE"
    for XPN_SOURCE in core transport standby profile certificate; do
        xcrun --sdk "$XPN_SDK" clang -target "$XPN_TARGET" -arch "$XPN_ARCH" \
            -isysroot "$(xcrun --sdk "$XPN_SDK" --show-sdk-path)" \
            -std=c11 -O3 -fvisibility=hidden -D_POSIX_C_SOURCE=200809L -D_DARWIN_C_SOURCE \
            -I"$XPN_PREFIX/include" -I"$XPN_ROOT/native/include" -I"$XPN_ROOT/native/src" \
            -c "$XPN_ROOT/native/src/$XPN_SOURCE.c" -o "$XPN_BUILD/$XPN_SLICE/$XPN_SOURCE.o"
    done
    xcrun libtool -static -o "$XPN_BUILD/$XPN_SLICE/libXPNNative.a" \
        "$XPN_BUILD/$XPN_SLICE/"*.o "$XPN_PREFIX/lib/"*.a
done
set -- -create-xcframework
if [ -d "$XPN_BUILD/ios-arm64" ]; then
    set -- "$@" -library "$XPN_BUILD/ios-arm64/libXPNNative.a" -headers "$XPN_ROOT/native/include" \
        -library "$XPN_BUILD/simulator-arm64/libXPNNative.a" -headers "$XPN_ROOT/native/include"
fi
if [ -d "$XPN_BUILD/macos-arm64" ]; then
    xcrun lipo -create "$XPN_BUILD/macos-arm64/libXPNNative.a" "$XPN_BUILD/macos-x86_64/libXPNNative.a" -output "$XPN_BUILD/libXPNNative-macos.a"
    set -- "$@" -library "$XPN_BUILD/libXPNNative-macos.a" -headers "$XPN_ROOT/native/include"
fi
xcodebuild "$@" -output "$XPN_BUILD/XPNNative.xcframework"
mkdir -p "$XPN_ROOT/clients/apple/Frameworks"
if [ -e "$XPN_OUTPUT" ]; then
    XPN_BACKUP=$XPN_ROOT/clients/apple/Frameworks/XPNNative.previous-$(date +%Y%m%d%H%M%S)-$$.xcframework
    mv "$XPN_OUTPUT" "$XPN_BACKUP"
    echo "Previous framework saved at $XPN_BACKUP"
fi
mv "$XPN_BUILD/XPNNative.xcframework" "$XPN_OUTPUT"
echo "Built $XPN_OUTPUT (${XPN_APPLE_TARGETS:-all})"
