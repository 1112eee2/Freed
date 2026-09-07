"""Thai Makhos Web GUI Launcher.

Run this script directly with:
    python server.py
or
    python server.py --port 8000
"""

import os
import sys

# Ensure current working directory is added to sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from makhos.server import run_server

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Thai Makhos Web GUI Launcher")
    parser.add_argument("--port", type=int, default=8000, help="HTTP server port (default 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()

    run_server(port=args.port, open_browser=not args.no_browser)
