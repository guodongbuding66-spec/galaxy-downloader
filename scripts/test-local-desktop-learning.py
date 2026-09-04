from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / 'local-engine'
if str(LOCAL_ENGINE) not in sys.path: sys.path.insert(0, str(LOCAL_ENGINE))
from desktop_hooks import registered_after_build_ui_hooks
from desktop_learning import install_desktop_learning, run_desktop_learning_self_test
class FakeWindow: pass
class FakeEngine: EngineWindow = FakeWindow
def run_test():
    install_desktop_learning(FakeEngine)
    assert getattr(FakeWindow,'_galaxy_desktop_learning_installed',False)
    assert registered_after_build_ui_hooks(FakeWindow).count('desktop-learning') == 1
    install_desktop_learning(FakeEngine)
    assert registered_after_build_ui_hooks(FakeWindow).count('desktop-learning') == 1
    run_desktop_learning_self_test()
if __name__ == '__main__': run_test(); print('Desktop Learning self-test passed')
