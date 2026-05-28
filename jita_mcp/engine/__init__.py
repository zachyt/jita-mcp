"""Dogma / fitting engine wrapper.

Wraps the chosen calculation engine (currently undecided: vendored Pyfa eos, forked
standalone eos, or a custom dogma evaluator) behind a stable interface so tool code
doesn't depend on the engine choice.
"""
