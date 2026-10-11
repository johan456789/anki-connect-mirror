.DEFAULT_GOAL := help

PYTHON ?= python3
# Leave empty to use the version matrix defined in tools/test.sh.
VERSIONS ?=

.PHONY: help test test-unit check contract package link

help:
	@printf '%s\n' \
		'make test       Run the cached Anki matrix, including GUI scenarios' \
		'make test-unit  Run the matrix without GUI scenarios' \
		'make check      Check generated contract, API docs, coverage, and syntax' \
		'make contract   Regenerate plugin/contract.py' \
		'make package    Build AnkiConnect.zip without cleaning the checkout' \
		'make link       Link the add-on into an existing Linux/macOS Anki folder' \
		'' \
		'Overrides: VERSIONS="26.8 26.9.3" for tests; PYTHON=/path/to/python for check/contract/package'

test:
	./tools/test.sh $(VERSIONS)

test-unit:
	./tools/test.sh --no-ui $(VERSIONS)

check:
	"$(PYTHON)" tools/build_api_contract.py --check
	"$(PYTHON)" tools/check_api_spec.py
	"$(PYTHON)" tools/check_api_docs.py
	"$(PYTHON)" tools/check_api_coverage.py
	"$(PYTHON)" -m compileall -q plugin tools tests_api
	git diff --check

contract:
	"$(PYTHON)" tools/build_api_contract.py

package:
	PYTHON="$(PYTHON)" ./tools/package.sh

link:
	./tools/link.sh
