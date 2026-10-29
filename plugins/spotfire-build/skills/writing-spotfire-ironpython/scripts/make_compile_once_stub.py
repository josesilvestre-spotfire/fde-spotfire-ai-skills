"""Wrap a Spotfire IronPython script in a compile-once stub.

Spotfire prepares a stored IronPython script again on every run. For a
large script that costs about 1 s per 250 KB, even when the script does
nothing (measured in Spotfire Analyst 15.0). The stub keeps the code as a
string literal, compiles it once per Analyst session, caches the compiled
code object in the .NET AppDomain and runs it from there. A trigger script
fell from about 650 ms to about 50 ms this way.

The stub copies every global the script receives (Document, Application and
the script parameters) into the namespace the cached code runs in, so the
wrapped script needs no change. The cache key holds the script name, the
code length and its hash, so a new version of the code is compiled again.

Usage:
  python make_compile_once_stub.py "Script Name" script.py > stub.py
  python make_compile_once_stub.py --self-test

Paste or store stub.py as the document script. Keep script.py as the source
you edit; regenerate the stub after every change.
"""

import sys

STUB_TAIL = '''
from System import AppDomain
_DOMAIN = AppDomain.CurrentDomain
_KEY = "compiled-script.%s.%d.%d" % (_NAME, len(_CODE), hash(_CODE))
_COMPILED = _DOMAIN.GetData(_KEY)
if _COMPILED is None:
    _COMPILED = compile(_CODE, _NAME, "exec")
    _DOMAIN.SetData(_KEY, _COMPILED)
_GLOBALS = {"__name__": "__main__"}
for _n, _v in list(globals().items()):
    if not _n.startswith("_") and _n != "AppDomain":
        _GLOBALS[_n] = _v
exec(_COMPILED, _GLOBALS)
'''


def make_stub(name, code):
    """The stub text for script `name` with source `code`."""
    if "\t" in code:
        raise ValueError("the script contains tab characters; use spaces")
    header = ("# %s: the script code is kept as text and compiled once per\n"
              "# Analyst session, so a click does not prepare it again.\n"
              "# Edit the source file and regenerate this stub.\n" % name)
    return (header + "_NAME = " + repr(name) + "\n_CODE = " + repr(code)
            + "\n" + STUB_TAIL)


def self_test():
    """Run a stub twice under CPython with a stand-in for System.AppDomain."""
    import types

    store = {}

    class Domain(object):
        def GetData(self, key):
            return store.get(key)

        def SetData(self, key, value):
            store[key] = value

    class AppDomainStandIn(object):
        CurrentDomain = Domain()

    system = types.ModuleType("System")
    system.AppDomain = AppDomainStandIn
    saved = sys.modules.get("System")
    sys.modules["System"] = system
    try:
        code = ("results.append(threshold * 2)\n"
                "Document['StatusMessage'] = 'done %d' % len(results)\n")
        stub = make_stub("Double Threshold", code)
        compile(stub, "stub", "exec")
        document, results = {}, []
        for _ in range(2):
            exec(stub, {"Document": document, "threshold": 21,
                        "results": results})
        assert results == [42, 42], results
        assert document["StatusMessage"] == "done 2", document
        assert len(store) == 1, store
    finally:
        if saved is None:
            del sys.modules["System"]
        else:
            sys.modules["System"] = saved
    print("self-test passed")
    return 0


def main(argv):
    if argv and argv[0] == "--self-test":
        return self_test()
    if len(argv) != 2:
        print(__doc__)
        return 2
    name, path = argv
    with open(path, encoding="utf-8") as f:
        code = f.read()
    sys.stdout.write(make_stub(name, code))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
