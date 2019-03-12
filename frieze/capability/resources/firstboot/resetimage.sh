#!/bin/sh -e
<%text>
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

rm ${FETCHKEYRC_SCRIPT}
rm ${CFGINITRC_SCRIPT}
rm ${CFGINIT_SCRIPT}
yes | pkg delete firstboot-freebsd-update firstboot-pkgs

sysrc -f ${RCCONF} -x ${FIRSTBOOT_UPDATE}_enable
sysrc -f ${RCCONF} -x ${FIRSTBOOT_PKGS}_enable
sysrc -f ${RCCONF} -x ${FETCHKEYRC}_enable
sysrc -f ${RCCONF} -x ${CFGINITRC}_enable

rm ${FIRSTBOOT_SENTINEL}

bectl activate default
bectl destroy -F bootstrap-done
</%text>\
