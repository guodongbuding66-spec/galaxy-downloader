from __future__ import annotations

"""Compatibility facade for the V1.8 transfer presenter."""

import desktop_transfers_legacy as _legacy
from desktop_aria2_transfer import (
    install_desktop_aria2_transfer_presenter,
    run_desktop_aria2_transfer_self_test,
)

for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals().setdefault(_name, getattr(_legacy, _name))


def install_desktop_transfers(engine_module):
    install_desktop_aria2_transfer_presenter(engine_module, _legacy)
    return _legacy.install_desktop_transfers(engine_module)


def run_desktop_transfers_self_test() -> None:
    _legacy.run_desktop_transfers_self_test()
    run_desktop_aria2_transfer_self_test()
