"""Modified Nodal Analysis.

Given a circuit, a time window (before or after t = 0) and a way of treating the
storage elements, this builds the linear system A x = b whose unknowns are the
node voltages plus one current per element that cannot be written as a
conductance.

The two storage treatments are the whole trick behind initial-condition
problems:

  storage="dc"   steady state.  An inductor is a short (0 V source), a capacitor
                 is an open circuit.  Used for t < 0 and for t -> infinity.

  storage="ic"   the instant just after switching.  An inductor becomes a
                 current source holding i_L, a capacitor becomes a voltage
                 source holding v_C, because those are the two quantities that
                 cannot change instantaneously.

Crucially the "ic" matrix does not depend on the values of i_L and v_C -- they
only ever land in b.  So one assembled matrix solves both for the values at 0+
and, with a differentiated right-hand side, for the derivatives at 0+.

A branch current is split into an unknown part (coefficients over x, which goes
into the matrix) and a known part (a plain number, which goes into b).  Keeping
those separate is what lets a CCCS be controlled by *any* branch, including an
inductor that is currently standing in as a current source.
"""

from fractions import Fraction

from circuit import CircuitError, is_ground
from exact import SingularSystem, format_number, solve, zeros

# Roles that carry their own current unknown, and so also a constraint row.
CURRENT_UNKNOWN_ROLES = ("short", "vsrc", "vsrc_indep", "vctrl")


def role_of(element, window, storage):
    """How an element behaves in this configuration."""
    kind = element.kind
    if kind == "R":
        return "resistor"
    if kind == "L":
        return "short" if storage == "dc" else "isrc"
    if kind == "C":
        return "open" if storage == "dc" else "vsrc"
    if kind == "V":
        return "vsrc_indep"
    if kind == "I":
        return "isrc_indep"
    if kind == "SW":
        return "short" if element.state(window) == "closed" else "open"
    if kind in ("E", "H", "OPAMP"):
        return "vctrl"
    if kind in ("G", "F"):
        return "ictrl"
    raise CircuitError("no analysis role for element kind %r" % kind)


ROLE_DESCRIPTION = {
    "resistor": "resistor",
    "short": "replaced by a short circuit",
    "open": "removed (open circuit)",
    "isrc": "replaced by a current source",
    "vsrc": "replaced by a voltage source",
    "vsrc_indep": "voltage source",
    "isrc_indep": "current source",
    "vctrl": "voltage-defining element",
    "ictrl": "current-defining element",
}


class MnaSystem(object):
    """The assembled equations for one configuration of the circuit."""

    def __init__(self, circuit, window, storage):
        self.circuit = circuit
        self.window = window
        self.storage = storage

        self.node_names = circuit.free_nodes
        self.node_index = {name: i for i, name in enumerate(self.node_names)}
        self.roles = {e.name: role_of(e, window, storage) for e in circuit.elements}

        self.current_elements = [e for e in circuit.elements
                                 if self.roles[e.name] in CURRENT_UNKNOWN_ROLES]
        offset = len(self.node_names)
        self.current_index = {e.name: offset + i
                              for i, e in enumerate(self.current_elements)}

        self.size = len(self.node_names) + len(self.current_elements)
        self.labels = (["V(%s)" % n for n in self.node_names] +
                       ["i(%s)" % e.name for e in self.current_elements])
        self.row_labels = (["KCL at node %s" % n for n in self.node_names] +
                           [self._constraint_label(e) for e in self.current_elements])

        self.matrix = zeros(self.size, self.size)
        self._build_matrix()

    # -- indexing helpers -------------------------------------------------

    def _col(self, node):
        """Column for a node voltage, or None for ground (whose voltage is 0)."""
        if is_ground(node):
            return None
        if node not in self.node_index:
            raise CircuitError("unknown node %r" % node)
        return self.node_index[node]

    def _constraint_label(self, element):
        role = self.roles[element.name]
        if role == "short":
            if element.kind == "L":
                return "%s is a short" % element.name
            return "%s is closed" % element.name
        if role == "vsrc":
            return "%s holds its voltage" % element.name
        if role == "vsrc_indep":
            return "%s sets its voltage" % element.name
        if element.kind == "OPAMP":
            return "%s virtual short" % element.name
        return "%s defining equation" % element.name

    def kcl_terminals(self, element):
        """(node, sign) pairs for how a branch current enters the KCL rows.

        The sign is +1 at a node the current leaves through the element.
        """
        if element.kind == "OPAMP":
            # The unknown is the current the op-amp delivers into its output
            # node, so it arrives at that node rather than leaving it.
            return [(element.nodes[2], Fraction(-1))]
        return [(element.nodes[0], Fraction(1)), (element.nodes[1], Fraction(-1))]

    # -- matrix assembly ---------------------------------------------------

    def _add(self, row, col, value):
        if row is None or col is None:
            return
        self.matrix[row][col] += value

    def _build_matrix(self):
        for element in self.circuit.elements:
            role = self.roles[element.name]
            if role == "resistor":
                self._stamp_resistor(element)
            elif role == "ictrl":
                self._stamp_controlled_current(element)
            elif role in CURRENT_UNKNOWN_ROLES:
                self._stamp_current_unknown(element)
            # "open", "isrc" and "isrc_indep" contribute to b only.

    def _stamp_resistor(self, element):
        a, b = (self._col(n) for n in element.nodes)
        g = Fraction(1) / element.value
        self._add(a, a, g)
        self._add(a, b, -g)
        self._add(b, a, -g)
        self._add(b, b, g)

    def _stamp_current_unknown(self, element):
        """Put the branch current into KCL, then write its defining equation."""
        k = self.current_index[element.name]
        for node, sign in self.kcl_terminals(element):
            self._add(self._col(node), k, sign)

        row = k  # each constraint row sits at the index of its own current
        if element.kind == "OPAMP":
            # An ideal op-amp forces v(in+) = v(in-).
            self._add(row, self._col(element.nodes[0]), Fraction(1))
            self._add(row, self._col(element.nodes[1]), Fraction(-1))
            return

        # Every other case constrains the element terminal voltage.
        self._add(row, self._col(element.nodes[0]), Fraction(1))
        self._add(row, self._col(element.nodes[1]), Fraction(-1))

        if element.kind == "E":  # v = gain * (v(c+) - v(c-))
            self._add(row, self._col(element.ctrl_nodes[0]), -element.gain)
            self._add(row, self._col(element.ctrl_nodes[1]), element.gain)
        elif element.kind == "H":  # v = gain * i_ctrl
            for col, coef in self.current_form(
                    self.circuit.get(element.ctrl_element)).items():
                self._add(row, col, -element.gain * coef)
        # role "short" needs nothing more: its equation is simply v = 0.
        # roles "vsrc" and "vsrc_indep" put their value in b.

    def _stamp_controlled_current(self, element):
        """VCCS and CCCS: a branch current that depends on other unknowns."""
        coeffs = self.current_form(element)
        for node, sign in self.kcl_terminals(element):
            row = self._col(node)
            for col, coef in coeffs.items():
                self._add(row, col, sign * coef)

    # -- branch currents, split into unknown and known parts ---------------

    def current_form(self, element):
        """The part of a branch current that depends on the unknowns.

        Returns a mapping of column index -> coefficient.
        """
        role = self.roles[element.name]
        if role in CURRENT_UNKNOWN_ROLES:
            return {self.current_index[element.name]: Fraction(1)}
        if role == "resistor":
            g = Fraction(1) / element.value
            return _combine({}, self._col(element.nodes[0]), g,
                            self._col(element.nodes[1]), -g)
        if role in ("open", "isrc", "isrc_indep"):
            return {}
        if role == "ictrl":
            if element.kind == "G":
                return _combine({},
                                self._col(element.ctrl_nodes[0]), element.gain,
                                self._col(element.ctrl_nodes[1]), -element.gain)
            base = self.current_form(self.circuit.get(element.ctrl_element))
            return {col: element.gain * coef for col, coef in base.items()}
        raise CircuitError("cannot express the current through %s" % element.name)

    def known_current(self, element, source_values, storage_values):
        """The part of a branch current that is already a plain number."""
        role = self.roles[element.name]
        if role == "isrc":
            return storage_values[element.name]
        if role == "isrc_indep":
            return source_values[element.name]
        if role == "ictrl" and element.kind == "F":
            inner = self.known_current(self.circuit.get(element.ctrl_element),
                                       source_values, storage_values)
            return element.gain * inner
        return Fraction(0)

    # -- right-hand side ---------------------------------------------------

    def build_rhs(self, source_values, storage_values):
        """Assemble b for given source outputs and storage-element values.

        ``source_values`` maps independent source names to their output, and
        ``storage_values`` maps inductor names to a current and capacitor names
        to a voltage.  Passing time derivatives instead of values gives the
        differentiated system, which is how the dv/dt answers are found.
        """
        rhs = [Fraction(0)] * self.size

        def inject(tail, head, current):
            """Account for a known current flowing tail -> head inside a branch."""
            t, h = self._col(tail), self._col(head)
            if t is not None:
                rhs[t] -= current
            if h is not None:
                rhs[h] += current

        for element in self.circuit.elements:
            role = self.roles[element.name]
            if role in ("isrc", "isrc_indep"):
                inject(element.nodes[0], element.nodes[1],
                       self.known_current(element, source_values, storage_values))
            elif role == "vsrc_indep":
                rhs[self.current_index[element.name]] = source_values[element.name]
            elif role == "vsrc":
                rhs[self.current_index[element.name]] = storage_values[element.name]
            elif role == "ictrl":
                known = self.known_current(element, source_values, storage_values)
                if known:
                    inject(element.nodes[0], element.nodes[1], known)
            elif role == "vctrl" and element.kind == "H":
                known = self.known_current(self.circuit.get(element.ctrl_element),
                                           source_values, storage_values)
                if known:
                    rhs[self.current_index[element.name]] += element.gain * known
        return rhs

    def solve(self, source_values, storage_values):
        rhs = self.build_rhs(source_values, storage_values)
        try:
            x = solve(self.matrix, rhs)
        except SingularSystem as error:
            error.system = self
            raise
        return Solution(self, x, source_values, storage_values, rhs)

    # -- presentation ------------------------------------------------------

    def equation_lines(self, rhs):
        """Render the system the way it would be written out by hand."""
        lines = []
        for r in range(self.size):
            terms = []
            for c in range(self.size):
                coef = self.matrix[r][c]
                if coef == 0:
                    continue
                terms.append(_term(coef, self.labels[c], not terms))
            left = " ".join(terms) if terms else "0"
            lines.append("%-26s %s = %s"
                         % (self.row_labels[r] + ":", left, format_number(rhs[r])))
        return lines


def _combine(target, col_a, coef_a, col_b, coef_b):
    for col, coef in ((col_a, coef_a), (col_b, coef_b)):
        if col is not None:
            target[col] = target.get(col, Fraction(0)) + coef
    return target


def _term(coef, label, first):
    negative = coef < 0
    magnitude = -coef if negative else coef
    body = label if magnitude == 1 else "%s*%s" % (format_number(magnitude), label)
    if first:
        return ("-" + body) if negative else body
    return ("- " if negative else "+ ") + body


class Solution(object):
    """Node voltages and branch quantities for one solved configuration."""

    def __init__(self, system, x, source_values, storage_values, rhs):
        self.system = system
        self.x = x
        self.source_values = source_values
        self.storage_values = storage_values
        self.rhs = rhs

    def node_voltage(self, node):
        if is_ground(node):
            return Fraction(0)
        return self.x[self.system.node_index[node]]

    def element_voltage(self, element):
        """v = V(first node) - V(second node), the passive convention."""
        if element.kind == "OPAMP":
            return self.node_voltage(element.nodes[2])
        return (self.node_voltage(element.nodes[0]) -
                self.node_voltage(element.nodes[1]))

    def element_current(self, element):
        """Current through the element, in the direction its node order declares."""
        system = self.system
        role = system.roles[element.name]
        if role in CURRENT_UNKNOWN_ROLES:
            return self.x[system.current_index[element.name]]
        if role == "resistor":
            return self.element_voltage(element) / element.value
        if role == "open":
            return Fraction(0)
        if role in ("isrc", "isrc_indep"):
            return system.known_current(element, self.source_values,
                                        self.storage_values)
        if role == "ictrl":
            if element.kind == "G":
                return element.gain * (
                    self.node_voltage(element.ctrl_nodes[0]) -
                    self.node_voltage(element.ctrl_nodes[1]))
            return element.gain * self.element_current(
                system.circuit.get(element.ctrl_element))
        raise CircuitError("cannot report the current through %s" % element.name)

    def as_dict(self):
        out = {"nodes": {}, "currents": {}, "voltages": {}}
        for node in self.system.circuit.nodes:
            out["nodes"][node] = self.node_voltage(node)
        for element in self.system.circuit.elements:
            out["currents"][element.name] = self.element_current(element)
            out["voltages"][element.name] = self.element_voltage(element)
        return out
