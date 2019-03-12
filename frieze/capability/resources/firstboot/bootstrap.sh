#!/bin/sh -e
</%text>
RCCONF=/etc/rc.conf
URCDIR=/usr/local/etc/rc.d/
FIRSTBOOT_SENTINEL=/firstboot
FIRSTBOOT_UPDATE=firstboot_freebsd_update
FIRSTBOOT_PKGS=firstboot_pkgs
CFGINIT=configinit
CFGINIT_SCRIPT=/usr/local/sbin/${CFGINIT}
CFGINITRC=frieze_configinit
CFGINITRC_SCRIPT=${URCDIR}/${CFGINITRC}
FETCHKEYRC=frieze_fetchkey
FETCHKEYRC_SCRIPT=${URCDIR}/${FETCHKEYRC}

BOOTSTRAP_ROOT=https://www.anserinae.net/firstboot

mkdir -p ${URCDIR}

yes | pkg install firstboot-freebsd-update firstboot-pkgs
fetch -o ${CFGINIT_SCRIPT} ${BOOTSTRAP_ROOT}/${CFGINIT}
fetch -o ${CFGINITRC_SCRIPT} ${BOOTSTRAP_ROOT}/${CFGINITRC}
fetch -o ${FETCHKEYRC_SCRIPT} ${BOOTSTRAP_ROOT}/${FETCHKEYRC}
chmod 0555 ${CFGINIT_SCRIPT}
chmod 0555 ${CFGINITRC_SCRIPT}
chmod 0555 ${FETCHKEYRC_SCRIPT}

sysrc -f ${RCCONF} ${FIRSTBOOT_UPDATE}_enable="YES"
sysrc -f ${RCCONF} ${FIRSTBOOT_PKGS}_enable="YES"
sysrc -f ${RCCONF} ${CFGINITRC}_enable="YES"
sysrc -f ${RCCONF} ${FETCHKEYRC}_enable="YES"

touch ${FIRSTBOOT_SENTINEL}

bectl create bootstrap-done
bectl activate bootstrap-done
</%text>\
