"""Regression tests: every expected value here was worked out by hand first.

Each case lists a netlist and a set of (phase, element, quantity, expected)
checks.  Phases are "t<0", "0+", "d/dt" and "inf"; quantities are "v" and "i".
In the "d/dt" phase those mean dv/dt and di/dt.
"""

import os
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "solver"))

from analysis import AnalysisError, analyse
from circuit import CircuitError, parse_netlist
from exact import format_number

CASES = []


def case(name, netlist, checks, nodes=None, notes_contain=None):
    CASES.append({"name": name, "netlist": netlist, "checks": checks,
                  "nodes": nodes or [], "notes_contain": notes_contain})


# --------------------------------------------------------------------------
# 1. The lecture example: parallel RLC driven by a step and a DC source.
# --------------------------------------------------------------------------
case(
    "lecture example 2 (parallel RLC, 4u(t) + 6 A)",
    """
    R1 1 2 5
    C1 1 0 1/5
    L1 2 0 2
    I1 0 1 step 4
    I2 0 2 dc 6
    """,
    [
        ("t<0", "L1", "i", 6), ("t<0", "C1", "v", 0),
        ("0+", "L1", "i", 6), ("0+", "C1", "v", 0), ("0+", "R1", "v", 0),
        ("0+", "C1", "i", 4), ("0+", "L1", "v", 0),
        ("d/dt", "L1", "i", 0), ("d/dt", "C1", "v", 20), ("d/dt", "R1", "v", 0),
        ("inf", "L1", "i", 10), ("inf", "C1", "v", 20), ("inf", "R1", "v", 20),
    ],
)

# --------------------------------------------------------------------------
# 2. Series RLC step response.  Nothing is stored at t<0, so the step lands
#    entirely across the inductor at 0+.
# --------------------------------------------------------------------------
case(
    "series RLC, 12u(t) V source",
    """
    V1 1 0 step 12
    R1 1 2 4
    L1 2 3 1
    C1 3 0 1/4
    """,
    [
        ("t<0", "L1", "i", 0), ("t<0", "C1", "v", 0),
        ("0+", "L1", "i", 0), ("0+", "C1", "v", 0),
        ("0+", "R1", "v", 0), ("0+", "L1", "v", 12), ("0+", "C1", "i", 0),
        ("d/dt", "L1", "i", 12), ("d/dt", "C1", "v", 0),
        ("d/dt", "R1", "v", 48), ("d/dt", "L1", "v", -48),
        ("inf", "C1", "v", 12), ("inf", "L1", "i", 0),
        ("inf", "R1", "v", 0), ("inf", "L1", "v", 0),
    ],
)

# --------------------------------------------------------------------------
# 3. A switch that opens and strands an inductor: the classic inductive kick.
# --------------------------------------------------------------------------
case(
    "switch opens, inductor forces current through R2",
    """
    V1 1 0 dc 10
    R1 1 2 5
    SW1 2 3 closed open
    L1 3 0 2
    R2 3 0 20
    """,
    [
        ("t<0", "L1", "i", 2), ("t<0", "R2", "i", 0),
        ("0+", "L1", "i", 2), ("0+", "L1", "v", -40), ("0+", "R2", "i", -2),
        ("d/dt", "L1", "i", -20),
        ("inf", "L1", "i", 0), ("inf", "L1", "v", 0),
    ],
    nodes=[("0+", "3", -40), ("inf", "2", 10)],
)

# --------------------------------------------------------------------------
# 4. Resistive divider feeding a VCVS.  No storage, so time does not matter.
# --------------------------------------------------------------------------
case(
    "VCVS driven by a divider",
    """
    V1 1 0 dc 10
    R1 1 2 1000
    R2 2 0 1000
    E1 3 0 2 0 5
    R3 3 0 100
    """,
    [("0+", "R3", "i", Fraction(1, 4))],
    nodes=[("0+", "2", 5), ("0+", "3", 25)],
)

# --------------------------------------------------------------------------
# 5. VCCS and CCVS, checked against hand-solved node equations.
# --------------------------------------------------------------------------
case(
    "VCCS injecting 3*V(1)",
    """
    V1 1 0 dc 4
    R1 1 2 2
    G1 0 2 1 0 3
    R2 2 0 1
    """,
    [],
    nodes=[("0+", "2", Fraction(28, 3))],
)

case(
    "CCVS controlled by a resistor current",
    """
    I1 0 1 dc 3
    R1 1 0 4
    H1 2 0 R1 5
    R2 2 0 10
    """,
    [("0+", "R1", "i", 3), ("0+", "H1", "i", Fraction(-3, 2))],
    nodes=[("0+", "1", 12), ("0+", "2", 15)],
)

# --------------------------------------------------------------------------
# 6. A CCCS controlled by an inductor.  This is the case that forces the
#    solver to treat a controlling current as known rather than unknown,
#    because at 0+ the inductor is standing in as a current source.
# --------------------------------------------------------------------------
case(
    "CCCS controlled by an inductor current",
    """
    I1 0 1 6 10
    R1 1 0 3
    L1 1 0 2
    F1 0 2 L1 2
    R2 2 0 5
    """,
    [
        ("t<0", "L1", "i", 6),
        ("0+", "L1", "i", 6), ("0+", "L1", "v", 12), ("0+", "F1", "i", 12),
        ("d/dt", "L1", "i", 6),
        ("inf", "L1", "i", 10), ("inf", "F1", "i", 20),
    ],
    nodes=[("0+", "1", 12), ("0+", "2", 60),
           ("d/dt", "1", -18), ("d/dt", "2", 60),
           ("inf", "2", 100)],
)

# --------------------------------------------------------------------------
# 7. Ideal op-amp: inverting amplifier, gain -5.
# --------------------------------------------------------------------------
case(
    "inverting op-amp amplifier",
    """
    V1 1 0 dc 2
    R1 1 2 1000
    R2 2 3 5000
    OP1 0 2 3
    """,
    [("0+", "R1", "i", Fraction(1, 500))],
    nodes=[("0+", "2", 0), ("0+", "3", -10)],
)

# --------------------------------------------------------------------------
# 8. Op-amp integrator with a stated initial condition.  Its output ramps at
#    -Vin/RC = -1000 V/s, and it has no DC steady state at either end.
# --------------------------------------------------------------------------
case(
    "op-amp integrator, 1 V step, RC = 1 ms",
    """
    V1 1 0 step 1
    R1 1 2 1000
    C1 2 3 1/1000000 ic=0
    OP1 0 2 3
    """,
    [
        ("0+", "C1", "v", 0), ("0+", "C1", "i", Fraction(1, 1000)),
        ("d/dt", "C1", "v", 1000),
    ],
    nodes=[("0+", "3", 0), ("d/dt", "3", -1000)],
    notes_contain="no final steady state",
)

# --------------------------------------------------------------------------
# 9. Two capacitors in series across a step: charge sharing sets the split.
#    Series caps have no DC path, so the t<0 solve must fail loudly unless
#    initial conditions are supplied.
# --------------------------------------------------------------------------
case(
    "series capacitors need stated initial conditions",
    """
    V1 1 0 step 9
    R1 1 2 1
    C1 2 3 1/2 ic=0
    C2 3 0 1/4 ic=0
    """,
    [
        ("0+", "C1", "v", 0), ("0+", "C2", "v", 0),
        ("0+", "R1", "i", 9), ("0+", "C1", "i", 9), ("0+", "C2", "i", 9),
        ("d/dt", "C1", "v", 18), ("d/dt", "C2", "v", 36),
    ],
)


# --------------------------------------------------------------------------
# Failure cases: the solver must refuse rather than invent a number.
# --------------------------------------------------------------------------
FAILURES = [
    ("floating node with no DC path",
     """
     I1 0 1 dc 1
     C1 1 0 1
     C2 1 2 1
     """,
     "isolated"),
    ("no ground node",
     """
     R1 1 2 5
     V1 1 2 dc 4
     """,
     "ground"),
    ("negative resistance",
     """
     V1 1 0 dc 5
     R1 1 0 -3
     """,
     "positive"),
    ("control loop",
     """
     I1 0 1 dc 1
     R1 1 0 1
     F1 0 2 F2 2
     F2 0 3 F1 2
     R2 2 0 1
     R3 3 0 1
     """,
     "loop"),
]


def run():
    failures = []
    total = 0

    for spec in CASES:
        try:
            result = analyse(parse_netlist(spec["netlist"]))
        except Exception as error:  # noqa: BLE001 - report anything at all
            failures.append("%s: raised %s: %s"
                            % (spec["name"], type(error).__name__, error))
            continue

        for phase, name, quantity, expected in spec["checks"]:
            total += 1
            got = result.value(phase, name, quantity)
            if got != Fraction(expected):
                failures.append(
                    "%s: %s %s(%s) = %s, expected %s"
                    % (spec["name"], phase, quantity, name,
                       format_number(got) if got is not None else "none", expected))

        for phase, node, expected in spec["nodes"]:
            total += 1
            got = result.node(phase, node)
            if got != Fraction(expected):
                failures.append(
                    "%s: %s V(%s) = %s, expected %s"
                    % (spec["name"], phase, node,
                       format_number(got) if got is not None else "none", expected))

        if spec["notes_contain"]:
            total += 1
            blob = " ".join(result.notes)
            if spec["notes_contain"] not in blob:
                failures.append("%s: expected a note mentioning %r, got %r"
                                % (spec["name"], spec["notes_contain"], blob))

    for name, netlist, fragment in FAILURES:
        total += 1
        try:
            analyse(parse_netlist(netlist))
        except (AnalysisError, CircuitError) as error:
            if fragment not in str(error):
                failures.append("%s: refused, but the message %r does not "
                                "mention %r" % (name, str(error), fragment))
        except Exception as error:  # noqa: BLE001
            failures.append("%s: raised the wrong error type %s: %s"
                            % (name, type(error).__name__, error))
        else:
            failures.append("%s: was accepted, but it should have been refused"
                            % name)

    print("%d checks across %d circuits" % (total, len(CASES) + len(FAILURES)))
    if failures:
        print("\nFAILURES (%d):" % len(failures))
        for line in failures:
            print("  -", line)
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
