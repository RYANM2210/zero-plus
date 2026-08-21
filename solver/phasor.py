"""AC steady state by phasors, in exact complex arithmetic.

At a fixed angular frequency every impedance is a Gaussian rational -- a
complex number whose real and imaginary parts are both exact fractions:

    resistor    Z = R                 real
    inductor    Z = j*w*L             purely imaginary
    capacitor   Z = 1/(j*w*C)         purely imaginary

So the whole nodal analysis can be carried out without a single floating point
number, exactly as the transient side is.  Only two things are genuinely
irrational and they are both at the edges: a source phase that is not a
quarter turn on the way in, and the magnitude and angle of an answer on the way
out.  Everything between them is exact, and the rectangular form of every
result is reported alongside the polar one so nothing is hidden behind a
rounded magnitude.

Frequency is given in radians per second rather than hertz, because w = 2*pi*f
would drag an irrational number into every impedance in the circuit.
"""

import math
from fractions import Fraction

from circuit import CircuitError, is_ground
from exact import SingularSystem, format_number, to_fraction, zeros


class Cx(object):
    """A complex number with exact rational parts."""

    __slots__ = ("re", "im")

    def __init__(self, re=0, im=0):
        self.re = to_fraction(re)
        self.im = to_fraction(im)

    def __add__(self, other):
        return Cx(self.re + other.re, self.im + other.im)

    def __sub__(self, other):
        return Cx(self.re - other.re, self.im - other.im)

    def __mul__(self, other):
        return Cx(self.re * other.re - self.im * other.im,
                  self.re * other.im + self.im * other.re)

    def __truediv__(self, other):
        denominator = other.re * other.re + other.im * other.im
        if denominator == 0:
            raise ZeroDivisionError("division by a zero phasor")
        return Cx((self.re * other.re + self.im * other.im) / denominator,
                  (self.im * other.re - self.re * other.im) / denominator)

    __div__ = __truediv__

    def __neg__(self):
        return Cx(-self.re, -self.im)

    def __eq__(self, other):
        return self.re == other.re and self.im == other.im

    def __ne__(self, other):
        return not self == other

    @property
    def is_zero(self):
        return self.re == 0 and self.im == 0

    @property
    def magnitude(self):
        """Irrational in general, so a float and marked as such in reports."""
        return math.sqrt(float(self.re) ** 2 + float(self.im) ** 2)

    @property
    def degrees(self):
        return math.degrees(math.atan2(float(self.im), float(self.re)))

    def rectangular(self):
        if self.im == 0:
            return format_number(self.re)
        sign = "-" if self.im < 0 else "+"
        return "%s %s j%s" % (format_number(self.re), sign,
                              format_number(abs(self.im)))

    def polar(self):
        return "%.6g / %.6g deg" % (self.magnitude, self.degrees)

    def __repr__(self):
        return "Cx(%s)" % self.rectangular()


ZERO = Cx(0, 0)
ONE = Cx(1, 0)
J = Cx(0, 1)


def polar_to_rect(magnitude, degrees):
    """Exact for quarter turns, which is where phasor problems usually sit."""
    magnitude = to_fraction(magnitude)
    degrees = to_fraction(degrees)
    turn = degrees % 360
    if turn == 0:
        return Cx(magnitude, 0)
    if turn == 90:
        return Cx(0, magnitude)
    if turn == 180:
        return Cx(-magnitude, 0)
    if turn == 270:
        return Cx(0, -magnitude)
    raise CircuitError(
        "a phase of %s degrees cannot be written exactly. Use 0, 90, 180 or "
        "270, or give the phasor in rectangular form instead."
        % format_number(degrees))


# --------------------------------------------------------------------------
# complex nodal analysis
# --------------------------------------------------------------------------

def impedance(element, omega):
    """Z for a passive element at this frequency."""
    if element.kind == "R":
        return Cx(element.value, 0)
    if element.kind == "L":
        return Cx(0, omega * element.value)
    if element.kind == "C":
        product = omega * element.value
        if product == 0:
            raise CircuitError(
                "%s is an open circuit at zero frequency, so there is no AC "
                "steady state to find." % element.name)
        return Cx(0, -Fraction(1) / product)
    raise CircuitError("%s has no impedance" % element.name)


class PhasorSystem(object):
    """Nodal analysis over Gaussian rationals at one frequency."""

    def __init__(self, circuit, omega, phasors):
        self.circuit = circuit
        self.omega = to_fraction(omega)
        self.phasors = phasors

        self.node_names = circuit.free_nodes
        self.node_index = {n: i for i, n in enumerate(self.node_names)}

        # Sources and shorts still need their own current unknown.
        self.current_elements = [e for e in circuit.elements
                                 if self._needs_current(e)]
        offset = len(self.node_names)
        self.current_index = {e.name: offset + i
                              for i, e in enumerate(self.current_elements)}
        self.size = len(self.node_names) + len(self.current_elements)
        self.labels = (["V(%s)" % n for n in self.node_names] +
                       ["I(%s)" % e.name for e in self.current_elements])

        self.matrix = [[ZERO] * self.size for _ in range(self.size)]
        self.rhs = [ZERO] * self.size
        self._build()

    def _needs_current(self, element):
        if element.kind in ("V", "E", "H", "OPAMP"):
            return True
        if element.kind == "SW":
            return element.state_after == "closed"
        return False

    def _col(self, node):
        return None if is_ground(node) else self.node_index[node]

    def _add(self, row, col, value):
        if row is None or col is None:
            return
        self.matrix[row][col] = self.matrix[row][col] + value

    def _inject(self, tail, head, current):
        t, h = self._col(tail), self._col(head)
        if t is not None:
            self.rhs[t] = self.rhs[t] - current
        if h is not None:
            self.rhs[h] = self.rhs[h] + current

    def _build(self):
        for element in self.circuit.elements:
            kind = element.kind
            if kind in ("R", "L", "C"):
                self._stamp_admittance(element)
            elif kind == "I":
                self._inject(element.nodes[0], element.nodes[1],
                             self.phasors[element.name])
            elif kind == "SW" and element.state_after == "open":
                continue
            elif self._needs_current(element):
                self._stamp_current_unknown(element)
            elif kind == "G":
                gain = Cx(element.gain, 0)
                for node, sign in self._terminals(element):
                    row = self._col(node)
                    self._add(row, self._col(element.ctrl_nodes[0]), sign * gain)
                    self._add(row, self._col(element.ctrl_nodes[1]),
                              sign * -gain)
            elif kind == "F":
                gain = Cx(element.gain, 0)
                for node, sign in self._terminals(element):
                    row = self._col(node)
                    for col, coefficient in self._current_form(
                            self.circuit.get(element.ctrl_element)).items():
                        self._add(row, col, sign * gain * coefficient)
                known = self._known_current(self.circuit.get(element.ctrl_element))
                if not known.is_zero:
                    self._inject(element.nodes[0], element.nodes[1], gain * known)

    def _terminals(self, element):
        if element.kind == "OPAMP":
            return [(element.nodes[2], -ONE)]
        return [(element.nodes[0], ONE), (element.nodes[1], -ONE)]

    def _stamp_admittance(self, element):
        y = ONE / impedance(element, self.omega)
        a, b = (self._col(n) for n in element.nodes)
        self._add(a, a, y)
        self._add(a, b, -y)
        self._add(b, a, -y)
        self._add(b, b, y)

    def _stamp_current_unknown(self, element):
        k = self.current_index[element.name]
        for node, sign in self._terminals(element):
            self._add(self._col(node), k, sign)

        row = k
        if element.kind == "OPAMP":
            self._add(row, self._col(element.nodes[0]), ONE)
            self._add(row, self._col(element.nodes[1]), -ONE)
            return

        self._add(row, self._col(element.nodes[0]), ONE)
        self._add(row, self._col(element.nodes[1]), -ONE)

        if element.kind == "V":
            self.rhs[row] = self.phasors[element.name]
        elif element.kind == "E":
            gain = Cx(element.gain, 0)
            self._add(row, self._col(element.ctrl_nodes[0]), -gain)
            self._add(row, self._col(element.ctrl_nodes[1]), gain)
        elif element.kind == "H":
            gain = Cx(element.gain, 0)
            control = self.circuit.get(element.ctrl_element)
            for col, coefficient in self._current_form(control).items():
                self._add(row, col, -gain * coefficient)
            known = self._known_current(control)
            if not known.is_zero:
                self.rhs[row] = self.rhs[row] + gain * known

    def _current_form(self, element):
        if self._needs_current(element):
            return {self.current_index[element.name]: ONE}
        if element.kind in ("R", "L", "C"):
            y = ONE / impedance(element, self.omega)
            form = {}
            a, b = (self._col(n) for n in element.nodes)
            if a is not None:
                form[a] = form.get(a, ZERO) + y
            if b is not None:
                form[b] = form.get(b, ZERO) - y
            return form
        if element.kind == "G":
            gain = Cx(element.gain, 0)
            form = {}
            cp, cm = (self._col(n) for n in element.ctrl_nodes)
            if cp is not None:
                form[cp] = form.get(cp, ZERO) + gain
            if cm is not None:
                form[cm] = form.get(cm, ZERO) - gain
            return form
        if element.kind == "F":
            base = self._current_form(self.circuit.get(element.ctrl_element))
            gain = Cx(element.gain, 0)
            return {col: gain * value for col, value in base.items()}
        return {}

    def _known_current(self, element):
        if element.kind == "I":
            return self.phasors[element.name]
        if element.kind == "F":
            return (Cx(element.gain, 0) *
                    self._known_current(self.circuit.get(element.ctrl_element)))
        return ZERO

    def solve(self):
        x = _solve_complex(self.matrix, self.rhs)
        return PhasorSolution(self, x)


def _solve_complex(matrix, rhs):
    """Exact Gauss-Jordan over Gaussian rationals."""
    n = len(matrix)
    if n == 0:
        return []
    augmented = [list(matrix[i]) + [rhs[i]] for i in range(n)]
    pivot_of_column = [None] * n
    row = 0
    for col in range(n):
        pivot = None
        for r in range(row, n):
            if not augmented[r][col].is_zero:
                pivot = r
                break
        if pivot is None:
            continue
        augmented[row], augmented[pivot] = augmented[pivot], augmented[row]
        scale = augmented[row][col]
        augmented[row] = [entry / scale for entry in augmented[row]]
        for r in range(n):
            if r != row and not augmented[r][col].is_zero:
                factor = augmented[r][col]
                augmented[r] = [a - factor * b
                                for a, b in zip(augmented[r], augmented[row])]
        pivot_of_column[col] = row
        row += 1
        if row == n:
            break
    if row < n:
        free = [c for c in range(n) if pivot_of_column[c] is None]
        raise SingularSystem("the AC equations have no unique solution",
                             free_columns=free)
    return [augmented[pivot_of_column[c]][n] for c in range(n)]


class PhasorSolution(object):
    def __init__(self, system, x):
        self.system = system
        self.x = x

    def node_voltage(self, node):
        if is_ground(node):
            return ZERO
        return self.x[self.system.node_index[node]]

    def element_voltage(self, element):
        if element.kind == "OPAMP":
            return self.node_voltage(element.nodes[2])
        return (self.node_voltage(element.nodes[0]) -
                self.node_voltage(element.nodes[1]))

    def element_current(self, element):
        system = self.system
        if system._needs_current(element):
            return self.x[system.current_index[element.name]]
        if element.kind in ("R", "L", "C"):
            return self.element_voltage(element) / impedance(element, system.omega)
        if element.kind == "I":
            return system.phasors[element.name]
        if element.kind == "SW":
            return ZERO
        if element.kind == "G":
            return Cx(element.gain, 0) * (
                self.node_voltage(element.ctrl_nodes[0]) -
                self.node_voltage(element.ctrl_nodes[1]))
        if element.kind == "F":
            return Cx(element.gain, 0) * self.element_current(
                system.circuit.get(element.ctrl_element))
        raise CircuitError("cannot report the current through %s" % element.name)

    def impedance_at(self, element):
        """The impedance a source looks out into.

        Both element quantities use the passive convention, where current runs
        into the + terminal, but a source drives current the other way. Negating
        turns V/I at its own terminals into the impedance of everything else.
        """
        current = self.element_current(element)
        if current.is_zero:
            return None
        try:
            return -(self.element_voltage(element) / current)
        except ZeroDivisionError:
            return None


class PhasorReport(object):
    def __init__(self, omega):
        self.omega = omega
        self.solution = None
        self.impedances = {}
        self.notes = []


def analyse_ac(circuit, omega, phasors=None):
    """Solve the AC steady state at one angular frequency, in rad/s."""
    circuit.validate()
    omega = to_fraction(omega)
    if omega <= 0:
        raise CircuitError("the frequency must be greater than zero")

    sources = circuit.of_kind("V", "I")
    if not sources:
        raise CircuitError("there are no sources to drive the circuit")

    resolved = {}
    for element in sources:
        given = (phasors or {}).get(element.name)
        if isinstance(given, Cx):
            resolved[element.name] = given
        elif given is not None:
            resolved[element.name] = polar_to_rect(given[0], given[1] or 0)
        elif element.ac is not None or element.phase is not None:
            magnitude = element.ac if element.ac is not None else element.after
            resolved[element.name] = polar_to_rect(magnitude, element.phase or 0)
        else:
            # No AC phasor stated, so take the t > 0 value at zero phase.
            resolved[element.name] = Cx(element.after, 0)

    report = PhasorReport(omega)
    system = PhasorSystem(circuit, omega, resolved)
    report.solution = system.solve()
    report.system = system
    report.phasors = resolved

    for element in sources:
        seen = report.solution.impedance_at(element)
        if seen is not None:
            report.impedances[element.name] = seen

    for element in circuit.of_kind("SW"):
        report.notes.append(
            "%s is held %s: AC steady state describes one fixed circuit, so the "
            "t > 0 position is the one used." % (element.name, element.state_after))
    if circuit.of_kind("OPAMP"):
        report.notes.append(
            "Op-amps are treated as ideal at every frequency, with no gain "
            "roll-off, so this is the textbook answer rather than what real "
            "silicon would do.")
    return report
