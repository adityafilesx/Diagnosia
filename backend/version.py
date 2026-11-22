"""The app's version, stored with records that must say which code produced them.

Raise it with each release. A deployment can name its exact build with DIAGNOSIA_APP_VERSION,
for example the commit it runs.
"""
import os

APP_VERSION = os.environ.get("DIAGNOSIA_APP_VERSION", "").strip()[:40] or "0.3.0"
