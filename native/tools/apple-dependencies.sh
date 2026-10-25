#!/bin/sh
# Remote CI only: build reproducible platform dependency SDKs from vcpkg sources.
set -eu
[ "${CI:-}" = true ] || { echo 'Run native C dependency builds on remote CI only.' >&2; exit 1; }
: "${XPN_DEPENDENCY_WORK:?Set an empty CI build directory}"
XPN_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
XPN_BASELINE=817892b0ecbc6af994dd6df999c73faf795adbf2
mkdir -p "$XPN_DEPENDENCY_WORK"
git clone --filter=blob:none https://github.com/microsoft/vcpkg.git "$XPN_DEPENDENCY_WORK/vcpkg"
git -C "$XPN_DEPENDENCY_WORK/vcpkg" checkout --detach "$XPN_BASELINE"
"$XPN_DEPENDENCY_WORK/vcpkg/bootstrap-vcpkg.sh" -disableMetrics
export VCPKG_DISABLE_METRICS=1
mkdir -p "$XPN_DEPENDENCY_WORK/sdk" "$XPN_ROOT/clients/apple/Resources/ThirdParty"
for XPN_TRIPLET in arm64-ios arm64-ios-simulator arm64-osx x64-osx; do
    "$XPN_DEPENDENCY_WORK/vcpkg/vcpkg" install \
        --triplet "$XPN_TRIPLET" \
        --overlay-triplets="$XPN_ROOT/native/deps/triplets" \
        --x-manifest-root="$XPN_ROOT/native/deps" \
        --x-install-root="$XPN_DEPENDENCY_WORK/installed"
    case "$XPN_TRIPLET" in
        arm64-ios) XPN_SLICE=ios-arm64;;
        arm64-ios-simulator) XPN_SLICE=simulator-arm64;;
        arm64-osx) XPN_SLICE=macos-arm64;;
        x64-osx) XPN_SLICE=macos-x86_64;;
    esac
    ln -s "$XPN_DEPENDENCY_WORK/installed/$XPN_TRIPLET" "$XPN_DEPENDENCY_WORK/sdk/$XPN_SLICE"
    for XPN_LICENSE in "$XPN_DEPENDENCY_WORK/installed/$XPN_TRIPLET/share/"*/copyright; do
        test -f "$XPN_LICENSE" || continue
        XPN_NAME=$(basename "$(dirname "$XPN_LICENSE")")
        cp "$XPN_LICENSE" "$XPN_ROOT/clients/apple/Resources/ThirdParty/$XPN_NAME.txt"
    done
done
echo "Native SDKs: $XPN_DEPENDENCY_WORK/sdk"
