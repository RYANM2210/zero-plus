"""The initial- and final-condition procedure.

Four solves, in this order:

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
the same matrix with a different right-hand side.
"""

from fractions import Fraction

from circuit import is_ground
from exact import SingularSystem
from mna import MnaSystem


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


class Result(object):
    """Everything the four solves produced, indexed for easy reporting."""

    def __init__(self, circuit):
        self.circuit = circuit
        self.phases = {}
        self.initial_conditions = {}
        self.ic_sources = {}
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
            for key in ("t<0", "0+", "d/dt", "inf"):
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


def analyse(circuit):
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

    # ---- phase 3: derivatives at 0+ --------------------------------------
    derivative_storage = {}
    for element in storage:
        if element.kind == "L":
            # di_L/dt = v_L / L
            derivative_storage[element.name] = (
                zero_plus.element_voltage(element) / element.value)
        else:
            # dv_C/dt = i_C / C
            derivative_storage[element.name] = (
                zero_plus.element_current(element) / element.value)

    # Sources are constant for t > 0, so every source derivative is zero.
    zero_sources = {e.name: Fraction(0) for e in circuit.of_kind("V", "I")}
    derivatives = _solve_or_explain(zero_plus_system, zero_sources,
                                    derivative_storage, "derivatives at 0+")
    result.add(Phase("d/dt", "First derivatives at t = 0+", zero_plus_system,
                     derivatives, _describe_derivative(circuit, derivative_storage)))
    result.derivative_storage = derivative_storage

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


def _describe_derivative(circuit, derivative_storage):
    lines = ["same equations as t = 0+, differentiated once with respect to time",
             "every source is constant for t > 0, so all source terms become 0"]
    for element in circuit.of_kind("L"):
        lines.append("%s -> current source of di/dt = v_L(0+)/L = %s A/s"
                     % (element.name, _fmt(derivative_storage[element.name])))
    for element in circuit.of_kind("C"):
        lines.append("%s -> voltage source of dv/dt = i_C(0+)/C = %s V/s"
                     % (element.name, _fmt(derivative_storage[element.name])))
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
