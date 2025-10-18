FROM mcr.microsoft.com/devcontainers/python:3.13

# Install uv using the project's installer (avoid using pip in the container)
# Ensure curl and ca-certificates are available so we can download the installer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates git

# Ensure user-local bin is on PATH for the vscode user so uv installed to ~/.local/bin is found.
ENV PATH="/home/vscode/.local/bin:${PATH}"

# Install uv as the non-root vscode user via the official installer. The installer will
# place binaries in the user's local bin (~/.local/bin) by default.
USER vscode

RUN curl -LsSf https://astral.sh/uv/install.sh | sh -s
