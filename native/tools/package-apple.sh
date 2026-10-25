#!/bin/sh
# CI-only packaging. Supply vetted, platform-specific static dependency SDKs.
# This script is intentionally not executed locally by the agent.
set -eu
[ "${CI:-}" = true ] || { echo 'Run this C build only on a remote CI Mac (CI=true).' >&2; exit 1; }
: "${XPN_APPLE_SDKS:?Set XPN_APPLE_SDKS to the directory described in clients/apple/README.md}"
XPN_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
XPN_BUILD=$(mktemp -d)
trap 'rm -rf "$XPN_BUILD"' EXIT INT TERM
for XPN_SLICE in ios-arm64 simulator-arm64 macos-arm64 macos-x86_64; do
    case "$XPN_SLICE" in
        ios-arm64) XPN_SDK=iphoneos; XPN_ARCH=arm64; XPN_TARGET=arm64-apple-ios17.0;;
        simulator-arm64) XPN_SDK=iphonesimulator; XPN_ARCH=arm64; XPN_TARGET=arm64-apple-ios17.0-simulator;;
        macos-arm64) XPN_SDK=macosx; XPN_ARCH=arm64; XPN_TARGET=arm64-apple-macos14.0;;
        macos-x86_64) XPN_SDK=macosx; XPN_ARCH=x86_64; XPN_TARGET=x86_64-apple-macos14.0;;
    esac
    XPN_PREFIX=$XPN_APPLE_SDKS/$XPN_SLICE
    for XPN_LIB in ssl crypto websockets curl jansson; do test -f "$XPN_PREFIX/lib/lib$XPN_LIB.a"; done
    mkdir -p "$XPN_BUILD/$XPN_SLICE"
    for XPN_SOURCE in core transport profile; do
        xcrun --sdk "$XPN_SDK" clang -target "$XPN_TARGET" -arch "$XPN_ARCH" \
            -isysroot "$(xcrun --sdk "$XPN_SDK" --show-sdk-path)" \
            -std=c11 -O3 -fvisibility=hidden -D_POSIX_C_SOURCE=200809L -D_DARWIN_C_SOURCE \
            -I"$XPN_PREFIX/include" -I"$XPN_ROOT/native/include" -I"$XPN_ROOT/native/src" \
            -c "$XPN_ROOT/native/src/$XPN_SOURCE.c" -o "$XPN_BUILD/$XPN_SLICE/$XPN_SOURCE.o"
    done
    xcrun libtool -static -o "$XPN_BUILD/$XPN_SLICE/libXPNNative.a" \
        "$XPN_BUILD/$XPN_SLICE/"*.o "$XPN_PREFIX/lib/"*.a
done
xcrun lipo -create "$XPN_BUILD/macos-arm64/libXPNNative.a" "$XPN_BUILD/macos-x86_64/libXPNNative.a" -output "$XPN_BUILD/libXPNNative-macos.a"
mkdir -p "$XPN_ROOT/clients/apple/Frameworks"
test ! -e "$XPN_ROOT/clients/apple/Frameworks/XPNNative.xcframework"
xcodebuild -create-xcframework \
    -library "$XPN_BUILD/ios-arm64/libXPNNative.a" -headers "$XPN_ROOT/native/include" \
    -library "$XPN_BUILD/simulator-arm64/libXPNNative.a" -headers "$XPN_ROOT/native/include" \
    -library "$XPN_BUILD/libXPNNative-macos.a" -headers "$XPN_ROOT/native/include" \
    -output "$XPN_ROOT/clients/apple/Frameworks/XPNNative.xcframework"
