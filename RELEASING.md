# Releasing

Nowgate releases this package from its own server, which holds its PyPI token.

1. Set the version in `pyproject.toml`, and move `CHANGELOG.md`'s "Unreleased" section under it.
2. On the server, build the wheel and the source archive (flit_core, pinned in
   `requirements-dev.txt`), upload them with twine, and tag the commit `v<version>`.
3. Check the registry: `pip index versions nowgate`.
