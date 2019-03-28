# Prefixes
PROJECT=frieze

# Environment
ENV=dev

# Common
HOME?=/usr/home/${USER}
SRCDIR?=${HOME}/src

# Python environment
PIP?="pip-3.6"
DEVPI?="devpi"
DEVPI-SERVER?="devpi-server"
PYTHON?="python3"
PYTEST_FILE_PATTERN?="*test.py"

# Application variables
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

pyclean:
	-/usr/bin/yes | ${PIP} uninstall ${OPENARC_PYMODULE_NAME}
	-/usr/bin/yes | ${PIP} uninstall ${VULTR_PYMODULE_NAME}
	-/usr/bin/yes | ${PIP} uninstall ${FRIEZE_PYMODULE_NAME}
	-/usr/bin/yes | ${PIP} uninstall ${BLESS_PYMODULE_NAME}
	-rm ${FRIEZE_PYMODULE_NAME}/*.pyc
	-rm ${FRIEZE_PYMODULE_NAME}/tests/*.pyc
	-rm ${FRIEZE_PYMODULE_NAME}

pyinit: pyclean

	# Make sure all packages have been uploaded
	# Some helper tools
	${PIP} install --no-cache-dir wheel devpi-server devpi-client --user

	# Start DevPI (or check on its status)
	-${DEVPI-SERVER} --start

	# Upload locally developed packages
	cd ${BLESS_PROJECT_DIR} && ${DEVPI} upload
	cd ${OPENARC_PROJECT_DIR} && ${DEVPI} upload
	cd ${VULTR_PROJECT_DIR} && ${DEVPI} upload
	cd ${FRIEZE_PROJECT_DIR} && ${DEVPI} upload

	${PIP} install --no-cache-dir ${FRIEZE_PYMODULE_NAME} --user

push-bootstrap:
	scp ./${PROJECT}/resources/firstboot/configinit\
	./${PROJECT}/resources/firstboot/*.sh\
	./${PROJECT}/resources/firstboot/frieze_fetchkey\
	./${PROJECT}/resources/firstboot/frieze_configinit\
	${PUSHCREDS}:${PUSHDIR}

clean:
	@rm ./${PROJECT}/*.pyc
	@rm ./${PROJECT}/tests/*.pyc

test: #pyinit
	# Todo: replace this with TAP output
	@echo "Running tests: ${FRIEZE_PYMODULE_NAME}"
	@${PYTHON} -m unittest discover ./${FRIEZE_PYMODULE_NAME}/tests -p ${PYTEST_FILE_PATTERN}
