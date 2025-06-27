.PHONY: help install install-dev test lint format type-check clean build release

help:
	@echo "Available targets:"
	@echo "  install      - Install the package"
	@echo "  install-dev  - Install the package with development dependencies"
	@echo "  test         - Run tests"
	@echo "  lint         - Run linting (flake8, pylint)"
	@echo "  format       - Format code (black, isort)"
	@echo "  type-check   - Run type checking (mypy)"
	@echo "  clean        - Clean build artifacts"
	@echo "  build        - Build the package"
	@echo "  release      - Build and check the package for release"

install: build test
	pip install -e .

install-dev:
	pip install -e ".[dev,test]"

test: lint build
	python -m pytest

lint:
	python -m flake8 src test
	python -m pylint src test

format:
	python -m black src test
	python -m isort src test

type-check:
	python -m mypy src

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf htmlcov/
	rm -f coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build:
	python -m build

release: clean build test
	python -m twine check dist/*
	@echo "Package is ready for release. Run 'python -m twine upload dist/*' to publish."
