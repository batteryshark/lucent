"""lucent — code understanding as a ledgered investigation (a muster consumer).

The second domain built on muster's spine, and the cross-domain proof that the extraction
seam holds. lucent enumerates a Python target's modules, understands each (functions,
classes, methods, imports), and drains that surface to N/N coverage — the same guarantee
muster gives unmask's detection sweep, over an entirely different domain, importing only
`muster` (never unmask).
"""

from __future__ import annotations

__version__ = "0.0.1"

from lucent.graph import LucentConfig
from lucent.run import LucentResult, resume_lucent, run_lucent

__all__ = ["LucentConfig", "LucentResult", "run_lucent", "resume_lucent", "__version__"]
