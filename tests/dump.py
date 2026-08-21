"""Emit every solved quantity for the whole test corpus, as exact n/d strings.

Paired with dump.js, which does the same through the JavaScript solver.  Any
disagreement between the two files is a porting bug.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "solver"))
sys.path.insert(0, HERE)

from analysis import AnalysisError, analyse
from circuit import CircuitError, parse_netlist
from test_cases import CASES, FAILURES

PHASES = ["t<0", "0+", "d/dt", "inf"]


def exact(value):
    return "%d/%d" % (value.numerator, value.denominator)


def dump_one(netlist):
    try:
        circuit = parse_netlist(netlist)
        result = analyse(circuit)
    except (CircuitError, AnalysisError) as error:
        return {"error": type(error).__name__}

    out = {"phases": {}, "notes": len(result.notes), "error": None,
           "ics": {name: exact(value)
                   for name, value in result.initial_conditions.items()}}
    for key in PHASES:
        phase = result.phases.get(key)
        if phase is None:
            out["phases"][key] = None
            continue
        entry = {"nodes": {}, "elements": {}}
        for node in circuit.nodes:
            entry["nodes"][node] = exact(phase.solution.node_voltage(node))
        for element in circuit.elements:
            entry["elements"][element.name] = {
                "v": exact(phase.solution.element_voltage(element)),
                "i": exact(phase.solution.element_current(element)),
            }
        out["phases"][key] = entry
    return out


def main():
    if len(sys.argv) > 1:
        name = sys.argv[1]
        with open(os.path.join(HERE, "corpus_%s.json" % name)) as handle:
            corpus = json.load(handle)
        results = {k: dump_one(v) for k, v in corpus.items()}
        with open(os.path.join(HERE, "results_python_%s.json" % name), "w") as handle:
            json.dump(results, handle, indent=1, sort_keys=True)
        print("dumped %d circuits" % len(corpus))
        return
    corpus = {}
    for spec in CASES:
        corpus[spec["name"]] = spec["netlist"]
    for name, netlist, _fragment in FAILURES:
        corpus["FAIL: " + name] = netlist

    with open(os.path.join(HERE, "corpus.json"), "w") as handle:
        json.dump(corpus, handle, indent=1, sort_keys=True)

    results = {name: dump_one(netlist) for name, netlist in corpus.items()}
    with open(os.path.join(HERE, "results_python.json"), "w") as handle:
        json.dump(results, handle, indent=1, sort_keys=True)

    print("dumped %d circuits" % len(corpus))


if __name__ == "__main__":
    main()
