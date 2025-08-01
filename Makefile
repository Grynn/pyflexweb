.PHONY: lint test build dev install bump-patch bump-minor bump-major release pre-commit-install pre-commit-run setup-repo setup-pypi check-clean

# Show PyPI setup instructions
setup-pypi:
	@./scripts/setup-pypi.sh

lint:
	@echo "Running pre-commit hooks..."
	@uv run pre-commit run --all-files
	@echo "Linting completed successfully."

pre-commit-install:
	@echo "Installing pre-commit hooks..."
	@uv run pre-commit install
	@echo "Pre-commit hooks installed successfully."

pre-commit-run:
	@echo "Running pre-commit hooks on all files..."
	@uv run pre-commit run --all-files
	@echo "Pre-commit completed successfully."

test:
	@echo "Running tests..."
	@uv run pytest tests/ -v
	@echo "Tests completed successfully."

build:
	@echo "Building package..."
	@uv build
	@echo "Build completed successfully."

dev:
	@echo "Setting up development environment..."
	@uv sync --all-extras
	@echo "Development environment ready."

install:
	@echo "Installing package..."
	@uv tool install -U .
	@echo "Package installed successfully."

# Check for uncommitted changes (used by release)
check-clean:
	@echo "Checking for uncommitted changes..."
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "Error: There are uncommitted changes in the working tree:"; \
		git status --short; \
		echo "Please commit or stash your changes before creating a release."; \
		exit 1; \
	fi
	@echo "Working tree is clean."

# Version bumping targets
bump-patch:
	@echo "Bumping patch version..."
	@python -c "import toml; \
		config = toml.load('pyproject.toml'); \
		version = config['project']['version'].split('.'); \
		version[2] = str(int(version[2]) + 1); \
		config['project']['version'] = '.'.join(version); \
		toml.dump(config, open('pyproject.toml', 'w'))"
	@echo "Version bumped to: $$(python -c "import toml; print(toml.load('pyproject.toml')['project']['version'])")"
	uv sync --all-extras

bump-minor:
	@echo "Bumping minor version..."
	@python -c "import toml; \
		config = toml.load('pyproject.toml'); \
		version = config['project']['version'].split('.'); \
		version[1] = str(int(version[1]) + 1); \
		version[2] = '0'; \
		config['project']['version'] = '.'.join(version); \
		toml.dump(config, open('pyproject.toml', 'w'))"
	@echo "Version bumped to: $$(python -c "import toml; print(toml.load('pyproject.toml')['project']['version'])")"
	uv sync --all-extras

bump-major:
	@echo "Bumping major version..."
	@python -c "import toml; \
		config = toml.load('pyproject.toml'); \
		version = config['project']['version'].split('.'); \
		version[0] = str(int(version[0]) + 1); \
		version[1] = '0'; \
		version[2] = '0'; \
		config['project']['version'] = '.'.join(version); \
		toml.dump(config, open('pyproject.toml', 'w'))"
	@echo "Version bumped to: $$(python -c "import toml; print(toml.load('pyproject.toml')['project']['version'])")"
	uv sync --all-extras

# Release target
release: check-clean lint test build
	@echo "Creating release..."
	@VERSION=$$(python -c "import toml; print(toml.load('pyproject.toml')['project']['version'])"); \
		echo "Preparing release for version $$VERSION"; \
		git add pyproject.toml; \
		git commit -m "Bump version to $$VERSION" || echo "No changes to commit"; \
		git tag -a "v$$VERSION" -m "Release version $$VERSION"; \
		git push origin main; \
		git push origin "v$$VERSION"; \
		gh release create "v$$VERSION" --title "v$$VERSION" --notes "Release version $$VERSION" --latest
	@echo "Release completed successfully."
