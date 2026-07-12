"""Single source of the package version.

Kept as a leaf module so ``assess`` can read the version without importing the top-level
``lucent`` package. A top-level import would form a module-level cycle
(``assess`` -> ``__init__`` -> ``graph`` -> ``assess``).
"""

from __future__ import annotations

__version__ = "0.1.0"
