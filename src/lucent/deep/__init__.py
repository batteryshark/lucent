"""Optional deep code-understanding providers.

The deterministic Lucent index is always primary. Providers in this package consume that
index after it is complete and may add bounded evidence; they never participate in Lucent's
coverage predicate.
"""

from lucent.deep.joern import RekitJoernRunner, context_for_module, run_joern_provider

__all__ = ["RekitJoernRunner", "context_for_module", "run_joern_provider"]
