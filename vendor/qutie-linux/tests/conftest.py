import atexit
import os
import shutil
import sys
import tempfile

# Qt tests run without a display
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Never touch the real user configuration: QSettings (saved printer etc.) lives under XDG_CONFIG_HOME.
_CONFIG = tempfile.mkdtemp(prefix="qutie-test-config-")
os.environ["XDG_CONFIG_HOME"] = _CONFIG
atexit.register(shutil.rmtree, _CONFIG, ignore_errors=True)

sys.path.insert(0, os.path.dirname(__file__))
