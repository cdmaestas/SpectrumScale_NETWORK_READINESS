#!/usr/bin/env bash
# Build RPM and/or DEB packages for koet.
#
# Usage:
#   ./build-pkg.sh          — build both RPM and DEB (skips whichever tools are missing)
#   ./build-pkg.sh --rpm    — RPM only
#   ./build-pkg.sh --deb    — DEB only
#
# Prerequisites:
#   RPM: rpmbuild  (sudo dnf install rpm-build  OR  sudo apt install rpm)
#   DEB: dpkg-deb  (sudo apt install dpkg-dev   OR  brew install dpkg)
#
# Output: dist/koet-1.18.2-1.noarch.rpm
#         dist/koet_1.18.2-1_all.deb

set -euo pipefail

PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$PKG_DIR")"
DIST="$ROOT/dist"
VERSION="1.18.2"
RELEASE="1"

BUILD_RPM=true
BUILD_DEB=true
for arg in "$@"; do
    case "$arg" in
        --rpm) BUILD_DEB=false ;;
        --deb) BUILD_RPM=false ;;
    esac
done

mkdir -p "$DIST"

# ── Shared: assemble staging area ────────────────────────────────────────────
STAGE="$PKG_DIR/.stage"
rm -rf "$STAGE"
mkdir -p "$STAGE"

cp "$ROOT/koet.py"              "$STAGE/koet.py"
cp "$ROOT/koet-server.py"       "$STAGE/koet-server.py"
cp "$ROOT/koet-ui.html"         "$STAGE/koet-ui.html"
cp "$ROOT/supported_OS.json"    "$STAGE/supported_OS.json"
cp "$ROOT/packages.json"        "$STAGE/packages.json"
cp "$ROOT/packages_rdma.json" "$STAGE/packages_rdma.json"
cp "$ROOT/packages_rdma_rh8.json" "$STAGE/packages_rdma_rh8.json"
cp "$PKG_DIR/koet-wrapper"      "$STAGE/koet-wrapper"
cp "$PKG_DIR/koet.service"      "$STAGE/koet.service"
gzip -9 -c "$PKG_DIR/man/man1/koet-ui.1" > "$STAGE/koet-ui.1.gz"
gzip -9 -c "$PKG_DIR/man/man8/koet.8"   > "$STAGE/koet.8.gz"

# ── RPM ───────────────────────────────────────────────────────────────────────
build_rpm() {
    echo "==> Building RPM..."
    if ! command -v rpmbuild &>/dev/null; then
        echo "    SKIP: rpmbuild not found (sudo dnf install rpm-build)"
        return
    fi

    local rpmbuild_root="$PKG_DIR/.rpmbuild"
    mkdir -p "$rpmbuild_root"/{SPECS,SOURCES,BUILD,RPMS,SRPMS}

    cp "$STAGE"/* "$rpmbuild_root/SOURCES/"
    cp "$PKG_DIR/koet.spec" "$rpmbuild_root/SPECS/"

    rpmbuild \
        --define "_topdir $rpmbuild_root" \
        --define "_version $VERSION" \
        --define "_release $RELEASE" \
        -bb "$rpmbuild_root/SPECS/koet.spec"

    find "$rpmbuild_root/RPMS" -name "*.rpm" -exec cp {} "$DIST/" \;
    echo "    RPM: $(ls "$DIST/"*.rpm 2>/dev/null | tail -1)"
    rm -rf "$rpmbuild_root"
}

# ── DEB ───────────────────────────────────────────────────────────────────────
build_deb() {
    echo "==> Building DEB..."
    if ! command -v dpkg-deb &>/dev/null; then
        echo "    SKIP: dpkg-deb not found (sudo apt install dpkg-dev)"
        return
    fi

    local deb_root="$PKG_DIR/.deb"
    local deb_name="koet_${VERSION}-${RELEASE}_all"
    rm -rf "$deb_root"
    mkdir -p "$deb_root/$deb_name/DEBIAN"
    mkdir -p "$deb_root/$deb_name/usr/lib/koet"
    mkdir -p "$deb_root/$deb_name/usr/bin"
    mkdir -p "$deb_root/$deb_name/usr/lib/systemd/system"
    mkdir -p "$deb_root/$deb_name/usr/share/man/man1"
    mkdir -p "$deb_root/$deb_name/usr/share/man/man8"

    cp "$STAGE/koet.py"               "$deb_root/$deb_name/usr/lib/koet/"
    cp "$STAGE/koet-server.py"        "$deb_root/$deb_name/usr/lib/koet/"
    cp "$STAGE/koet-ui.html"          "$deb_root/$deb_name/usr/lib/koet/"
    cp "$STAGE/supported_OS.json"     "$deb_root/$deb_name/usr/lib/koet/"
    cp "$STAGE/packages.json"         "$deb_root/$deb_name/usr/lib/koet/"
    cp "$STAGE/packages_rdma.json" "$deb_root/$deb_name/usr/lib/koet/"
    cp "$STAGE/packages_rdma_rh8.json" "$deb_root/$deb_name/usr/lib/koet/"
    cp "$STAGE/koet-wrapper"          "$deb_root/$deb_name/usr/bin/koet-ui"
    cp "$STAGE/koet.service"          "$deb_root/$deb_name/usr/lib/systemd/system/"
    cp "$STAGE/koet-ui.1.gz"         "$deb_root/$deb_name/usr/share/man/man1/"
    cp "$STAGE/koet.8.gz"            "$deb_root/$deb_name/usr/share/man/man8/"

    chmod 0755 "$deb_root/$deb_name/usr/bin/koet-ui"
    chmod 0755 "$deb_root/$deb_name/usr/lib/koet/koet.py"
    chmod 0755 "$deb_root/$deb_name/usr/lib/koet/koet-server.py"
    chmod 0644 "$deb_root/$deb_name/usr/lib/koet/koet-ui.html"
    chmod 0644 "$deb_root/$deb_name/usr/lib/koet/supported_OS.json"
    chmod 0644 "$deb_root/$deb_name/usr/lib/koet/packages.json"
    chmod 0644 "$deb_root/$deb_name/usr/lib/koet/packages_rdma.json"
    chmod 0644 "$deb_root/$deb_name/usr/lib/koet/packages_rdma_rh8.json"
    chmod 0644 "$deb_root/$deb_name/usr/lib/systemd/system/koet.service"
    chmod 0644 "$deb_root/$deb_name/usr/share/man/man1/koet-ui.1.gz"
    chmod 0644 "$deb_root/$deb_name/usr/share/man/man8/koet.8.gz"

    cp "$PKG_DIR/debian/control"   "$deb_root/$deb_name/DEBIAN/"
    cp "$PKG_DIR/debian/changelog" "$deb_root/$deb_name/DEBIAN/"
    cp "$PKG_DIR/debian/postinst"  "$deb_root/$deb_name/DEBIAN/"
    cp "$PKG_DIR/debian/prerm"     "$deb_root/$deb_name/DEBIAN/"
    cp "$PKG_DIR/debian/postrm"    "$deb_root/$deb_name/DEBIAN/"
    chmod 0755 "$deb_root/$deb_name/DEBIAN/postinst" \
               "$deb_root/$deb_name/DEBIAN/prerm" \
               "$deb_root/$deb_name/DEBIAN/postrm"

    local installed_size
    installed_size=$(du -sk "$deb_root/$deb_name" | cut -f1)
    sed -i.bak "s/^Version:.*/Version: ${VERSION}-${RELEASE}/" "$deb_root/$deb_name/DEBIAN/control"
    echo "Installed-Size: $installed_size" >> "$deb_root/$deb_name/DEBIAN/control"

    dpkg-deb --build --root-owner-group "$deb_root/$deb_name" "$DIST/${deb_name}.deb"
    echo "    DEB: $DIST/${deb_name}.deb"
    rm -rf "$deb_root"
}

# ── Run ───────────────────────────────────────────────────────────────────────
[[ "$BUILD_RPM" == "true" ]] && build_rpm
[[ "$BUILD_DEB" == "true" ]] && build_deb

rm -rf "$STAGE"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Output:"
ls -1 "$DIST/" 2>/dev/null | sed 's/^/    /'
echo ""
echo "  Install on RHEL/Rocky:"
echo "    sudo dnf install dist/koet-${VERSION}-${RELEASE}.noarch.rpm"
echo ""
echo "  Install on Debian/Ubuntu:"
echo "    sudo apt install ./dist/koet_${VERSION}-${RELEASE}_all.deb"
echo ""
echo "  Start:   koet-ui"
echo "  Service: sudo systemctl enable --now koet"
echo "  Tunnel:  ssh -L 5002:127.0.0.1:5002 root@cluster-node"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
