DBRUNDIR?=~/run/db
DBCFGDIR?=./cfg/
DBSOCKDIR?=/tmp
DBLOGDIR?=/tmp
PGCTL?=/usr/local/bin/pg_ctl
PYTEST_BIN?="python -m unittest discover"
PYTEST_FILE_PATTERN?="*_test.py"
PROJECT=frieze

clean:
	@rm ./${PROJECT}/*.pyc
	@rm ./${PROJECT}/tests/*.pyc

dbinit:
	-dropdb -h ${DBSOCKDIR} ${PROJECT}
	createdb -h ${DBSOCKDIR} ${PROJECT}

test:
	# Todo: replace this with TAP output
	@echo "Running tests"
	python3 -m unittest discover ./{${PROJECT}}/tests -p ${PYTEST_FILE_PATTERN}

testclean: dbinit test
