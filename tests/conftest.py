"""
Keeps the suite out of the production log: backend/logging_config.py
opens backend/logs/backend.log at import, and every test that imports
backend.main would otherwise leave its fake agents' TTS warnings there for
an operator to misread. The override must be in place before that first
import, hence at conftest import time.

(It used to also write every run's results into docs/boarding.html; that page
is now a feature guide and carries no test results.)
"""
import os
import tempfile

os.environ.setdefault("LAS_BACKEND_LOG_DIR", tempfile.mkdtemp(prefix="las-backend-test-logs-"))
# Importing backend/main.py must not start fetching GitHub in the background (backend/updates.py).
os.environ.setdefault("LAS_NO_UPDATE_CHECK", "1")
os.environ.setdefault("LAS_NO_WIDGET_WATCHDOG", "1")  # importing backend/main.py must never reopen the real widget
