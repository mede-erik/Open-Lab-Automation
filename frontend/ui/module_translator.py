# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Translations for the dialogs of a measurement module.

The application's own catalogs (``frontend/lang/<lang>.json``) are shared with other parts of the
program. A measurement module keeps its strings in its own folder instead,
``frontend/lang/modules/<module>/<lang>.json``, so adding or changing them never touches the shared
files. ``CatalogTranslator.t(key)`` looks the key up in the module catalog of the current language,
then in the English one, then in the application's translator, and finally returns the key.
"""

import json
import os
from typing import Any, Dict, Optional

LANG_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lang", "modules"
)
FALLBACK_LANG = "en"


def load_catalog(module: str, lang: str, root: str = LANG_ROOT) -> Dict[str, str]:
    """The catalog of ``module`` in ``lang`` (empty if there is none or it is unreadable)."""
    try:
        with open(os.path.join(root, module, f"{lang}.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


class CatalogTranslator:
    """Looks strings up in a module's catalogs, then in English, then in the base translator."""

    def __init__(
        self,
        module: str,
        base: Optional[Any] = None,
        lang: Optional[str] = None,
        root: str = LANG_ROOT,
    ):
        """``base`` is the application's ``Translator`` (anything with ``t(key)`` and, optionally,
        ``current_lang``); ``lang`` overrides the language taken from it."""
        self.module, self.base, self.root = module, base, root
        self.lang = lang or getattr(base, "current_lang", None) or FALLBACK_LANG
        self._catalog = load_catalog(module, self.lang, root)
        self._fallback = load_catalog(module, FALLBACK_LANG, root)

    def set_language(self, lang: str) -> None:
        """Switch language (the catalog is read again)."""
        self.lang = lang
        self._catalog = load_catalog(self.module, lang, self.root)

    def t(self, key: str, **values: Any) -> str:
        """The translated text for ``key``; ``{name}`` placeholders are filled from ``values``."""
        text = self._catalog.get(key) or self._fallback.get(key)
        if text is None and self.base is not None:
            found = self.base.t(key)
            text = found if found != key else None
        if text is None:
            return key
        try:
            return text.format(**values) if values else text
        except (KeyError, IndexError, ValueError):
            return text
