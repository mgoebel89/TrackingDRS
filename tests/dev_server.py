"""Lokaler Testserver ohne TLS auf 127.0.0.1:<port> (Vorgabe 8461), Daten in .dev-daten im Repo-Ordner.

  python tests/dev_server.py [port]
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("TRACKINGDRS_DATEN", os.path.join(REPO, ".dev-daten"))
os.environ["TRACKINGDRS_OHNE_TLS"] = "1"
os.environ["TRACKINGDRS_BIND"] = "127.0.0.1"
os.environ["TRACKINGDRS_HTTP_PORT"] = sys.argv[1] if len(sys.argv) > 1 else "8461"
sys.path.insert(0, REPO)

from app import server  # noqa: E402  (erst nach den Umgebungsvariablen laden)

server.main()
