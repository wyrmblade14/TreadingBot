"""
Launch the TreadingBot Streamlit dashboard.

Usage:
    python scripts/run_dashboard.py
    python scripts/run_dashboard.py --port 8502
    python scripts/run_dashboard.py --no-browser

This is a thin wrapper around `streamlit run` that sets the correct
working directory and passes useful defaults.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Project root
ROOT = Path(__file__).parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch TreadingBot dashboard")
    parser.add_argument("--port",       default=8501, type=int, help="Port to serve on (default: 8501)")
    parser.add_argument("--no-browser", action="store_true",    help="Don't open browser automatically")
    args = parser.parse_args()

    app_path = ROOT / "dashboard" / "app.py"

    cmd = [
        sys.executable, "-m", "streamlit", "run",
        str(app_path),
        "--server.port", str(args.port),
        "--server.headless", str(args.no_browser).lower(),
        "--browser.gatherUsageStats", "false",
    ]

    print(f"\nStarting TreadingBot dashboard on http://localhost:{args.port}")
    print("Press Ctrl+C to stop.\n")

    subprocess.run(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    main()
