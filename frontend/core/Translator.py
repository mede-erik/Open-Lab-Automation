import os
import json

class Translator:
    """
    Handles application translations using JSON language files.
    Loads available languages from the lang directory and provides translation lookup.
    """
    def __init__(self, lang_dir=None, default_lang='en'):
        """
        Initialize the Translator.
        :param lang_dir: Directory containing language JSON files.
        :param default_lang: Default language code.
        """
        if lang_dir is None:
            # Absolute path to the lang folder inside frontend (parent directory of core)
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            lang_dir = os.path.join(base_dir, 'lang')
        self.lang_dir = lang_dir
        self.translations = {}
        self.current_lang = default_lang
        self.load_languages()
        self.set_language(default_lang)

    def load_languages(self):
        """
        Load available languages from the language directory.
        """
        self.available_langs = []
        if not os.path.exists(self.lang_dir):
            os.makedirs(self.lang_dir)
        for fname in os.listdir(self.lang_dir):
            if fname.endswith('.json'):
                lang = fname[:-5]
                self.available_langs.append(lang)

    def set_language(self, lang):
        """
        Set the current language and load its translations.
        :param lang: Language code to set.
        """
        try:
            with open(os.path.join(self.lang_dir, f'{lang}.json'), encoding='utf-8') as f:
                self.translations = json.load(f)
            self.current_lang = lang
        except Exception:
            self.translations = {}
            self.current_lang = lang

    def t(self, key):
        """
        Translate a key using the current language.
        :param key: The translation key.
        :return: Translated string or the key if not found.
        """
        return self.translations.get(key, key)
