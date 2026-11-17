# Releasing

1. Set the version in `pyproject.toml`, and move `CHANGELOG.md`'s
   "Unreleased" section under it.
2. Push a tag `v<version>` on that commit. The **Release** workflow checks the tag against the
   version, runs the tests, and publishes `nowgate` to PyPI (the repository secret
   `PYPI_API_TOKEN`).
3. Check the registry: `pip index versions nowgate`.
