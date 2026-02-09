.PHONY: help lint test build install dev version check-clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

lint: ## Run linter and pre-commit hooks
	@uv run pre-commit run --all-files

test: ## Run tests
	@uv run pytest tests/ -v

build: ## Build package
	@uv build

install: ## Install as uv tool
	@uv tool install -U .

dev: ## Set up dev environment (install pre-commit hooks)
	@uv sync --all-extras
	@uv run pre-commit install

check-clean:
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "Error: uncommitted changes"; \
		git status --short; \
		exit 1; \
	fi

version: check-clean test ## Bump patch version, commit, tag, and push
	@uv version --bump patch
	@VERSION=$$(uv run python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"); \
		uv sync --all-extras; \
		git add pyproject.toml uv.lock; \
		git commit -m "v$$VERSION"; \
		git tag "v$$VERSION"; \
		git push && git push --tags
	@echo "Done. GitHub Actions will publish to PyPI."
