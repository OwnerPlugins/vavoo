#!/bin/bash

version='1.87'
changelog="- Fixed a Python 3 bytes/str comparison bug that silently broke the
  proxy-null-response fallback when browsing channels
- Fixed a stream-resolution cache race condition in the local proxy
  under concurrent requests
- Fixed bouquet, favorites, and EPG cache files being left corrupted
  if the box lost power mid-write
- Fixed the plugin blocking for up to 5 seconds on a slow/unreachable
  network every time it loads
- Fixed the installer misdetecting Python 2 vs 3 on images without an
  unversioned 'python' binary
- Made 'Auto-update EPG' actually enable the EPGImport source instead
  of doing nothing
- Removed dead proxy-launch scripts and synced install dependencies
  across all three packaging paths"


echo "$changelog"
TMPPATH=/tmp/vavoo-install
FILEPATH=/tmp/vavoo-main.tar.gz

if [ ! -d /usr/lib64 ]; then
    PLUGINPATH=/usr/lib/enigma2/python/Plugins/Extensions/vavoo
else
    PLUGINPATH=/usr/lib64/enigma2/python/Plugins/Extensions/vavoo
fi

echo "Starting vavoo installation..."

cleanup() {
    echo "Cleaning up temporary files..."
    [ -d "$TMPPATH" ] && rm -rf "$TMPPATH"
    [ -f "$FILEPATH" ] && rm -f "$FILEPATH"
}

detect_os() {
    if [ -f /var/lib/dpkg/status ]; then
        OSTYPE="DreamOs"
        STATUS="/var/lib/dpkg/status"
    elif [ -f /etc/opkg/opkg.conf ] || [ -f /var/lib/opkg/status ]; then
        OSTYPE="OE"
        STATUS="/var/lib/opkg/status"
    elif [ -f /etc/debian_version ]; then
        OSTYPE="Debian"
        STATUS="/var/lib/dpkg/status"
    else
        OSTYPE="Unknown"
        STATUS=""
    fi
    echo "Detected OS type: $OSTYPE"
}

detect_os

if ! command -v wget >/dev/null 2>&1; then
    echo "Installing wget..."
    case "$OSTYPE" in
        "DreamOs"|"Debian")
            apt-get update && apt-get install -y wget || { echo "Failed to install wget"; exit 1; }
            ;;
        "OE")
            opkg update && opkg install wget || { echo "Failed to install wget"; exit 1; }
            ;;
        *)
            echo "Unsupported OS type. Cannot install wget."
            exit 1
            ;;
    esac
fi

# Best-effort curl install - NOT fatal if it fails, unlike wget above.
# Some images (e.g. OpenPLi) ship a BusyBox wget applet whose HTTPS/TLS
# support is too limited for GitHub's current requirements ("wget:
# error getting response: Connection reset by peer" mid-handshake,
# despite DNS/TCP succeeding) even though the exact same URL downloads
# fine via curl on the same box. wget stays the fallback either way.
if ! command -v curl >/dev/null 2>&1; then
    echo "Installing curl (best-effort, for a more reliable HTTPS download)..."
    case "$OSTYPE" in
        "DreamOs"|"Debian")
            apt-get update && apt-get install -y curl
            ;;
        "OE")
            opkg update && opkg install curl
            ;;
    esac
fi

if command -v python3 >/dev/null 2>&1; then
    echo "Python3 image detected"
    PYTHON="PY3"
    Packagesix="python3-six"
    Packagerequests="python3-requests"
elif command -v python >/dev/null 2>&1 && python --version 2>&1 | grep -q '^Python 3\.'; then
    echo "Python3 image detected (via 'python')"
    PYTHON="PY3"
    Packagesix="python3-six"
    Packagerequests="python3-requests"
elif command -v python >/dev/null 2>&1; then
    echo "Python2 image detected"
    PYTHON="PY2"
    Packagesix="python-six"
    Packagerequests="python-requests"
else
    echo "No Python interpreter found (neither python3 nor python). Cannot continue."
    exit 1
fi

install_pkg() {
    local pkg=$1
    if [ -z "$STATUS" ] || ! grep -qs "Package: $pkg" "$STATUS" 2>/dev/null; then
        echo "Installing $pkg..."
        case "$OSTYPE" in
            "DreamOs"|"Debian")
                apt-get update && apt-get install -y "$pkg" || { echo "Could not install $pkg, continuing anyway..."; }
                ;;
            "OE")
                opkg update && opkg install "$pkg" || { echo "Could not install $pkg, continuing anyway..."; }
                ;;
            *)
                echo "Cannot install $pkg on unknown OS type, continuing..."
                ;;
        esac
    else
        echo "$pkg already installed"
    fi
}

if [ -x /usr/bin/python3 ]; then
    install_pkg "python3-difflib"
else
    install_pkg "python-difflib"
fi


install_pkg "$Packagesix"
install_pkg "$Packagerequests"

if [ "$OSTYPE" = "OE" ]; then
    echo "Installing additional dependencies for OpenEmbedded..."
    for pkg in ffmpeg gstplayer exteplayer3 enigma2-plugin-systemplugins-serviceapp; do
        install_pkg "$pkg"
    done
fi

cleanup
mkdir -p "$TMPPATH"

echo "Downloading vavoo..."
DOWNLOAD_URL='https://github.com/Belfagor2005/vavoo/archive/refs/heads/main.tar.gz'
DOWNLOAD_OK=1
if command -v curl >/dev/null 2>&1; then
    curl -fL --insecure -o "$FILEPATH" "$DOWNLOAD_URL"
    DOWNLOAD_OK=$?
fi
if [ "$DOWNLOAD_OK" -ne 0 ]; then
    echo "Falling back to wget for the download..."
    wget --no-check-certificate "$DOWNLOAD_URL" -O "$FILEPATH"
    DOWNLOAD_OK=$?
fi
if [ "$DOWNLOAD_OK" -ne 0 ]; then
    echo "Failed to download vavoo package!"
    cleanup
    exit 1
fi

echo "Extracting package..."
tar -xzf "$FILEPATH" -C "$TMPPATH"
if [ $? -ne 0 ]; then
    echo "Failed to extract vavoo package!"
    cleanup
    exit 1
fi

echo "Installing plugin files..."
mkdir -p "$PLUGINPATH"

if [ -d "$TMPPATH/vavoo-main/usr/lib/enigma2/python/Plugins/Extensions/vavoo" ]; then
    cp -r "$TMPPATH/vavoo-main/usr/lib/enigma2/python/Plugins/Extensions/vavoo"/* "$PLUGINPATH/" 2>/dev/null
    echo "Copied from standard plugin directory"
elif [ -d "$TMPPATH/vavoo-main/usr/lib64/enigma2/python/Plugins/Extensions/vavoo" ]; then
    cp -r "$TMPPATH/vavoo-main/usr/lib64/enigma2/python/Plugins/Extensions/vavoo"/* "$PLUGINPATH/" 2>/dev/null
    echo "Copied from lib64 plugin directory"
elif [ -d "$TMPPATH/vavoo-main/usr" ]; then
    cp -r "$TMPPATH/vavoo-main/usr"/* /usr/ 2>/dev/null
    echo "Copied entire usr structure"
else
    echo "Could not find plugin files in extracted archive"
    echo "Available directories:"
    find "$TMPPATH" -type d -name "*vavoo*" | head -10
    cleanup
    exit 1
fi

sync

echo "Verifying installation..."
if [ -d "$PLUGINPATH" ] && [ -n "$(ls -A "$PLUGINPATH" 2>/dev/null)" ]; then
    echo "Plugin directory found and not empty: $PLUGINPATH"
    echo "Contents:"
    ls -la "$PLUGINPATH/" | head -10
else
    echo "Plugin installation failed or directory is empty!"
    cleanup
    exit 1
fi

cleanup
sync

FILE="/etc/image-version"
box_type=$(sed -n '1p' /etc/hostname 2>/dev/null || echo "Unknown")
# distro_value=$(grep '^distro=' "$FILE" 2>/dev/null | awk -F '=' '{print $2}')
# distro_version=$(grep '^version=' "$FILE" 2>/dev/null | awk -F '=' '{print $2}')
distro_value="Unknown"
distro_version="Unknown"
if [ -r /etc/os-release ]; then
    distro_value=$(grep '^NAME=' /etc/os-release 2>/dev/null | cut -d'"' -f2)
    distro_version=$(grep '^VERSION_ID=' /etc/os-release 2>/dev/null | cut -d'"' -f2)
elif [ -r /etc/issue ]; then
    distro_value=$(head -n 1 /etc/issue 2>/dev/null | awk '{print $1}')
    distro_version=$(head -n 1 /etc/issue 2>/dev/null | awk '{print $2}')
elif [ -r /etc/vtiversion.info ]; then
    distro_value=$(head -n 1 /etc/vtiversion.info 2>/dev/null)
    # versione non disponibile, lascia Unknown
elif [ -r /etc/issue.net ]; then
    distro_value=$(head -n 1 /etc/issue.net 2>/dev/null | awk '{print $1}')
    distro_version=$(head -n 1 /etc/issue.net 2>/dev/null | awk '{print $2}')
fi

[ -z "$distro_value" ] && distro_value="Unknown"
[ -z "$distro_version" ] && distro_version="Unknown"
if command -v python3 >/dev/null 2>&1; then
    python_vers=$(python3 --version 2>&1)
elif command -v python >/dev/null 2>&1; then
    python_vers=$(python --version 2>&1)
else
    python_vers="not found"
fi

cat <<EOF

#########################################################
#               INSTALLED SUCCESSFULLY                  #
#                developed by LULULLA                   #
#               https://corvoboys.org                   #
#########################################################
#         Enigma2 GUI will RESTART now (box stays on)   #
#########################################################
^^^^^^^^^^Debug information:
BOX MODEL: $box_type
OS SYSTEM: $OSTYPE
PYTHON: $python_vers
IMAGE NAME: ${distro_value:-Unknown}
IMAGE VERSION: ${distro_version:-Unknown}
PLUGIN VERSION: $version
EOF

exit 0
