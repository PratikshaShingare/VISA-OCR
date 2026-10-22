"""
Local development server for Khanna Travels & Holidays (used by
"Start Frontend.bat"). Identical to `python -m http.server <port>` (same
folder, same port, same listening address) except that it tells the browser
never to cache anything — so after any update to the app's HTML/CSS/JS, a
normal refresh always shows the current version instead of a stale copy.

Usage:  python serve_nocache.py [port]      (default 8766)
"""
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    print(f"Serving HTTP (no-cache) on port {port} ...")
    ThreadingHTTPServer(("", port), NoCacheHandler).serve_forever()
