"""Command line front end.

    python solve.py tests/ex2.net
    python solve.py tests/ex2.net --no-equations
    python solve.py -            (read a netlist from stdin)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "solver"))

from analysis import AnalysisError, analyse
from circuit import CircuitError, parse_netlist
from report import render


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}

    if not args:
        print(__doc__)
        return 2

    path = args[0]
    if path == "-":
        text, title = sys.stdin.read(), "circuit"
    else:
        if not os.path.exists(path):
            print("no such file: %s" % path)
            return 2
        text = open(path).read()
        title = os.path.splitext(os.path.basename(path))[0]

    try:
        circuit = parse_netlist(text, title=title)
        result = analyse(circuit)
    except CircuitError as error:
        print("Problem with the circuit description:\n  %s" % error)
        return 1
    except AnalysisError as error:
        print("This circuit cannot be solved:\n  %s" % error)
        return 1

    print(render(result, show_equations="--no-equations" not in flags))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
