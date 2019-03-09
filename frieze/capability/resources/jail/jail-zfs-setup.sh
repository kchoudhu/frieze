#!/bin/sh -e

# OS base to create
OS_JAIL=${host.os.release_name}
<%text>
# Don't let freebsd-update block on pager
export PAGER=cat

#### Root datasets
DS_JAIL=zroot/jails
MP_JAIL=/usr/local/jails

#### Thinjail layers
#
# Layer 1: RELEASE
#
# Build area for each supported release
RELEASE_DS=${DS_JAIL}/release/${OS_JAIL}
#
# Layer 2: BASE
#
# Template OS, common to all jails. Update this when you want to create security
# updates
BASE_DS=${DS_JAIL}/base/${OS_JAIL}
#
# Layer 3: SKELETON
#
# Template thinjail components, a snapshot of which mounted into every thinjail.
SKELETON_DS=${DS_JAIL}/skeleton/${OS_JAIL}
#
# Layer 4: THINJAIL
#
# Thin, variable parts of individual jails live here.
THINJAIL_DS=${DS_JAIL}/thinjail
THINJAIL_MP=${MP_JAIL}/thinjail

zfs_optionally_create() {
    if [ ! "`zfs list | egrep ${1}`" ]; then
        echo "  zfs create: $1"
        zfs create -p $1
        if [ $2 ]; then
            zfs set mountpoint=$2 $1
        fi
    else
        echo "  already present: ${1}"
    fi
}

zfs_mountpoint() {
    echo "`zfs get mountpoint $1 | tail -1 | awk '{print $3}'`"
}

create_layer_0_zfs(){
    echo "Creating ZFS layer"
    zfs_optionally_create ${DS_JAIL} ${MP_JAIL}
    zfs_optionally_create ${RELEASE_DS}
    zfs_optionally_create ${BASE_DS}
    zfs_optionally_create ${SKELETON_DS}
    zfs_optionally_create ${THINJAIL_DS}
}

create_layer_1_release(){

    echo "Creating RELEASE snapshot for ${OS_JAIL}"

    RELEASE_MP=`zfs_mountpoint ${RELEASE_DS}`
    RELEASE_SNAP=${RELEASE_DS}@$`date +"%Y%m%d%H%M%S"`
    SENTINEL_L1_DIR=${RELEASE_MP}/sentinel
    SENTINEL_L1_DONE=${SENTINEL_L1_DIR}/layer-1

    if [ ! -e ${SENTINEL_L1_DONE} ]; then
        mkdir -p ${SENTINEL_L1_DIR}

        RELTMP=`mktemp -d "/tmp/jailbootstrap.XXXXXX"`
        trap 'rm -r "$RELTMP"' EXIT

        echo "  Fetching components"
        fetch https://ftp.freebsd.org/pub/FreeBSD/releases/amd64/amd64/${OS_JAIL}/base.txz -qo  ${RELTMP}/base.txz
        fetch https://ftp.freebsd.org/pub/FreeBSD/releases/amd64/amd64/${OS_JAIL}/lib32.txz -qo ${RELTMP}/lib32.txz

        echo "  Extracting components"
        tar -xf ${RELTMP}/base.txz  -C ${RELEASE_MP}
        tar -xf ${RELTMP}/lib32.txz -C ${RELEASE_MP}


        touch ${SENTINEL_L1_DONE}

        echo "  Creating snapshot [${RELEASE_SNAP}]"
        zfs snapshot ${RELEASE_SNAP}
    else
        echo "  ${OS_JAIL} snapshot already present"
    fi
}

create_layer_2_base(){

    echo "Creating BASE (updatable) snapshot from RELEASE"

    BASE_MP=`zfs_mountpoint ${BASE_DS}`

    RELEASE_MP=`zfs_mountpoint ${RELEASE_DS}`
    RELEASE_SNAP_LAST=`zfs list -rt snapshot | egrep RELEASE | tail -1 | awk '{print $1}'`

    SENTINEL_L2_DIR=${BASE_MP}/sentinel
    SENTINEL_L2_DONE=${SENTINEL_L2_DIR}/layer-2

    if [ ! -e ${SENTINEL_L2_DONE} ]; then
        if [ "`zfs list | egrep ${BASE_DS}`" ]; then
            echo "  Stale BASE detected, destroying"
            zfs destroy -f ${BASE_DS}
        fi

        echo "  Cloning RELEASE to BASE"
        echo "zfs clone -p ${RELEASE_SNAP_LAST} ${BASE_DS}"
        zfs clone -p ${RELEASE_SNAP_LAST} ${BASE_DS}

        cp /etc/localtime ${BASE_MP}/etc/localtime

        echo "  Executing freebsd-update fetch in [${BASE_MP}]"
        env UNAME_r=${OS_JAIL} freebsd-update --not-running-from-cron -b ${BASE_MP} fetch

        if [ -e /var/db/freebsd-update/`echo ${BASE_MP} | sha256`-install ]; then
            echo "  Executing freebsd-update install in [${BASE_MP}]"
            freebsd-update -b ${BASE_MP} install
        else
            echo "  Detected no need to install updates, proceeding"
        fi

        touch ${SENTINEL_L2_DONE}
    else
        echo "  No need to create base image"
    fi
}

create_layer_3_skeleton(){

    echo "Creating SKELETON dataset from BASE"

    BASE_MP=`zfs_mountpoint ${BASE_DS}`

    SKELETON_MP=`zfs_mountpoint ${SKELETON_DS}`
    SKELETON_SNAP=${SKELETON_DS}@skeleton

    SENTINEL_L3_DIR=${BASE_MP}/sentinel
    SENTINEL_L3_DONE=${SENTINEL_L3_DIR}/layer-3

    if [ ! -e ${SENTINEL_L3_DONE} ]; then
        cd ${BASE_MP}
        echo "  Copying skeleton files from base template"
        mkdir -p ${SKELETON_MP}/home
        mkdir -p ${SKELETON_MP}/usr
        chflags 0 ${BASE_MP}/var/empty
        rm -rf ${BASE_MP}/var/empty
        mv ${BASE_MP}/etc       ${SKELETON_MP}/etc
        mv ${BASE_MP}/usr/local ${SKELETON_MP}/usr/local
        mv ${BASE_MP}/tmp       ${SKELETON_MP}/tmp
        mv ${BASE_MP}/var       ${SKELETON_MP}/var
        mv ${BASE_MP}/root      ${SKELETON_MP}/root

        echo "  Setting up links to skeleton files"
        mkdir skeleton
        ln -s skeleton/etc etc
        ln -s skeleton/home home
        ln -s skeleton/root root
        ln -s ../skeleton/usr/local usr/local
        ln -s skeleton/tmp tmp
        ln -s skeleton/var var

        echo "  Creating skeleton template snapshot"
        zfs snapshot ${SKELETON_SNAP}

        touch ${SENTINEL_L3_DONE}
    else
        echo "  No need to create skeleton data"
    fi
}

create_layer_0_zfs
create_layer_1_release
create_layer_2_base
create_layer_3_skeleton
</%text>\
