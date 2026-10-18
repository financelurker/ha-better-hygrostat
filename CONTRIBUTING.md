# Contributing

Thanks for helping out! Bug reports and pull requests are welcome.

- `main` is protected: work on a branch and open a pull request.
- Add or update tests for every change. They run in a real Home Assistant test instance; `tests/helpers.py` has the room setup and a time helper.
- Run `ruff check .`, `ruff format --check .` and `pytest` before opening a pull request.
- Keep the keys that existing installations depend on: domain, unique ids, storage key and option keys (`tests/test_compat.py` guards them). Changing one turns an update into a new installation.
- Home Keeper stays optional: talk to it only through its services and events, never by importing it.
- New user-facing texts go into both `translations/en.json` and `translations/de.json`.
- If a change alters what the README screenshots show, retake them (`scripts/screenshots/README.md`).
- The brand icon is generated from `scripts/brand/icon.svg`; change the SVG and re-render (`scripts/brand/README.md`), don't edit the PNGs.

Versions: the GitHub release tag is the only source of the version (see "Releases" in the README). `manifest.json` keeps the placeholder `0.0.0`; don't change it, and don't write the version anywhere else. Code that needs the version reads it from the loaded integration.

By contributing you agree that your contribution is licensed under the Apache License 2.0.
