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

PHASES = ["t<0", "0+", "d/dt", "d2/dt2", "inf"]


def _root_text(root):
    """A complex pair renders the same way in both languages."""
    if isinstance(root, tuple):
        return ",".join(str(part) for part in root)
    return str(root)


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

    d = result.dynamics
    if d is not None and d.order:
        out["dynamics"] = {
            "order": d.order,
            "damping": d.damping or "",
            "alpha": exact(d.alpha) if d.alpha is not None else "",
            "omega0sq": exact(d.omega0_squared) if d.omega0_squared is not None else "",
            "disc": exact(d.discriminant) if d.discriminant is not None else "",
            "stable": bool(d.stable),
            "poly": [exact(c) for c in d.polynomial],
            "tau": str(d.tau) if d.tau is not None else "",
            "roots": [_root_text(r) for r in d.roots],
        }
        out["responses"] = {
            name: {q: form.formula for q, form in forms.items()}
            for name, forms in result.responses.items()
        }

    if result.ac is not None:
        circuit_nodes = {}
        for node in circuit.nodes:
            value = result.ac.solution.node_voltage(node)
            circuit_nodes[node] = "%s|%s" % (exact(value.re), exact(value.im))
        branches = {}
        for element in circuit.elements:
            v = result.ac.solution.element_voltage(element)
            i = result.ac.solution.element_current(element)
            branches[element.name] = {
                "v": "%s|%s" % (exact(v.re), exact(v.im)),
                "i": "%s|%s" % (exact(i.re), exact(i.im)),
            }
        out["ac"] = {
            "omega": exact(result.ac.omega),
            "nodes": circuit_nodes,
            "branches": branches,
            "z": {n: "%s|%s" % (exact(z.re), exact(z.im))
                  for n, z in result.ac.impedances.items()},
        }
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
