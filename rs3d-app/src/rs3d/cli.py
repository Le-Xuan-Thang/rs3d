"""`rs3d-app` command."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="rs3d-app", description="Raspberry Shake 3D status, live view and data export")
    parser.add_argument("--port", type=int, default=None, help="web port (default 8765, or a free one)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    parser.add_argument("--native", action="store_true", help="open in its own desktop window (needs the 'desktop' extra)")
    args = parser.parse_args(argv)

    from rs3d.app.main import run

    run(port=args.port, show=not args.no_browser and not args.native, native=args.native)


if __name__ in {"__main__", "__mp_main__"}:
    main()
