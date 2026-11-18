#!/bin/bash
# =====================================================================
#  vavoo installer - con log su file
#  Log: /tmp/vavoo_install.log  (copia anche in /home/root/ a fine run)
# =====================================================================

version='1.89'
changelog="- Streams no longer stop every few minutes: a channel now keeps one
  stream address for the whole viewing, and a failed stream is
  retried and then moved to another source automatically
- New default channel source (Geil, needs no token) with Vavoo/Kool
  as fallback - choose it in Config
- A channel available from several sources is shown once; press
  YELLOW in the player to choose the source by name
- Channel logos (picons) in the channel list and on the player overlay
- New: Favourites (INFO key), parental control PIN, log viewer in
  Config, live /playlist.m3u for other players
- Fixed LEFT/RIGHT muting the sound during playback
- Fixed a freeze when opening the plugin right after boot, and empty
  channel lists after a slow start
- Fixed a proxy restart that could crash the whole box
- Simpler settings: removed Proxy Enabled, Auto-update EPG and EPG
  Similarity Threshold
- Many EPG and bouquet fixes (scheduled update timing, western
  satellites, reload after export, notification bar on HD screens)"

LOGFILE=/tmp/vavoo_install.log
RCFILE=/tmp/vavoo_install.rc
LOGCOPY_DIR=/home/root

TMPPATH=/tmp/vavoo-install
FILEPATH=/tmp/vavoo-main.tar.gz

# ---------------------------------------------------------------------
# helper di log
# ---------------------------------------------------------------------
ts() { date '+%Y-%m-%d %H:%M:%S' 2>/dev/null; }
log() { echo "[$(ts)] $*"; }
section() { echo ""; echo "[$(ts)] ===== $* ====="; }

# esegue un comando, lo scrive nel log e ne riporta l'exit code
run() {
    log "\$ $*"
    "$@"
    local rc=$?
    [ $rc -ne 0 ] && log "!! comando fallito (exit $rc): $*"
    return $rc
}

fail() {
    log "ERRORE: $*"
    cleanup
    exit 1
}

cleanup() {
    log "Cleaning up temporary files..."
    [ -d "$TMPPATH" ] && rm -rf "$TMPPATH"
    [ -f "$FILEPATH" ] && rm -f "$FILEPATH"
}

# ---------------------------------------------------------------------
# diagnostica del sistema (prima di installare)
# ---------------------------------------------------------------------
diagnostics() {
    section "DIAGNOSTICA SISTEMA"
    log "Installer version: $version"
    log "Shell: $0  (BASH_VERSION=${BASH_VERSION:-n/a})"
    log "User: $(id 2>/dev/null)"
    log "uname: $(uname -a 2>/dev/null)"
    log "hostname: $(cat /etc/hostname 2>/dev/null)"
    for f in /etc/image-version /etc/os-release /etc/issue /etc/vtiversion.info; do
        if [ -r "$f" ]; then
            echo "--- $f ---"
            head -n 20 "$f" 2>/dev/null
        fi
    done

    echo "--- tool disponibili ---"
    for t in python3 python opkg apt-get dpkg wget curl tar gzip tee; do
        p=$(command -v $t 2>/dev/null)
        echo "  $t: ${p:-NON TROVATO}"
    done
    command -v python3 >/dev/null 2>&1 && echo "  python3 --version: $(python3 --version 2>&1)"
    command -v python  >/dev/null 2>&1 && echo "  python --version:  $(python --version 2>&1)"
    [ -d /usr/lib64 ] && echo "  /usr/lib64 presente" || echo "  /usr/lib64 assente"

    echo "--- spazio disco (causa frequente di installazioni fallite) ---"
    df -h / /tmp /usr 2>/dev/null || df / /tmp /usr 2>/dev/null
    echo "--- memoria ---"
    free 2>/dev/null || cat /proc/meminfo 2>/dev/null | head -n 5

    echo "--- rete ---"
    if command -v nslookup >/dev/null 2>&1; then
        nslookup github.com 2>&1 | tail -n 4
    fi
    ping -c 1 -W 3 github.com >/dev/null 2>&1 \
        && echo "  ping github.com: OK" \
        || echo "  ping github.com: FALLITO (puo' essere solo ICMP bloccato)"
    echo "  data di sistema: $(date) (se sbagliata, HTTPS/TLS puo' fallire!)"

    echo "--- installazione precedente ---"
    for p in /usr/lib/enigma2/python/Plugins/Extensions/vavoo \
             /usr/lib64/enigma2/python/Plugins/Extensions/vavoo; do
        [ -d "$p" ] && echo "  trovata: $p" && ls -la "$p" 2>/dev/null | head -n 5
    done
}

# ---------------------------------------------------------------------
# installazione
# ---------------------------------------------------------------------
main() {
    echo "$changelog"

    diagnostics

    if [ ! -d /usr/lib64 ]; then
        PLUGINPATH=/usr/lib/enigma2/python/Plugins/Extensions/vavoo
    else
        PLUGINPATH=/usr/lib64/enigma2/python/Plugins/Extensions/vavoo
    fi
    log "PLUGINPATH=$PLUGINPATH"

    section "RILEVAMENTO OS"
    if [ -f /etc/debian_version ]; then
        OSTYPE="Debian";  STATUS="/var/lib/dpkg/status"
    elif [ -f /var/lib/dpkg/status ]; then
        OSTYPE="DreamOs"; STATUS="/var/lib/dpkg/status"
    elif [ -f /etc/opkg/opkg.conf ] || [ -f /var/lib/opkg/status ]; then
        OSTYPE="OE";      STATUS="/var/lib/opkg/status"
    else
        OSTYPE="Unknown"; STATUS=""
    fi
    log "Detected OS type: $OSTYPE (status file: ${STATUS:-none})"

    UPDATED=0
    pkg_update() {
        [ "$UPDATED" -eq 1 ] && return 0
        case "$OSTYPE" in
            "DreamOs"|"Debian") run apt-get update ;;
            "OE")               run opkg update ;;
        esac
        UPDATED=1
    }

    section "DIPENDENZE"
    if ! command -v wget >/dev/null 2>&1; then
        log "Installing wget..."
        pkg_update
        case "$OSTYPE" in
            "DreamOs"|"Debian") run apt-get install -y wget || fail "Failed to install wget" ;;
            "OE")               run opkg install wget     || fail "Failed to install wget" ;;
            *)                  fail "Unsupported OS type. Cannot install wget." ;;
        esac
    fi

    if ! command -v curl >/dev/null 2>&1; then
        log "Installing curl (best-effort)..."
        pkg_update
        case "$OSTYPE" in
            "DreamOs"|"Debian") run apt-get install -y curl ;;
            "OE")               run opkg install curl ;;
        esac
    fi

    if command -v python3 >/dev/null 2>&1; then
        log "Python3 image detected"
        PYTHON="PY3"; PYBIN=python3
        Packagesix="python3-six"; Packagerequests="python3-requests"
    elif command -v python >/dev/null 2>&1 && python --version 2>&1 | grep -q '^Python 3\.'; then
        log "Python3 image detected (via 'python')"
        PYTHON="PY3"; PYBIN=python
        Packagesix="python3-six"; Packagerequests="python3-requests"
    elif command -v python >/dev/null 2>&1; then
        log "Python2 image detected"
        PYTHON="PY2"; PYBIN=python
        Packagesix="python-six"; Packagerequests="python-requests"
    else
        fail "No Python interpreter found (neither python3 nor python)."
    fi

    install_pkg() {
        local pkg=$1
        # match esatto della riga "Package: nome" (prima matchava anche i prefissi)
        if [ -z "$STATUS" ] || ! grep -qsx "Package: $pkg" "$STATUS" 2>/dev/null; then
            log "Installing $pkg..."
            pkg_update
            case "$OSTYPE" in
                "DreamOs"|"Debian") run apt-get install -y "$pkg" || log "Could not install $pkg, continuing anyway..." ;;
                "OE")               run opkg install "$pkg"     || log "Could not install $pkg, continuing anyway..." ;;
                *)                  log "Cannot install $pkg on unknown OS type, continuing..." ;;
            esac
        else
            log "$pkg already installed"
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
        log "Installing additional dependencies for OpenEmbedded..."
        for pkg in ffmpeg gstplayer exteplayer3 enigma2-plugin-systemplugins-serviceapp; do
            install_pkg "$pkg"
        done
    fi

    section "DOWNLOAD"
    cleanup
    mkdir -p "$TMPPATH" || fail "Cannot create $TMPPATH"

    DOWNLOAD_URL='https://github.com/Belfagor2005/vavoo/archive/refs/heads/main.tar.gz'
    DOWNLOAD_OK=1
    if command -v curl >/dev/null 2>&1; then
        # -sS: niente barra di progresso nel log, ma errori visibili
        run curl -fsSL --connect-timeout 20 -o "$FILEPATH" "$DOWNLOAD_URL"
        DOWNLOAD_OK=$?
    fi
    if [ "$DOWNLOAD_OK" -ne 0 ]; then
        log "Falling back to wget for the download..."
        run wget "$DOWNLOAD_URL" -O "$FILEPATH"
        DOWNLOAD_OK=$?
    fi
    [ "$DOWNLOAD_OK" -ne 0 ] && fail "Failed to download vavoo package!"
    log "Archivio scaricato: $(ls -la "$FILEPATH" 2>/dev/null)"

    section "ESTRAZIONE"
    run tar -xzf "$FILEPATH" -C "$TMPPATH" || fail "Failed to extract vavoo package (archivio corrotto o spazio esaurito in /tmp?)"
    log "Cartelle estratte (primo livello):"
    ls -la "$TMPPATH" 2>/dev/null
    ls -la "$TMPPATH"/* 2>/dev/null | head -n 20

    section "COPIA FILE"
    # File dell'utente da conservare tra un aggiornamento e l'altro
    USERFILES="Favorite.txt"
    BACKUPDIR=/tmp/vavoo-userdata
    rm -rf "$BACKUPDIR"; mkdir -p "$BACKUPDIR"
    if [ -d "$PLUGINPATH" ]; then
        for f in $USERFILES; do
            if [ -f "$PLUGINPATH/$f" ]; then
                cp -f "$PLUGINPATH/$f" "$BACKUPDIR/" && log "Backup dati utente: $f"
            fi
        done
        log "Removing previous installation at $PLUGINPATH..."
        rm -rf "$PLUGINPATH"
    fi
    mkdir -p "$PLUGINPATH" || fail "Cannot create $PLUGINPATH (filesystem read-only o pieno?)"

    COPY_OK=1
    if [ -d "$TMPPATH/vavoo-main/usr/lib/enigma2/python/Plugins/Extensions/vavoo" ]; then
        run cp -r "$TMPPATH/vavoo-main/usr/lib/enigma2/python/Plugins/Extensions/vavoo"/* "$PLUGINPATH/"
        COPY_OK=$?
        log "Copied from standard plugin directory"
    elif [ -d "$TMPPATH/vavoo-main/usr/lib64/enigma2/python/Plugins/Extensions/vavoo" ]; then
        run cp -r "$TMPPATH/vavoo-main/usr/lib64/enigma2/python/Plugins/Extensions/vavoo"/* "$PLUGINPATH/"
        COPY_OK=$?
        log "Copied from lib64 plugin directory"
    elif [ -d "$TMPPATH/vavoo-main/usr" ]; then
        run cp -r "$TMPPATH/vavoo-main/usr"/* /usr/
        COPY_OK=$?
        log "Copied entire usr structure"
    else
        log "Could not find plugin files in extracted archive"
        log "Available directories:"
        find "$TMPPATH" -type d -name "*vavoo*" | head -10
        fail "Struttura archivio inattesa"
    fi
    [ "$COPY_OK" -ne 0 ] && fail "Failed to copy plugin files (cp exited with $COPY_OK) - controlla lo spazio libero qui sopra"

    for f in $USERFILES; do
        if [ -f "$BACKUPDIR/$f" ]; then
            cp -f "$BACKUPDIR/$f" "$PLUGINPATH/$f" && log "Ripristinato dato utente: $f"
        fi
    done
    rm -rf "$BACKUPDIR"
    sync

    section "VERIFICA"
    if [ -f "$PLUGINPATH/plugin.py" ] && [ -f "$PLUGINPATH/plugin.png" ]; then
        log "Plugin files verified: $PLUGINPATH"
        ls -la "$PLUGINPATH/" | head -20
        log "Numero file installati: $(find "$PLUGINPATH" -type f | wc -l)"
    else
        fail "Plugin installation failed - expected files not found in $PLUGINPATH!"
    fi

    # Il plugin puo' essere copiato ma non comparire nel menu se Python
    # non riesce a compilarlo o mancano moduli: lo verifichiamo qui.
    log "Test compilazione plugin.py con $PYBIN..."
    if $PYBIN -c "import py_compile,sys; py_compile.compile(sys.argv[1], doraise=True)" "$PLUGINPATH/plugin.py" 2>&1; then
        log "plugin.py compila correttamente"
    else
        log "!! plugin.py NON compila con $PYBIN: il plugin non apparira' nel menu"
    fi
    for mod in requests six difflib; do
        if $PYBIN -c "import $mod" >/dev/null 2>&1; then
            log "modulo python '$mod': OK"
        else
            log "!! modulo python '$mod': MANCANTE ($($PYBIN -c "import $mod" 2>&1 | tail -n 1))"
        fi
    done

    cleanup
    sync

    box_type=$(sed -n '1p' /etc/hostname 2>/dev/null || echo "Unknown")
    distro_value="Unknown"
    distro_version="Unknown"
    if [ -r /etc/image-version ] && grep -q '^distro=' /etc/image-version; then
        distro_value=$(grep '^distro=' /etc/image-version | head -n 1 | cut -d= -f2)
        distro_version=$(grep '^imageversion=' /etc/image-version | head -n 1 | cut -d= -f2)
        [ -z "$distro_version" ] && distro_version=$(grep '^version=' /etc/image-version | head -n 1 | cut -d= -f2)
    elif [ -r /etc/os-release ]; then
        distro_value=$(grep '^NAME=' /etc/os-release 2>/dev/null | cut -d'"' -f2)
        distro_version=$(grep '^VERSION_ID=' /etc/os-release 2>/dev/null | cut -d'"' -f2)
    elif [ -r /etc/issue ]; then
        distro_value=$(head -n 1 /etc/issue 2>/dev/null | awk '{print $1}')
        distro_version=$(head -n 1 /etc/issue 2>/dev/null | awk '{print $2}')
    elif [ -r /etc/vtiversion.info ]; then
        distro_value=$(head -n 1 /etc/vtiversion.info 2>/dev/null)
    elif [ -r /etc/issue.net ]; then
        distro_value=$(head -n 1 /etc/issue.net 2>/dev/null | awk '{print $1}')
        distro_version=$(head -n 1 /etc/issue.net 2>/dev/null | awk '{print $2}')
    fi
    [ -z "$distro_value" ] && distro_value="Unknown"
    [ -z "$distro_version" ] && distro_version="Unknown"
    python_vers=$($PYBIN --version 2>&1)

    cat <<EOF

#########################################################
#               INSTALLED SUCCESSFULLY                  #
#                developed by LULULLA                   #
#               https://corvoboys.org                   #
#########################################################
#   >>> PLEASE RESTART THE ENIGMA2 GUI MANUALLY <<<     #
#   Menu > Standby/Restart > Restart GUI                #
#   or via telnet:  init 4; sleep 2; init 3             #
#   The plugin will appear only after the restart.      #
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
}

# ---------------------------------------------------------------------
# avvio: tutto l'output (stdout + stderr) va a schermo E nel log.
# Funziona anche con "| /bin/sh" (busybox ash), senza process substitution.
# ---------------------------------------------------------------------
: > "$LOGFILE"
rm -f "$RCFILE"
{
    echo "### vavoo installer log - $(ts)"
    ( main )
    echo $? > "$RCFILE"
} 2>&1 | tee -a "$LOGFILE"

RC=$(cat "$RCFILE" 2>/dev/null || echo 1)
rm -f "$RCFILE"
echo "[$(ts)] Installer terminato con exit code $RC" >> "$LOGFILE"

if [ -d "$LOGCOPY_DIR" ]; then
    cp -f "$LOGFILE" "$LOGCOPY_DIR/vavoo_install.log" 2>/dev/null
fi

echo ""
echo "Log completo salvato in: $LOGFILE"
[ -d "$LOGCOPY_DIR" ] && echo "Copia permanente:         $LOGCOPY_DIR/vavoo_install.log"
if [ "$RC" -ne 0 ]; then
    echo "INSTALLATION FAILED (exit $RC): please send the log file for support."
else
    echo ""
    echo ">>> Restart the Enigma2 GUI manually to see the plugin <<<"
fi

exit "$RC"
