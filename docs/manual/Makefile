# Build the RS3D manuals.  Needs XeLaTeX, latexmk, biber and Pygments (for minted).
#   make            build both manuals into docs/RS3D_*.pdf
#   make guide      user's guide only      make theory     theory manual only
#   make figures    regenerate figures/ (needs `uv sync` in ../../rs3d-app, plus Chrome for the screenshots)
#   make clean      remove build output
LATEXMK = latexmk -xelatex -shell-escape -interaction=nonstopmode -halt-on-error
COMMON  = $(abspath common)

.PHONY: all guide theory figures clean
all: guide theory

guide:
	mkdir -p build/guide
	cd user-guide && TEXINPUTS=$(COMMON)//: $(LATEXMK) -outdir=../build/guide main.tex
	cp build/guide/main.pdf ../RS3D_Users_Guide.pdf

theory:
	mkdir -p build/theory
	cd theory && TEXINPUTS=$(COMMON)//: $(LATEXMK) -outdir=../build/theory main.tex
	cp build/theory/main.pdf ../RS3D_Theory_Manual.pdf

figures:
	cd ../../rs3d-app && uv run python ../docs/manual/scripts/make_figures.py

clean:
	rm -rf build
