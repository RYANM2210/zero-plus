"""Build everything needed to run Zero Plus on another machine.

Produces, in dist/:

    zero-plus-offline.html   the app, one file, no install, no network
    zeroplus.pyz             the command line solver, one file, Python 3 only
    zero-plus.zip            both of the above plus examples and full source

    python package.py
"""

import io
import os
import shutil
import subprocess
import sys
import zipapp
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist")
SOLVER = os.path.join(HERE, "solver")

MODULES = ["exact.py", "circuit.py", "mna.py", "analysis.py", "report.py"]

# Inside a zipapp the archive root is on sys.path, so the solver modules sit
# at the top level and keep importing each other by plain name.
MAIN = '''"""Zero Plus: initial and final conditions for switched linear circuits."""

import os
import sys

from analysis import AnalysisError, analyse
from circuit import CircuitError, parse_netlist
from report import render

USAGE = """Zero Plus - initial and final conditions for switched circuits

  python zeroplus.pyz <netlist file>
  python zeroplus.pyz <netlist file> --no-equations
  python zeroplus.pyz -                 read a netlist from standard input

Export a netlist from the drawing tool with its Netlist button, save it to a
file, and pass it here to check the answer in a second place."""


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = set(a for a in argv[1:] if a.startswith("--"))

    if not args or "--help" in flags or "-h" in flags:
        print(USAGE)
        return 0 if args else 2

    path = args[0]
    if path == "-":
        text, title = sys.stdin.read(), "circuit"
    else:
        if not os.path.exists(path):
            print("no such file: %s" % path)
            return 2
        with open(path) as handle:
            text = handle.read()
        title = os.path.splitext(os.path.basename(path))[0]

    try:
        result = analyse(parse_netlist(text, title=title))
    except CircuitError as error:
        print("Problem with the circuit description:\\n  %s" % error)
        return 1
    except AnalysisError as error:
        print("This circuit cannot be solved:\\n  %s" % error)
        return 1

    print(render(result, show_equations="--no-equations" not in flags))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
'''

HOW_TO_RUN = """Zero Plus
=========

Initial conditions, their derivatives, and final conditions for switched
linear circuits, with the working shown.


THE DRAWING TOOL  --  zero-plus-offline.html
--------------------------------------------

Double-click it. That is the whole install.

It is one self-contained file: no internet, no Python, no server. It works
from a memory stick, a Downloads folder, or anywhere else you put it. Any
reasonably recent browser will do.

On a phone or tablet, copy it across and open it from your Files app, or put
it in a cloud drive folder and open it from there.

To use it: pick a part from the left rail, drag across two or more grid
squares to place it. Terminals that touch are connected; drag with Wire to
join things further apart. The small blue numbers are the node numbers the
solver worked out, so check those against your own drawing. Click a part to
set its value, flip its polarity, or delete it. Then press Solve.


THE COMMAND LINE SOLVER  --  zeroplus.pyz
------------------------------------------

Needs Python 3 installed, and nothing else at all.

    python zeroplus.pyz examples/lecture-example.net

The point of having two versions is that you can check one against the other.
Press Netlist in the drawing tool, save the text to a file, and run it through
this. The two are separate implementations that are tested against each other,
so if they agree, the answer is sound.


EXAMPLES
--------

    examples/lecture-example.net   parallel RLC, 4u(t) A step plus a 6 A source
    examples/series-rlc.net        12u(t) V into a series RLC
    examples/switch-opens.net      an opening switch stranding an inductor
    examples/inverting-opamp.net   ideal op-amp, gain -5


SOURCE
------

Everything is in source/, including the tests. From that folder:

    python run_tests.py       run the tests, including the cross-check
    python build.py           rebuild the HTML after editing web/
    python package.py         rebuild this bundle

If you change the solver, change it in BOTH source/solver/ (Python) and
source/web/solver.js (JavaScript). They are deliberate ports of each other and
the tests compare them value by value; that agreement is why the answers can
be trusted.

README.md has the method, the sign conventions, the netlist format, and the
limits worth knowing.
"""

EXAMPLES = {
    "lecture-example.net": """.title Parallel RLC driven by a step and a DC source
R1 1 2 5
C1 1 0 1/5
L1 2 0 2
I1 0 1 step 4
I2 0 2 dc 6
""",
    "series-rlc.net": """.title Series RLC with a 12u(t) V source
V1 1 0 step 12
R1 1 2 4
L1 2 3 1
C1 3 0 1/4
""",
    "switch-opens.net": """.title Switch opens and strands the inductor current
V1 1 0 dc 10
R1 1 2 5
SW1 2 3 closed open
L1 3 0 2
R2 3 0 20
""",
    "inverting-opamp.net": """.title Ideal inverting amplifier, gain -5
V1 1 0 dc 2
R1 1 2 1k
R2 2 3 5k
OP1 0 2 3
""",
}

SOURCE_TREE = [
    "README.md", "solve.py", "run_tests.py", "build.py", "package.py",
    "fetch_fonts.py", ".gitignore",
    "solver/exact.py", "solver/circuit.py", "solver/mna.py",
    "solver/analysis.py", "solver/report.py",
    "web/index.html", "web/style.css", "web/solver.js", "web/app.js",
    "web/fonts.css",
    "tests/test_cases.py", "tests/crosscheck.py", "tests/dump.py",
    "tests/dump.js", "tests/fuzz.py", "tests/ex2.net",
]


def build_pyz():
    staging = os.path.join(DIST, "_pyz")
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging)

    for name in MODULES:
        shutil.copy(os.path.join(SOLVER, name), os.path.join(staging, name))
    with io.open(os.path.join(staging, "__main__.py"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write(MAIN)

    target = os.path.join(DIST, "zeroplus.pyz")
    zipapp.create_archive(staging, target, interpreter="/usr/bin/env python3")
    shutil.rmtree(staging)
    return target


def main():
    if not os.path.isdir(DIST):
        os.mkdir(DIST)

    subprocess.check_call([sys.executable, os.path.join(HERE, "build.py")])
    print()

    pyz = build_pyz()
    print("dist/zeroplus.pyz            %6.0f KB   command line, Python 3 only"
          % (os.path.getsize(pyz) / 1024.0))

    examples_dir = os.path.join(DIST, "examples")
    if not os.path.isdir(examples_dir):
        os.mkdir(examples_dir)
    for name, text in EXAMPLES.items():
        with io.open(os.path.join(examples_dir, name), "w",
                     encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    bundle = os.path.join(DIST, "zero-plus.zip")
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("HOW-TO-RUN.txt", HOW_TO_RUN)
        archive.write(os.path.join(DIST, "zero-plus-offline.html"),
                      "zero-plus-offline.html")
        archive.write(pyz, "zeroplus.pyz")
        for name, text in EXAMPLES.items():
            archive.writestr("examples/" + name, text)
        missing = []
        for relative in SOURCE_TREE:
            source = os.path.join(HERE, relative)
            if os.path.exists(source):
                archive.write(source, "source/" + relative)
            else:
                missing.append(relative)

    print("dist/zero-plus.zip           %6.0f KB   everything, ready to hand over"
          % (os.path.getsize(bundle) / 1024.0))
    if missing:
        print("\nnote: not found, so left out of the bundle: %s" % ", ".join(missing))


if __name__ == "__main__":
    main()
