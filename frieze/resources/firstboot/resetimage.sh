#!/bin/sh -e

RCCONF=/etc/rc.conf
URCDIR=/usr/local/etc/rc.d/
FIRSTBOOT_SENTINEL=/firstboot
FIRSTBOOT_UPDATE=firstboot_freebsd_update
FIRSTBOOT_PKGS=firstboot_pkgs
CFGINIT=frieze_configinit
CFGINIT_SCRIPT=${URCDIR}/${CFGINIT}
FETCHKEY=frieze_fetchkey
FETCHKEY_SCRIPT=${URCDIR}/${FETCHKEY}

rm ${FETCHKEY_SCRIPT}
rm ${CFGINIT_SCRIPT}
yes | pkg delete firstboot-freebsd-update firstboot-pkgs ec2-scripts

sysrc -f ${RCCONF} -x firstboot_freebsd_update_enable
sysrc -f ${RCCONF} -x firstboot_pkgs_enable
sysrc -f ${RCCONF} -x ${FETCHKEY}_enable
sysrc -f ${RCCONF} -x ${CFGINIT}_enable

rm ${FIRSTBOOT_SENTINEL}
