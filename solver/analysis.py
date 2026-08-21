"""The initial- and final-condition procedure, and what follows from it.

The core is four solves, in this order:

  1. t < 0      steady state of the pre-switch circuit.  L is a short, C is an
                open.  This is where i_L(0-) and v_C(0-) come from.

  2. t = 0+     the post-switch circuit with L standing in as a current source
                holding i_L(0-) and C as a voltage source holding v_C(0-).
                Continuity is the entire justification: inductor current and
                capacitor voltage are the only quantities that cannot jump.
                Solving gives every other branch value at 0+, which is where the
                ones that *can* jump (v_R, i_C, v_L) are pinned down.

  3. d/dt at 0+ the same equations differentiated once.  The matrix is
                unchanged; only the right-hand side moves, because the storage
                elements now hold di_L/dt = v_L(0+)/L and dv_C/dt = i_C(0+)/C,
                and constant sources differentiate to zero.

  4. t -> inf   steady state of the post-switch circuit, L short, C open again.

Steps 1 and 4 are the same code with a different time window; steps 2 and 3 are
the same matrix with a different right-hand side.  Step 3 repeats for as many
orders as asked for, each order feeding the next.

Once those are done, dynamics.py recovers the state matrix by probing the same
t = 0+ system, which gives the natural frequencies and the damping, and the
values already computed at 0+, its slope, and infinity are exactly the three
constants a closed-form response needs.
"""

from fractions import Fraction

from circuit import is_ground
from dynamics import analyse_dynamics, response_for
from exact import SingularSystem
from mna import MnaSystem

# How many derivatives at 0+ to work out. Two covers second-order circuits,
# which is as far as the closed-form response goes.
DEFAULT_DERIVATIVE_ORDER = 2

DERIVATIVE_KEYS = {1: "d/dt", 2: "d2/dt2", 3: "d3/dt3"}


class AnalysisError(Exception):
    """The circuit is well-formed but its equations have no unique answer."""


class Phase(object):
    """One solved configuration, kept alongside how it was set up."""

    def __init__(self, key, title, system, solution, description):
        self.key = key
        self.title = title
        self.system = system
        self.solution = solution
        self.description = description

    @property
    def rhs(self):
        return self.solution.rhs


PHASE_KEYS = ["t<0", "0+", "d/dt", "d2/dt2", "d3/dt3", "inf"]


class Result(object):
    """Everything the four solves produced, indexed for easy reporting."""

    def __init__(self, circuit):
        self.circuit = circuit
        self.phases = {}
        self.initial_conditions = {}
        self.ic_sources = {}
        self.derivative_storage = {}
        self.dynamics = None
        self.responses = {}
        self.ac = None
        self.notes = []

    def add(self, phase):
        self.phases[phase.key] = phase
        return phase

    def value(self, phase_key, element_name, quantity):
        """quantity is 'v' or 'i'."""
        phase = self.phases.get(phase_key)
        if phase is None:
            return None
        element = self.circuit.get(element_name)
        if quantity == "v":
            return phase.solution.element_voltage(element)
        return phase.solution.element_current(element)

    def node(self, phase_key, node_name):
        phase = self.phases.get(phase_key)
        if phase is None:
            return None
        return phase.solution.node_voltage(node_name)

    def table(self):
        """Every element, every quantity, across every phase."""
        rows = []
        for element in self.circuit.elements:
            row = {"element": element, "cells": {}}
            for key in PHASE_KEYS:
                phase = self.phases.get(key)
                if phase is None:
                    row["cells"][key] = None
                    continue
                row["cells"][key] = {
                    "v": phase.solution.element_voltage(element),
                    "i": phase.solution.element_current(element),
                }
            rows.append(row)
        return rows


def analyse(circuit, max_derivative_order=DEFAULT_DERIVATIVE_ORDER):
    circuit.validate()
    result = Result(circuit)
    storage = circuit.of_kind("L", "C")

    _note_assumptions(circuit, result, storage)

    # ---- phase 1: t < 0, steady state of the pre-switch circuit ----------
    given_ics = {e.name: e.ic for e in storage if e.ic is not None}
    all_ics_given = storage and len(given_ics) == len(storage)

    system = MnaSystem(circuit, "before", "dc")
    try:
        solution = system.solve(_source_values(circuit, "before"), {})
        result.add(Phase("t<0", "Steady state before switching", system, solution,
                         _describe_dc(circuit, "before")))
    except SingularSystem as error:
        reason = diagnose(system, error)
        if not all_ics_given:
            raise AnalysisError(
                "the t < 0 circuit has no unique steady state: %s\n"
                "If the question tells you the starting values, put them on the "
                "components with ic= and the solver will use those instead."
                % reason)
        result.notes.append(
            "The t < 0 circuit has no unique steady state (%s), so the given "
            "initial conditions are used directly." % reason)

    for element in storage:
        if element.name in given_ics:
            result.initial_conditions[element.name] = given_ics[element.name]
            result.ic_sources[element.name] = "given"
        else:
            phase = result.phases["t<0"]
            if element.kind == "L":
                value = phase.solution.element_current(element)
            else:
                value = phase.solution.element_voltage(element)
            result.initial_conditions[element.name] = value
            result.ic_sources[element.name] = "solved"

    # ---- phase 2: t = 0+, continuity ------------------------------------
    zero_plus_system = MnaSystem(circuit, "after", "ic")
    zero_plus = _solve_or_explain(zero_plus_system,
                                  _source_values(circuit, "after"),
                                  result.initial_conditions, "t = 0+")
    result.add(Phase("0+", "The instant after switching", zero_plus_system,
                     zero_plus, _describe_ic(circuit, result.initial_conditions)))

    # ---- phase 3: derivatives at 0+, to as many orders as asked for -------
    # Each order feeds the next. The n-th derivative of an inductor current is
    # the (n-1)-th derivative of its voltage over L, and the same for a
    # capacitor with its current over C, so one loop covers every order.
    zero_sources = {e.name: Fraction(0) for e in circuit.of_kind("V", "I")}
    previous = zero_plus
    for order in range(1, max_derivative_order + 1):
        storage_values = {}
        for element in storage:
            if element.kind == "L":
                storage_values[element.name] = (
                    previous.element_voltage(element) / element.value)
            else:
                storage_values[element.name] = (
                    previous.element_current(element) / element.value)

        key = DERIVATIVE_KEYS[order]
        label = ("First derivatives at t = 0+" if order == 1
                 else "Derivative %d at t = 0+" % order)
        solution = _solve_or_explain(zero_plus_system, zero_sources,
                                     storage_values, "derivatives at 0+")
        result.add(Phase(key, label, zero_plus_system, solution,
                         _describe_derivative(circuit, storage_values, order)))
        result.derivative_storage[order] = storage_values
        previous = solution

    # ---- phase 4: t -> infinity ------------------------------------------
    final_system = MnaSystem(circuit, "after", "dc")
    try:
        final = final_system.solve(_source_values(circuit, "after"), {})
        result.add(Phase("inf", "Steady state long after switching", final_system,
                         final, _describe_dc(circuit, "after")))
    except SingularSystem as error:
        result.notes.append(
            "There is no final steady state to report: %s Physically this "
            "circuit does not settle to fixed values, which is what an "
            "integrator or a source-free floating node looks like."
            % diagnose(final_system, error))

    # ---- natural frequencies and the closed-form response ------------------
    if storage:
        result.dynamics = analyse_dynamics(circuit, zero_plus_system,
                                           _source_values(circuit, "after"))
        result.notes.extend(result.dynamics.notes)
        if result.dynamics.damping and "inf" in result.phases:
            for element in circuit.elements:
                forms = {}
                for quantity in ("v", "i"):
                    form = response_for(
                        result.dynamics,
                        "%s_%s" % (quantity, element.name),
                        "V" if quantity == "v" else "A",
                        result.value("0+", element.name, quantity),
                        result.value("d/dt", element.name, quantity),
                        result.value("inf", element.name, quantity))
                    if form is not None:
                        forms[quantity] = form
                if forms:
                    result.responses[element.name] = forms

    # ---- AC steady state, only when a frequency was given -----------------
    if circuit.ac_omega:
        from circuit import CircuitError
        from phasor import analyse_ac
        try:
            result.ac = analyse_ac(circuit, circuit.ac_omega)
        except SingularSystem:
            result.notes.append(
                "The AC equations at that frequency have no unique solution, "
                "so no steady state is reported.")
        except CircuitError as error:
            result.notes.append("AC steady state was skipped: %s" % error)

    return result


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _source_values(circuit, window):
    return {e.name: e.source_value(window) for e in circuit.of_kind("V", "I")}


def _solve_or_explain(system, source_values, storage_values, phase_name):
    try:
        return system.solve(source_values, storage_values)
    except SingularSystem as error:
        raise AnalysisError("%s: %s" % (phase_name, diagnose(system, error)))


def _describe_dc(circuit, window):
    lines = []
    for element in circuit.of_kind("L"):
        lines.append("%s -> short circuit (steady state, so v = L di/dt = 0)"
                     % element.name)
    for element in circuit.of_kind("C"):
        lines.append("%s -> open circuit (steady state, so i = C dv/dt = 0)"
                     % element.name)
    for element in circuit.of_kind("V", "I"):
        value = element.source_value(window)
        if element.before != element.after:
            lines.append("%s -> %s (it is %s here)"
                         % (element.name, _quantity(element, value),
                            "off" if value == 0 else "on"))
    for element in circuit.of_kind("SW"):
        lines.append("%s -> %s" % (element.name, element.state(window)))
    return lines


def _describe_ic(circuit, initial_conditions):
    lines = []
    for element in circuit.of_kind("L"):
        lines.append("%s -> current source of %s A, because inductor current "
                     "cannot jump" % (element.name,
                                      _fmt(initial_conditions[element.name])))
    for element in circuit.of_kind("C"):
        lines.append("%s -> voltage source of %s V, because capacitor voltage "
                     "cannot jump" % (element.name,
                                      _fmt(initial_conditions[element.name])))
    for element in circuit.of_kind("V", "I"):
        if element.before != element.after:
            lines.append("%s -> %s (its t > 0 value)"
                         % (element.name, _quantity(element, element.after)))
    for element in circuit.of_kind("SW"):
        lines.append("%s -> %s" % (element.name, element.state_after))
    return lines


def _describe_derivative(circuit, derivative_storage, order=1):
    times = "once" if order == 1 else "%d times" % order
    lines = ["same equations as t = 0+, differentiated %s with respect to time"
             % times,
             "every source is constant for t > 0, so all source terms become 0"]
    prime = "" if order == 1 else "^%d" % order
    for element in circuit.of_kind("L"):
        lines.append("%s -> current source of d%si/dt%s = %s A/s%s"
                     % (element.name, prime, prime,
                        _fmt(derivative_storage[element.name]),
                        "" if order == 1 else "^%d" % order))
    for element in circuit.of_kind("C"):
        lines.append("%s -> voltage source of d%sv/dt%s = %s V/s%s"
                     % (element.name, prime, prime,
                        _fmt(derivative_storage[element.name]),
                        "" if order == 1 else "^%d" % order))
    return lines


def _quantity(element, value):
    unit = "V" if element.kind == "V" else "A"
    return "%s %s" % (_fmt(value), unit)


def _fmt(value):
    from exact import format_number
    return format_number(value)


def _note_assumptions(circuit, result, storage):
    if not storage:
        result.notes.append(
            "There are no inductors or capacitors, so nothing changes with "
            "time: every phase gives the same answer.")
    if circuit.of_kind("L") and not _has_resistance(circuit):
        result.notes.append(
            "This circuit has no resistance in it. A lossless LC circuit rings "
            "forever, so the t -> infinity column is the steady state the "
            "equations give, not a value the circuit actually settles at.")
    if not circuit.sources_change() and not circuit.switches_change():
        result.notes.append(
            "No source steps and no switch changes state at t = 0, so the "
            "circuit is already in steady state and nothing transient happens.")
    if circuit.of_kind("OPAMP"):
        result.notes.append(
            "Op-amps are treated as ideal: infinite gain, no input current, "
            "and an output that can supply whatever it needs to. The solver "
            "assumes the op-amp stays in its linear region.")


def _has_resistance(circuit):
    return bool(circuit.of_kind("R"))


# --------------------------------------------------------------------------
# diagnosis
# --------------------------------------------------------------------------

CONDUCTIVE_ROLES = ("resistor", "short", "vsrc", "vsrc_indep")


def diagnose(system, error):
    """Turn a singular matrix into something a student can act on."""
    floating = _floating_nodes(system)
    if floating:
        hint = ("its voltage is not determined by anything. Give it a resistive "
                "path to ground, or set an initial condition on the capacitor "
                "with ic=")
        if len(floating) == 1:
            return ("node %s is isolated in this configuration, so %s."
                    % (floating[0], hint))
        return ("nodes %s are isolated in this configuration, so %s."
                % (", ".join(floating), hint))

    conflict = _voltage_conflict(system)
    if conflict:
        return conflict

    if system.circuit.of_kind("OPAMP"):
        return ("the equations are inconsistent. With an ideal op-amp this "
                "usually means there is no negative feedback path from the "
                "output back to the inverting input.")

    undetermined = [system.labels[c] for c in error.free_columns
                    if c < len(system.labels)]
    if undetermined:
        return ("the equations do not pin down %s. Check for a loop of voltage "
                "sources, or current sources in series."
                % ", ".join(undetermined))
    return ("the equations have no unique solution. Check for a loop of voltage "
            "sources, or current sources in series with each other.")


def _floating_nodes(system):
    """Nodes with no conductive path back to ground in this configuration."""
    parent = {name: name for name in system.circuit.nodes}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    ground = [n for n in system.circuit.nodes if is_ground(n)]
    for extra in ground[1:]:
        union(extra, ground[0])

    for element in system.circuit.elements:
        role = system.roles[element.name]
        if role in CONDUCTIVE_ROLES:
            union(element.nodes[0], element.nodes[1])
        elif role == "vctrl":
            if element.kind == "OPAMP":
                # A driven output is not floating.
                union(element.nodes[2], ground[0])
            else:
                union(element.nodes[0], element.nodes[1])

    root = find(ground[0])
    return [n for n in system.circuit.free_nodes if find(n) != root]


def _voltage_conflict(system):
    """Two voltage-defining elements across the same node pair."""
    seen = {}
    for element in system.circuit.elements:
        role = system.roles[element.name]
        if role not in ("vsrc", "vsrc_indep", "short"):
            continue
        key = frozenset(element.nodes)
        if key in seen:
            return ("%s and %s are both connected straight across nodes %s and "
                    "%s, so they fight over the same voltage."
                    % (seen[key], element.name, element.nodes[0], element.nodes[1]))
        seen[key] = element.name
    return None
