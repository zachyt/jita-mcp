"""Shadow shim for pyfa's root-level modules.

Added to sys.path *before* vendor/pyfa/ so eos picks these up instead of pyfa's
own root config (which transitively pulls in wx, the GUI toolkit). Only modules
eos actually touches need to live here.
"""
