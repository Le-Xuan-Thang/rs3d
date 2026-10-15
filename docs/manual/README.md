# RS3D manuals

Two LaTeX manuals, built with XeLaTeX and KOMA-Script:

| Manual | Source | PDF |
|---|---|---|
| **RS3D User's Guide** (how to use the app) | `user-guide/` | `docs/RS3D_Users_Guide.pdf` |
| **RS3D Theory and Algorithms Manual** (how each function works) | `theory/` | `docs/RS3D_Theory_Manual.pdf` |

Shared style: `common/rs3d.sty`. Bibliography: `common/refs.bib`.

## Build

Needs XeLaTeX, `latexmk`, `biber` and Pygments (`pygmentize`; the `minted2` package calls it).

```bash
cd docs/manual
make            # both manuals -> docs/RS3D_*.pdf
make guide      # user's guide only
make theory     # theory manual only
make clean      # remove build/
```

## Regenerate the figures

Every figure comes from code, so the manuals never drift from the application.

```bash
cd rs3d-app && uv sync          # once
make -C ../docs/manual figures  # theory-manual plots (matplotlib, calls the app's own functions)
uv run python ../docs/manual/scripts/make_screenshots.py   # user-guide screenshots (Playwright + Google Chrome)
```

* `scripts/demo_data.py` builds the seeded synthetic day (station `AM.DEMO1.00`: noise, a local and a distant
  earthquake, two noise bursts, two gaps) used by both manuals. Nothing from a real station is committed.
* `scripts/make_figures.py` writes `figures/theory-*.pdf` and the generated tables `figures/*.tex`.
* `scripts/screenshot_app.py` runs the real app against a fake Shake; `scripts/make_screenshots.py` drives it with
  Playwright, saves `figures/ug-*.png`, and measures every control's position into `figures/ug-callouts.tex` so the
  numbered markers in the guide always sit on the right control.
* Run these from `rs3d-app` (not from this folder) so `uv` uses the application's environment.

## Notes

* `minted2` is used instead of `minted` 3 because `latexminted` fails on Python 3.14.
* The alert chapter of the theory manual (Section 10.9) is a design proposal; the user guide has no alert chapter yet.
