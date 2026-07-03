"""Scoperta automatica dei moduli.

Scorre i sotto-pacchetti di `modules/`, importa il loro `module.py` e
istanzia ogni sottoclasse di `ToolModule` trovata. Niente registrazioni
manuali: aggiungi una cartella e il modulo compare.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil

import modules
from core.context import AppContext
from core.module_base import ToolModule


def discover_modules(context: AppContext) -> list[ToolModule]:
    found: dict[str, ToolModule] = {}

    for info in pkgutil.iter_modules(modules.__path__, modules.__name__ + "."):
        if not info.ispkg:
            continue
        # Convenzione: la classe del modulo sta in `<pacchetto>.module`
        try:
            submodule = importlib.import_module(info.name + ".module")
        except ModuleNotFoundError:
            continue

        for _, obj in inspect.getmembers(submodule, inspect.isclass):
            is_module = (
                issubclass(obj, ToolModule)
                and obj is not ToolModule
                and obj.__module__ == submodule.__name__
            )
            if is_module:
                instance = obj(context)
                found[instance.id or obj.__name__] = instance

    return list(found.values())
