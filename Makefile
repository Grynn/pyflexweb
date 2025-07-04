.PHONY: lint test build dev install bump-patch bump-minor bump-major release

lint:
	@echo "Running linters..."
	@uv run ruff check --fix .
	@uv run isort --profile black .
	@uv run black .
	@echo "Linters completed successfully."

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

# Release target
release: lint test build
	@echo "Creating release..."
	@VERSION=$$(python -c "import toml; print(toml.load('pyproject.toml')['project']['version'])"); \
		echo "Preparing release for version $$VERSION"; \
		git add pyproject.toml; \
		git commit -m "Bump version to $$VERSION"; \
		git tag -a "v$$VERSION" -m "Release version $$VERSION"; \
		echo "Release $$VERSION created. Push with: git push origin main --tags"
	@echo "Release completed successfully."