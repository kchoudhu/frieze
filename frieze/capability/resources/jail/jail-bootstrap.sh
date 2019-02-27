#!/bin/sh -e
${"""
# Don't let freebsd-update block on pager
export PAGER=cat

# Datasets and their mountpoints
DATE=`date +"%Y%m%d%H%M%S"`
OS_JAIL=12.0-RELEASE
DS_JAIL=zroot/jails
MP_JAIL=/usr/local/jails

RELEASE_DS=${DS_JAIL}/release/${OS_JAIL}
RELEASE_MP=${MP_JAIL}/release/${OS_JAIL}
RELEASE_SNAP=${RELEASE_DS}@${DATE}

TEMPLATE_DS=${DS_JAIL}/template
TEMPLATE_MP=${MP_JAIL}/template

BASE_DS=${TEMPLATE_DS}/base/${OS_JAIL}
BASE_MP=${TEMPLATE_MP}/base/${OS_JAIL}

SKELETON_DS=${DS_JAIL}/skeleton/${OS_JAIL}
SKELETON_MP=${MP_JAIL}/skeleton/${OS_JAIL}

THINJAIL_DS=${DS_JAIL}/thinjail
THINJAIL_MP=${MP_JAIL}/thinjail

# Progress sentinels
SENTINEL_DIR=${RELEASE_MP}/sentinel
SENTINEL_FIRST=${SENTINEL_DIR}/first
SENTINEL_UPD_FETCH=${SENTINEL_DIR}/upd-fetch
SENTINEL_REL_DONE=${SENTINEL_DIR}/rel

echo "Creating datasets"
if [ ! "`zfs list | egrep ${DS_JAIL}`" ]; then
    echo "  zfs create: ${DS_JAIL}"
    zfs create -o mountpoint=${MP_JAIL} ${DS_JAIL}
else
    echo "  already present: ${DS_JAIL}"
fi
if [ ! "`zfs list | egrep ${TEMPLATE_DS}`" ]; then
    echo "  zfs create: ${TEMPLATE_DS}"
    zfs create -p ${TEMPLATE_DS}
else
    echo "  already present: ${TEMPLATE_DS}"
fi

if [ ! "`zfs list | egrep ${SKELETON_DS}`" ]; then
    echo "  zfs create: ${SKELETON_DS}"
    zfs create -p ${SKELETON_DS}
else
    echo "  already present: ${SKELETON_DS}"
fi

echo "Creating RELEASE snapshot"
if [ ! -e ${SENTINEL_REL_DONE} ]; then

    if [ ! "`zfs list | egrep ${RELEASE_DS}`" ]; then
        echo "  zfs create: ${RELEASE_DS}"
        zfs create -p ${RELEASE_DS}
        mkdir -p ${SENTINEL_DIR}
    fi


    if [ ! -e ${SENTINEL_FIRST} ]; then
        echo "  template container components: fetch"
        RELTMP=`mktemp -d "/tmp/jailbootstrap.XXXXXX"`
        trap 'rm -r "$RELTMP"' EXIT

        fetch ftp://ftp.freebsd.org/pub/FreeBSD/releases/amd64/amd64/${OS_JAIL}/base.txz -o  ${RELTMP}/base.txz
        fetch ftp://ftp.freebsd.org/pub/FreeBSD/releases/amd64/amd64/${OS_JAIL}/lib32.txz -o ${RELTMP}/lib32.txz

        tar -xf ${RELTMP}/base.txz  -C ${RELEASE_MP}
        tar -xf ${RELTMP}/lib32.txz -C ${RELEASE_MP}

        touch ${SENTINEL_FIRST}
    else
        echo "  template container components already present"
    fi

    if [ ! -e ${SENTINEL_UPD_FETCH} ]; then
        echo "  update template container components: fetch"
        env UNAME_r=${OS_JAIL} freebsd-update --not-running-from-cron -b ${RELEASE_MP} fetch
        touch ${SENTINEL_UPD_FETCH}
    else
        echo "  container component updates already fetched"
    fi

    # Check freebsd-update director for
    if [ -e /var/db/freebsd-update/`echo ${RELEASE_MP} | sha256`-install ]; then
        echo "  update template container components: install"
        freebsd-update -b ${RELEASE_MP} install
    else
        echo "  template container component updates already installed"
    fi

    cp /etc/localtime ${RELEASE_MP}/etc/localtime
    zfs snapshot ${RELEASE_SNAP}

    echo "Creating base template"
    LAST_REL_SNAP=`zfs list -rt snapshot | egrep RELEASE | tail -1 | awk '{print $1}'`
    if [ "`zfs list | egrep ${BASE_DS}`" ]; then
        echo "  old base template detected, destroying"
        zfs destroy -f ${BASE_DS}
    fi
    zfs clone -p ${LAST_REL_SNAP} ${BASE_DS}

    cd ${BASE_MP}
    echo "Initalizing skeleton template from base template"
    mkdir -p ${SKELETON_MP}/home
    mkdir -p ${SKELETON_MP}/usr
    chflags 0 ${BASE_MP}/var/empty
    rm -rf ${BASE_MP}/var/empty
    mv ${BASE_MP}/etc       ${SKELETON_MP}/etc
    mv ${BASE_MP}/usr/local ${SKELETON_MP}/usr/local
    mv ${BASE_MP}/tmp       ${SKELETON_MP}/tmp
    mv ${BASE_MP}/var       ${SKELETON_MP}/var
    mv ${BASE_MP}/root      ${SKELETON_MP}/root

    echo "Setting up skeleton template"
    mkdir skeleton
    ln -s skeleton/etc etc
    ln -s skeleton/home home
    ln -s skeleton/root root
    ln -s ../skeleton/usr/local usr/local
    ln -s skeleton/tmp tmp
    ln -s skeleton/var var

    echo "Creating skeleton template snapshot"
    zfs snapshot ${SKELETON_DS}@skeleton

    # Set release-done sentinel
    touch ${SENTINEL_REL_DONE}
else
    echo "  RELEASE snapshot detected at ${RELEASE_MP}, nothing to do"
fi"""}
