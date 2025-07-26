#!/usr/bin/env bash

# PyPI Setup Instructions
# =======================
#
# This script provides instructions for setting up PyPI trusted publishing
# for automated package publishing when creating releases.

echo "📦 PyPI Trusted Publishing Setup Instructions"
echo "=============================================="
echo ""
echo "To enable automated PyPI publishing when you create releases, you need to:"
echo ""
echo "1. 🔐 Set up PyPI Trusted Publishing:"
echo "   - Go to https://pypi.org/manage/account/publishing/"
echo "   - Click 'Add a new pending publisher'"
echo "   - Fill in the following details:"
echo "     * PyPI project name: pyflexweb"
echo "     * Owner: Grynn"
echo "     * Repository name: pyflexweb"
echo "     * Workflow filename: publish.yml"
echo "     * Environment name: release"
echo ""
echo "2. 🏷️  Create a release environment on GitHub:"
echo "   - Go to https://github.com/Grynn/pyflexweb/settings/environments"
echo "   - Click 'New environment'"
echo "   - Name it 'release'"
echo "   - Optionally add protection rules (recommended for production)"
echo ""
echo "3. 🚀 Now you can create releases with PyPI publishing:"
echo "   - Run 'make bump-patch' (or bump-minor/bump-major) to update version"
echo "   - Run 'make release' to create a GitHub release"
echo "   - The GitHub Action will automatically publish to PyPI"
echo ""
echo "✅ Once set up, every GitHub release will automatically publish to PyPI!"
echo ""
echo "📋 Useful commands:"
echo "   make bump-patch  # Increment patch version (0.1.1 -> 0.1.2)"
echo "   make bump-minor  # Increment minor version (0.1.1 -> 0.2.0)"
echo "   make bump-major  # Increment major version (0.1.1 -> 1.0.0)"
echo "   make release     # Create GitHub release and trigger PyPI publish"
echo ""
