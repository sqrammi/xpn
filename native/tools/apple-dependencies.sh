#!/bin/sh
# Local or CI: build pinned, platform-specific static dependency SDKs.
set -eu
[ "$(uname -s)" = Darwin ] || { echo 'Apple SDK builds require macOS and full Xcode.' >&2; exit 1; }
XPN_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
XPN_DEPENDENCY_WORK=${XPN_DEPENDENCY_WORK:-$XPN_ROOT/build/apple-deps}
XPN_BASELINE=817892b0ecbc6af994dd6df999c73faf795adbf2
case "${XPN_APPLE_TARGETS:-all}" in
    all) XPN_TRIPLETS='arm64-ios arm64-ios-simulator arm64-osx x64-osx';;
    macos) XPN_TRIPLETS='arm64-osx x64-osx';;
    ios) XPN_TRIPLETS='arm64-ios arm64-ios-simulator';;
    *) echo 'XPN_APPLE_TARGETS must be all, macos or ios.' >&2; exit 1;;
esac
xcrun --sdk macosx --show-sdk-path >/dev/null
if [ "${XPN_APPLE_TARGETS:-all}" != macos ]; then
    xcrun --sdk iphoneos --show-sdk-path >/dev/null
    xcrun --sdk iphonesimulator --show-sdk-path >/dev/null
fi
for XPN_TOOL in git cmake ninja pkg-config; do command -v "$XPN_TOOL" >/dev/null; done
mkdir -p "$XPN_DEPENDENCY_WORK"
XPN_DEPENDENCY_WORK=$(CDPATH= cd -- "$XPN_DEPENDENCY_WORK" && pwd)
if [ ! -e "$XPN_DEPENDENCY_WORK/vcpkg" ]; then
    git clone --filter=blob:none https://github.com/microsoft/vcpkg.git "$XPN_DEPENDENCY_WORK/vcpkg"
    git -C "$XPN_DEPENDENCY_WORK/vcpkg" checkout --detach "$XPN_BASELINE"
fi
[ "$(git -C "$XPN_DEPENDENCY_WORK/vcpkg" rev-parse HEAD)" = "$XPN_BASELINE" ] || {
    echo 'Existing vcpkg checkout has a different revision; choose a new XPN_DEPENDENCY_WORK directory.' >&2; exit 1;
}
if [ ! -x "$XPN_DEPENDENCY_WORK/vcpkg/vcpkg" ]; then
    "$XPN_DEPENDENCY_WORK/vcpkg/bootstrap-vcpkg.sh" -disableMetrics
fi
export VCPKG_DISABLE_METRICS=1
mkdir -p "$XPN_DEPENDENCY_WORK/sdk" "$XPN_ROOT/clients/apple/Resources/ThirdParty"
for XPN_TRIPLET in $XPN_TRIPLETS; do
    # Manifest installs prune packages for other targets. Keep each architecture
    # in its own install tree so a later slice cannot remove an earlier SDK.
    XPN_INSTALL_ROOT=$XPN_DEPENDENCY_WORK/installs/$XPN_TRIPLET
    "$XPN_DEPENDENCY_WORK/vcpkg/vcpkg" install \
        --triplet "$XPN_TRIPLET" \
        --overlay-triplets="$XPN_ROOT/native/deps/triplets" \
        --x-manifest-root="$XPN_ROOT/native/deps" \
        --x-install-root="$XPN_INSTALL_ROOT"
    case "$XPN_TRIPLET" in
        arm64-ios) XPN_SLICE=ios-arm64;;
        arm64-ios-simulator) XPN_SLICE=simulator-arm64;;
        arm64-osx) XPN_SLICE=macos-arm64;;
        x64-osx) XPN_SLICE=macos-x86_64;;
    esac
    if [ -L "$XPN_DEPENDENCY_WORK/sdk/$XPN_SLICE" ] || [ ! -e "$XPN_DEPENDENCY_WORK/sdk/$XPN_SLICE" ]; then
        ln -sfn "$XPN_INSTALL_ROOT/$XPN_TRIPLET" "$XPN_DEPENDENCY_WORK/sdk/$XPN_SLICE"
    fi
    for XPN_LICENSE in "$XPN_INSTALL_ROOT/$XPN_TRIPLET/share/"*/copyright; do
        test -f "$XPN_LICENSE" || continue
        XPN_NAME=$(basename "$(dirname "$XPN_LICENSE")")
        cp "$XPN_LICENSE" "$XPN_ROOT/clients/apple/Resources/ThirdParty/$XPN_NAME.txt"
    done
done
echo "Native SDKs: $XPN_DEPENDENCY_WORK/sdk"
