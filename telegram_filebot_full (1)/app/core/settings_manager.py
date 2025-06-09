import json
import os
from typing import Any

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "settings.json")

class SettingsManager:
    _cache: dict[str, Any] | None = None

    @classmethod
    def load(cls) -> dict[str, Any]:
        if cls._cache is None:
            try:
                with open(SETTINGS_PATH, "r") as f:
                    cls._cache = json.load(f)
            except FileNotFoundError:
                cls._cache = {}
        return cls._cache

    @classmethod
    def save(cls, data: dict[str, Any]) -> None:
        cls._cache = data
        with open(SETTINGS_PATH, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def update(cls, updates: dict[str, Any]) -> dict[str, Any]:
        settings = cls.load()
        settings.update(updates)
        cls.save(settings)
        return settings
