"""Optional desktop entry point; the CLI never imports Qt."""

import sys


def main() -> int:
    try:
        from .desktop import launch
    except ImportError:
        print("Desktop requires policy-admitted PySide6-Essentials and matched shiboken6. See DEPENDENCY_POLICY.md.", file=sys.stderr)
        return 3
    return launch()