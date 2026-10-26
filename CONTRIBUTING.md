# Contributing

Thanks for helping. This project is licensed under GPL-3.0-or-later; by contributing you agree your work is released
under the same licence.

## Workflow

1. Open an issue first for anything bigger than a small fix, so we agree on the idea before you write code.
2. Fork, then branch from `main`: `feat/short-name`, `fix/short-name` or `docs/short-name`.
3. Work test-first: write the failing test, see it fail for the right reason, then implement.
4. Open a pull request into `main`. `main` is protected: no direct pushes, CI must pass, and one review is required.
   Pull requests are squash-merged.

## Setup and checks

```bash
cd rs3d-app
uv sync
uv run python -m pytest            # unit and page tests, no Shake needed
uv run python -m pytest -m e2e     # real-browser tests (needs Google Chrome)
```

## Conventions

* Commit messages follow `type(scope): summary`, for example `feat(rs3d-app): ...` or `fix(rs3d-app): ...`.
* All user-facing text goes in `rs3d-app/src/rs3d/help/en.toml`, never inline in a page.
* `core/` must not import anything from `app/` or NiceGUI.
* Any change a user could notice gets a line under **Unreleased** in `CHANGELOG.md`, in the same pull request.
* Do not commit data files, passwords or real Shake addresses. Use synthetic signals in tests.

## Releases (maintainer)

Update `CHANGELOG.md` and the version in `rs3d-app/pyproject.toml`, merge to `main`, then tag `vX.Y.Z`. The
`Build Windows` workflow builds the portable zip and installer and attaches them to a GitHub Release.

## Reporting security problems

See [SECURITY.md](SECURITY.md). Do not open a public issue for them.
