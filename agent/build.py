"""PyInstaller build script for the SCC agent.

Run from the agent/ directory after `pip install -e ".[dev]"`. Outputs
``dist/scc-agent.exe``.
"""
from __future__ import annotations

import pathlib
import sys


def main() -> int:
    import PyInstaller.__main__  # imported lazily so non-Windows tooling can still import this module

    here = pathlib.Path(__file__).resolve().parent
    args = [
        str(here / "scc_agent" / "__main__.py"),
        "--name=scc-agent",
        "--onefile",
        "--console",
        f"--distpath={here / 'dist'}",
        f"--workpath={here / 'build'}",
        f"--specpath={here}",
        "--hidden-import=win32timezone",
        "--collect-submodules=watchdog",
    ]
    icon = here / "installer" / "icon.ico"
    if icon.exists():
        args.append(f"--icon={icon}")
    version_file = here / "installer" / "version.txt"
    if version_file.exists():
        args.append(f"--version-file={version_file}")
    PyInstaller.__main__.run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
