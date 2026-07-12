"""The observation-atom catalog — lucent's judgment-free behavior vocabulary.

Adapted from the parallax ontology: an *atom* records a mechanical fact about what code
can do (``EXEC.SHELL`` = "invokes a shell subprocess"), never a verdict. lucent observes
atoms from source across every language its extractor can parse, and the lenses
(``lens.py``) supply the judgment on top — capability is not accusation.

This module is pure data: the category names and the per-atom title/description the report
and lenses cite. The *detection* — which call sites map to which atom — lives in the
vendored parallax signature pack (``signatures/source-callees.json``), loaded by
``signatures.py``. Keeping the fact of an atom separate from how it is spotted is parallax's
own split: the packs are data, the scanner owns mechanics.

The catalog is kept in sync with the atoms the vendored callee pack actually emits, so
every observed atom renders with a real title; :func:`atom_title` degrades gracefully to
the raw id for anything uncatalogued (e.g. a newer pack).
"""

from __future__ import annotations

#: Atom categories, by the parallax code. Names are mechanical and lens-neutral by design:
#: a category says what a behavior IS, not whether it is good or bad ("transformation",
#: not "obfuscation"; "system inspection", not "reconnaissance").
CATEGORIES: dict[str, str] = {
    "EXEC": "Code Execution",
    "NETW": "Network Communication",
    "FSYS": "Filesystem Operations",
    "LOAD": "Dynamic Code Loading",
    "XFRM": "Data & Code Transformation",
    "CRED": "Credential Access",
    "ENVI": "Environment Interaction",
    "SYSI": "System Inspection",
    "PKGM": "Package & Build Operations",
    "CRPT": "Cryptographic Operations",
    "RSRC": "Resource & Concurrency",
    "TIME": "Temporal Operations",
}

#: The atoms lucent observes, ``id -> (title, description)``. This is exactly the vocabulary
#: the vendored ``parallax.source-callees`` callee pack emits: the judgment-free, multi-
#: language "what can this code reach out and do?" surface. (The MCD-flavoured content pack —
#: sandbox evasion, persistence, credential theft — is deliberately not vendored: lucent
#: describes a codebase, it does not accuse one.)
ATOMS: dict[str, tuple[str, str]] = {
    "EXEC.PROC": ("Process execution",
                  "Spawns a subprocess or replaces the process image (subprocess.run/Popen, "
                  "os.exec*, fork, ProcessBuilder, exec.Command)."),
    "EXEC.SHELL": ("Shell command execution",
                   "Runs a command string through a shell (os.system, popen, shell_exec, "
                   "Start-Process)."),
    "NETW.HTTP": ("HTTP request",
                  "Makes an outbound HTTP(S) request (urllib, requests, httpx, aiohttp, "
                  "HttpClient, fetch, curl/wget)."),
    "NETW.SOCKET": ("Raw socket",
                    "Opens a raw network socket or resolves a host (socket, create_connection, "
                    "net.Dial, getaddrinfo)."),
    "NETW.WS": ("WebSocket",
                "Opens a WebSocket connection for bidirectional streaming."),
    "FSYS.READ": ("Filesystem read",
                  "Reads files from disk (open/fopen, read_text, readFile, slurp)."),
    "FSYS.WRITE": ("Filesystem write",
                   "Writes, moves, or changes files on disk (write_text, writeFile, "
                   "shutil.copy/move, os.rename, chmod)."),
    "FSYS.DELETE": ("Filesystem delete",
                    "Removes files or directory trees (os.remove/unlink, rm, rmtree)."),
    "LOAD.EVAL": ("Dynamic code evaluation",
                  "Evaluates or compiles code from a string at runtime (eval, exec, compile, "
                  "Function, Invoke-Expression)."),
    "LOAD.IMPORT": ("Dynamic import / library load",
                    "Loads a module or native library chosen at runtime (importlib, __import__, "
                    "dlopen, LoadLibrary, Class.forName)."),
    "LOAD.DESER": ("Untrusted deserialization",
                   "Reconstructs objects from a serialized stream that can execute code "
                   "(pickle, marshal, yaml.load, readObject, unserialize)."),
    "XFRM.ENCODE": ("Encoding / decoding",
                    "Encodes or decodes a byte stream (base64, hex, atob/btoa)."),
    "XFRM.ENCRYPT": ("Encryption / decryption",
                     "Encrypts or decrypts data at a call site."),
    # -- lucent Python-idioms supplement -----------------------------------
    "NETW.LISTEN": ("Network listener",
                    "Binds and listens for inbound connections — a server surface "
                    "(socketserver, http.server, asyncio.start_server)."),
    "ENVI.VAR": ("Environment configuration",
                 "Reads an environment variable, so behaviour depends on the environment "
                 "(os.getenv, os.environ)."),
    "CRED.STORE": ("Credential store access",
                   "Reads a credential store (keyring, netrc)."),
    "CRPT.HASH": ("Hashing",
                  "Computes a cryptographic or non-cryptographic digest (hashlib, hmac)."),
    "RSRC.THREAD": ("Concurrency",
                    "Starts threads, processes, or async tasks (threading, multiprocessing, "
                    "concurrent.futures, asyncio)."),
    "TIME.SLEEP": ("Delay",
                   "Sleeps or delays execution (time.sleep, asyncio.sleep)."),
}


def category_of(atom: str) -> str:
    """The category code for an atom id (``EXEC.SHELL`` -> ``EXEC``)."""
    return atom.split(".", 1)[0]


def category_title(atom: str) -> str:
    """Human-readable category name for an atom id, or the raw code if unknown."""
    return CATEGORIES.get(category_of(atom), category_of(atom))


def atom_title(atom: str) -> str:
    """Human-readable title for an atom id, or the id itself if uncatalogued."""
    entry = ATOMS.get(atom)
    return entry[0] if entry else atom


def atom_description(atom: str) -> str:
    entry = ATOMS.get(atom)
    return entry[1] if entry else ""
