"""Compare the Python and JavaScript solvers value by value.

Both must produce the same exact fraction for every node voltage and every
branch quantity, in every phase, for every circuit in the corpus.  This is what
makes the web page trustworthy: it is not a second implementation that happens
to look right, it is one that agrees exactly with the tested one.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def walk(prefix, value, out):
    if isinstance(value, dict):
        for key in sorted(value):
            walk(prefix + "/" + str(key), value[key], out)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            walk("%s[%d]" % (prefix, index), item, out)
    else:
        out[prefix] = value


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else None
    suffix = ("_" + name) if name else ""
    extra = [name] if name else []
    subprocess.check_call([sys.executable, os.path.join(HERE, "dump.py")] + extra)
    subprocess.check_call(["node", os.path.join(HERE, "dump.js")] + extra)

    with open(os.path.join(HERE, "results_python%s.json" % suffix)) as handle:
        python_results = json.load(handle)
    with open(os.path.join(HERE, "results_js%s.json" % suffix)) as handle:
        js_results = json.load(handle)

    flat_python, flat_js = {}, {}
    walk("", python_results, flat_python)
    walk("", js_results, flat_js)

    keys = sorted(set(flat_python) | set(flat_js))
    mismatches = []
    for key in keys:
        left = flat_python.get(key, "<missing in python>")
        right = flat_js.get(key, "<missing in js>")
        if left != right:
            mismatches.append((key, left, right))

    print("compared %d values across %d circuits"
          % (len(keys), len(set(python_results) | set(js_results))))
    if mismatches:
        print("\nMISMATCHES (%d):" % len(mismatches))
        for key, left, right in mismatches[:40]:
            print("  %s\n      python: %s\n      js:     %s" % (key, left, right))
        if len(mismatches) > 40:
            print("  ... and %d more" % (len(mismatches) - 40))
        return 1
    print("the two solvers agree exactly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
