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

BOOTSTRAP_ROOT=https://www.anserinae.net/firstboot

mkdir -p ${URCDIR}

yes | pkg install firstboot-freebsd-update firstboot-pkgs ec2-scripts
fetch -o ${CFGINIT_SCRIPT} ${BOOTSTRAP_ROOT}/${CFGINIT}
fetch -o ${FETCHKEY_SCRIPT} ${BOOTSTRAP_ROOT}/${FETCHKEY}
chmod 0555 ${CFGINIT_SCRIPT}
chmod 0555 ${FETCHKEY_SCRIPT}

sysrc -f ${RCCONF} ${FIRSTBOOT_UPDATE}_enable="YES"
sysrc -f ${RCCONF} ${FIRSTBOOT_PKGS}_enable="YES"
sysrc -f ${RCCONF} ${CFGINIT}_enable="YES"
sysrc -f ${RCCONF} ${FETCHKEY}_enable="YES"

touch ${FIRSTBOOT_SENTINEL}
