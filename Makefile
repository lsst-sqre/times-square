# The dependencies need --allow-unsafe because kubernetes-asyncio and
# (transitively) pre-commit depends on setuptools, which is normally not
# allowed to appear in a hashed dependency file.
.PHONY: update-deps
update-deps:
	pip install --upgrade pip-tools pip setuptools
	pip-compile --upgrade --resolver=backtracking --build-isolation	\
	    --allow-unsafe --generate-hashes \
	    --output-file requirements/main.txt requirements/main.in
	pip-compile --upgrade --resolver=backtracking --build-isolation	\
	    --allow-unsafe --generate-hashes \
	    --output-file requirements/dev.txt requirements/dev.in

# Useful for testing against a Git version of Safir.
.PHONY: update-deps-no-hashes
update-deps-no-hashes:
	pip install --upgrade pip-tools pip setuptools
	pip-compile --upgrade --resolver=backtracking --build-isolation	\
	    --allow-unsafe \
	    --output-file requirements/main.txt requirements/main.in
	pip-compile --upgrade --resolver=backtracking --build-isolation	\
	    --allow-unsafe \
	    --output-file requirements/dev.txt requirements/dev.in

.PHONY: init
init:
	pip install --editable .
	pip install --upgrade -r requirements/main.txt -r requirements/dev.txt
	rm -rf .tox
	pip install --upgrade tox tox-docker scriv pre-commit
	pre-commit install

.PHONY: update
update: update-deps init

.PHONY: run
run:
	tox run -e=run
