"""Shared pytest setup: the Qt tests run without a screen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
