# Prefixes
PROJECT=frieze

# Environment
ENV=dev

# Common
HOME?=/usr/home/${USER}
SRCDIR?=${HOME}/src

# Python environment
PIP?="pip-3.6"
PYTHON?="python3"
PYTEST_FILE_PATTERN?="*test.py"

# Application variables
BACKEND_PYMODULE_NAME=frieze
BACKEND_PROJECT_DIR=${SRCDIR}/${BACKEND_PYMODULE_NAME}
OPENARC_PYMODULE_NAME?=openarc
OPENARC_PROJECT_DIR?=${SRCDIR}/${OPENARC_PYMODULE_NAME}

# Variables needed to push frieze
PUSHCREDS=anserinae@anserinae.net
PUSHDIR=anserinae.net/firstboot

pyclean:
	-/usr/bin/yes | ${PIP} uninstall ${OPENARC_PYMODULE_NAME}
	-/usr/bin/yes | ${PIP} uninstall ${BACKEND_PYMODULE_NAME}
	-rm ${BACKEND_PYMODULE_NAME}/*.pyc
	-rm ${BACKEND_PYMODULE_NAME}/tests/*.pyc
	-rm ${BACKEND_PYMODULE_NAME}

pyinit: pyclean
	${PIP} install ${OPENARC_PROJECT_DIR} --user
	${PIP} install ${BACKEND_PROJECT_DIR} --user

push-bootstrap:
	scp ./${PROJECT}/resources/firstboot/configinit\
	./${PROJECT}/resources/firstboot/*.sh\
	./${PROJECT}/resources/firstboot/frieze_fetchkey\
	./${PROJECT}/resources/firstboot/frieze_configinit\
	${PUSHCREDS}:${PUSHDIR}

clean:
	@rm ./${PROJECT}/*.pyc
	@rm ./${PROJECT}/tests/*.pyc

test: pyinit
	# Todo: replace this with TAP output
	@echo "Running tests: ${BACKEND_PYMODULE_NAME}"
	@${PYTHON} -m unittest discover ./${BACKEND_PYMODULE_NAME}/tests -p ${PYTEST_FILE_PATTERN}
