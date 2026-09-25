.PHONY: install test demo lint
install:
	python -m pip install -e ".[dev]"
test:
	pytest -q
demo:
	ega demo --output results/demo
lint:
	python -m compileall -q src tests
