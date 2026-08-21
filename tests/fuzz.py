"""Generate random circuits to cross-check the two solvers against each other.

Random topologies produce awkward fractions such as 4523/1710, which is exactly
where a floating-point slip or a mis-ported stamp would show up.  The generator
does not try to make solvable circuits: a circuit that both solvers refuse in
the same way is just as useful a datapoint as one they both solve.

    python fuzz.py [count] [seed]
"""

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

KIND_WEIGHTS = [
    ("R", 34), ("C", 14), ("L", 14), ("V", 10), ("I", 10),
    ("SW", 6), ("E", 3), ("G", 3), ("H", 3), ("F", 3),
]


def pick_kind(rng):
    total = sum(weight for _kind, weight in KIND_WEIGHTS)
    roll = rng.uniform(0, total)
    cursor = 0
    for kind, weight in KIND_WEIGHTS:
        cursor += weight
        if roll <= cursor:
            return kind
    return "R"


def pick_value(rng):
    style = rng.random()
    if style < 0.55:
        return str(rng.randint(1, 20))
    if style < 0.85:
        return "%d/%d" % (rng.randint(1, 19), rng.randint(2, 9))
    return "%d.%d" % (rng.randint(0, 9), rng.randint(1, 99))


def pick_signed(rng):
    value = pick_value(rng)
    return ("-" + value) if rng.random() < 0.3 else value


def make_circuit(rng):
    node_count = rng.randint(2, 5)
    nodes = ["0"] + [str(i) for i in range(1, node_count + 1)]
    lines = []
    names = []
    counters = {}

    def pair():
        a, b = rng.sample(nodes, 2)
        return a, b

    element_count = rng.randint(4, 9)
    for _ in range(element_count):
        kind = pick_kind(rng)
        # Controlled sources need something already placed to point at.
        if kind in ("H", "F") and not names:
            kind = "R"
        counters[kind] = counters.get(kind, 0) + 1
        name = kind + str(counters[kind])
        a, b = pair()

        if kind in ("R", "L", "C"):
            line = "%s %s %s %s" % (name, a, b, pick_value(rng))
            if kind in ("L", "C") and rng.random() < 0.25:
                line += " ic=%s" % pick_signed(rng)
        elif kind in ("V", "I"):
            style = rng.random()
            if style < 0.4:
                line = "%s %s %s step %s" % (name, a, b, pick_signed(rng))
            elif style < 0.75:
                line = "%s %s %s dc %s" % (name, a, b, pick_signed(rng))
            else:
                line = "%s %s %s %s %s" % (name, a, b, pick_signed(rng),
                                           pick_signed(rng))
        elif kind == "SW":
            states = rng.choice([("open", "closed"), ("closed", "open"),
                                 ("closed", "closed"), ("open", "open")])
            line = "%s %s %s %s %s" % (name, a, b, states[0], states[1])
        elif kind in ("E", "G"):
            c, d = pair()
            line = "%s %s %s %s %s %s" % (name, a, b, c, d, pick_signed(rng))
        else:  # H or F, controlled by an earlier element
            control = rng.choice(names)
            line = "%s %s %s %s %s" % (name, a, b, control, pick_signed(rng))

        lines.append(line)
        names.append(name)

    # Guarantee the netlist mentions ground so it fails for interesting reasons
    # rather than always tripping the missing-ground check.
    if not any(" 0 " in (" " + line + " ") for line in lines):
        lines.append("R%d 0 1 %s" % (counters.get("R", 0) + 1, pick_value(rng)))

    return "\n".join(lines) + "\n"


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 20260821
    rng = random.Random(seed)

    corpus = {}
    for index in range(count):
        corpus["fuzz-%04d" % index] = make_circuit(rng)

    path = os.path.join(HERE, "corpus_fuzz.json")
    with open(path, "w") as handle:
        json.dump(corpus, handle, indent=1, sort_keys=True)
    print("wrote %d random circuits to %s" % (count, os.path.basename(path)))


if __name__ == "__main__":
    main()
