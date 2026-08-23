SUMMARY = "Vavoo Stream Live"
MAINTAINER = "Lululla"
SECTION = "base"
PRIORITY = "required"
# Matches the project's real license (CC BY-NC-SA 4.0, see CLAUDE.md,
# README, and every CONTROL/post*/preinst header) - this was previously
# "proprietary" together with an unrelated GPLv2 license require, which
# directly contradicted both the actual license and each other.
LICENSE = "CC-BY-NC-SA-4.0"

RDEPENDS:${PN} = "ffmpeg gstplayer exteplayer3 enigma2-plugin-systemplugins-serviceapp python3-requests python3-six"

inherit allarch gitpkgv python3-compileall

# Keep in sync with __version__ in usr/lib/.../vavoo/__init__.py,
# CONTROL/control's Version:, and installer.sh's version= - none of
# these are auto-synced (see CLAUDE.md), and this file previously
# stayed at the placeholder "1.0" indefinitely.
PV = "1.88+git${SRCPV}"
PKGV = "1.88+git${GITPKGV}"
VER = "1.88"
PR = "r0"

SRC_URI = "git://github.com/Belfagor2005/vavoo.git;protocol=https;branch=main"

S = "${WORKDIR}/git"

FILES:${PN} = "/usr/*"
FILES:${PN}-src = "${libdir}/enigma2/python/Plugins/Extensions/vavoo/*.py ${libdir}/enigma2/python/Plugins/Extensions/vavoo/*/*.py"

do_install() {
    cp -af --no-preserve=ownership ${S}/usr* ${D}/
}
