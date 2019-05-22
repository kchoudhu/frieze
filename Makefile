# Prefixes
PROJECT=frieze

# Build environment
EXECDIR!=pwd
BUILD=${EXECDIR}/build
BUILD_PKG=${BUILD}/remote/pkg/freebsd
BUILD_FRIEZE=${BUILD}/remote/frieze

# Configurations
CFGDIR!=realpath ${BUILD}/local/cfg

# Python environment
PIP?=pip-3.6
PIP_OPTIONS=--global-option=build_ext --global-option="-I/usr/local/include/" --global-option="-L/usr/local/lib"
DEVPI?="devpi"
PYTHON=/usr/local/bin/python3
PYTEST_FILE_PATTERN?="*_test.py"

# Database
PSQL?=/usr/local/bin/psql
DBNAME=${PROJECT}

# Application variables
HOME?=/usr/home/${USER}
SRCDIR?=${HOME}/src
FRIEZE_PYMODULE_NAME=frieze
FRIEZE_PROJECT_DIR=${SRCDIR}/${FRIEZE_PYMODULE_NAME}
OPENARC_PYMODULE_NAME?=openarc
OPENARC_PROJECT_DIR?=${SRCDIR}/${OPENARC_PYMODULE_NAME}
VULTR_PYMODULE_NAME?=vultr
VULTR_PROJECT_DIR?=${SRCDIR}/python-vultr
BLESS_PYMODULE_NAME=bless
BLESS_PROJECT_DIR=${SRCDIR}/${BLESS_PYMODULE_NAME}

# Variables needed to push frieze
PUSHCREDS=anserinae@anserinae.net
PUSHDIR=anserinae.net/firstboot

dbcfg:
	(cd ~ && make cfg=${CFGDIR}/postgresql.conf pgcfgadd)
	(cd ~ && make cfg=${CFGDIR}/pg_hba.conf     pgcfgadd)
	(cd ~ && make cfg=${CFGDIR}/pg_bouncer.ini  pgcfgadd)
	cp ${CFGDIR}/openarc.conf   ~/.config/
	cp ${CFGDIR}/openarc.conf   ~/.frieze/cfg/
	cp ${CFGDIR}/frieze.conf    ~/.frieze/cfg/
	cp ${CFGDIR}/bless.conf     ~/.frieze/cfg/

dbstop:
	(cd ~ && make db=${DBNAME} pgstop)

dbstart: dbcfg
	(cd ~ && make db=${DBNAME} pgstart)
	${PSQL} -d ${DBNAME} < ${CFGDIR}/pg_init.sql

dbinit: dbcfg
	createdb -h /tmp ${DBNAME}

pyclean:
	-/usr/bin/yes | ${PIP} uninstall ${OPENARC_PYMODULE_NAME}
	-/usr/bin/yes | ${PIP} uninstall ${VULTR_PYMODULE_NAME}
	-/usr/bin/yes | ${PIP} uninstall ${FRIEZE_PYMODULE_NAME}
	-/usr/bin/yes | ${PIP} uninstall ${BLESS_PYMODULE_NAME}
	-rm ${FRIEZE_PYMODULE_NAME}/*.pyc
	-rm ${FRIEZE_PYMODULE_NAME}/tests/*.pyc
	-rm ${FRIEZE_PYMODULE_NAME}

pyinit: pyclean

	# Make sure devpi is working
	(cd ~ && make startenv)

	# Upload locally developed packages
	(cd ${BLESS_PROJECT_DIR} && ${DEVPI} upload && rm -rf ./dist)
	(cd ${OPENARC_PROJECT_DIR} && ${DEVPI} upload && rm -rf ./dist)
	(cd ${VULTR_PROJECT_DIR} && ${DEVPI} upload && rm -rf ./dist)
	(cd ${FRIEZE_PROJECT_DIR} && ${DEVPI} upload && rm -rf ./dist)

	# Install backend
	${PIP} install --no-cache-dir ${PIP_OPTIONS} ${FRIEZE_PYMODULE_NAME} --user

test: dbstart
	# Todo: replace this with TAP output
	@echo "Running tests"
	${PYTHON} -m unittest discover ./${PROJECT}/tests -p ${PYTEST_FILE_PATTERN}

push-bootstrap:
	scp ./${PROJECT}/resources/firstboot/configinit\
	./${PROJECT}/resources/firstboot/*.sh\
	./${PROJECT}/resources/firstboot/frieze_fetchkey\
	./${PROJECT}/resources/firstboot/frieze_configinit\
	${PUSHCREDS}:${PUSHDIR}
