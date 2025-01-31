#!/usr/bin/env bash
# Test runner script with useful pytest options
COVERAGE_ARGS='--cov --cov-report=term --cov-report=html'
export STRESS_TEST_MULTIPLIER=2

# Run unit tests first (and with multiprocessing) to fail quickly if there are issues
pytest tests/unit -x --numprocesses=auto $COVERAGE_ARGS
pytest tests/integration -x --cov-append $COVERAGE_ARGS
