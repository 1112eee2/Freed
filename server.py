"""Freed (Thai Makhos engine) Web GUI Launcher.

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
    parser = argparse.ArgumentParser(description="Freed Web GUI Launcher")
    parser.add_argument("--port", type=int, default=8000, help="HTTP server port (default 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    parser.add_argument("--release-pointer", help="GUI release selection JSON")
    parser.add_argument("--release-profile", choices=["nnue", "hce"], help="Select the release evaluator (HCE rollback)")
    parser.add_argument("--native-library", help="Explicit native DLL instead of the release")
    parser.add_argument("--nnue-model", help="Explicit NNUE model")
    args = parser.parse_args()

    try:
        run_server(port=args.port, open_browser=not args.no_browser,
                   native_library=args.native_library, nnue_model=args.nnue_model,
                   release_pointer=args.release_pointer, release_profile=args.release_profile)
    except (OSError, ValueError) as error:
        print(f"Cannot start Freed: {error}", file=sys.stderr)
        if getattr(sys, "frozen", False):
            input("Press Enter to exit.")
        sys.exit(1)
