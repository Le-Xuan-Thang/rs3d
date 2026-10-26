"""Desktop entry point: the same app in its own window. Also the entry of the packaged Windows build."""

from __future__ import annotations

import multiprocessing


def main() -> None:
    multiprocessing.freeze_support()  # NiceGUI's native window runs in a child process; required in a frozen exe
    from rs3d.cli import main as cli_main

    cli_main(["--native"])


if __name__ in {"__main__", "__mp_main__"}:
    main()
