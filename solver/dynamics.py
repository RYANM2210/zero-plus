"""Natural frequencies and the closed-form response.

The initial-condition solver already knows how to turn a set of stored values
into their own rates of change: hand the t = 0+ system a state and it returns
di_L/dt and dv_C/dt.  That map is linear, so probing it with unit states
recovers the state matrix directly, without ever writing the differential
equations out by hand:

    dx/dt = A x + f        x = the inductor currents and capacitor voltages

Column k of A is what dx/dt comes to when only storage element k holds one unit
and every source is off.  f is what dx/dt comes to with nothing stored and the
sources at their t > 0 values.  Both are recovered from the same tested MNA
code, so the dynamics cannot disagree with the initial conditions.

From A comes the characteristic polynomial, and from that alpha, omega-nought
and the damping.  Those three are exact rationals for any circuit: alpha is
half the negated trace, omega-nought squared is the determinant, and which side
of zero the discriminant falls on decides over-, under- or critical damping
with no rounding involved.  The roots themselves may be irrational, and are
marked as approximate when they are.
"""

from fractions import Fraction

from exact import format_number

DAMPING_LABELS = {
    "overdamped": "overdamped",
    "critical": "critically damped",
    "underdamped": "underdamped",
    "first-order": "first order",
}


class Num(object):
    """A quantity that is either exact or an unavoidable decimal.

    Square roots of rationals are usually irrational, so the reports need to be
    able to say which numbers are precise and which are not.
    """

    def __init__(self, exact=None, approx=None):
        self.exact = exact
        self.approx = float(exact) if exact is not None else approx

    @property
    def is_exact(self):
        return self.exact is not None

    def __str__(self):
        if self.is_exact:
            return format_number(self.exact)
        if self.approx is None:
            return "?"
        return "%.6g" % self.approx

    def __repr__(self):
        return "Num(%s)" % self


def exact_sqrt(value):
    """The exact square root of a rational, or None when it is irrational."""
    if value < 0:
        return None
    numerator = _integer_sqrt(value.numerator)
    denominator = _integer_sqrt(value.denominator)
    if numerator is None or denominator is None:
        return None
    return Fraction(numerator, denominator)


def _integer_sqrt(n):
    if n < 0:
        return None
    root = int(n ** 0.5)
    # Correct for floating point drift near the boundary on large integers.
    for candidate in (root - 1, root, root + 1):
        if candidate >= 0 and candidate * candidate == n:
            return candidate
    return None


def root_of(value):
    """sqrt of a non-negative rational as a Num, exact when it can be."""
    precise = exact_sqrt(value)
    if precise is not None:
        return Num(exact=precise)
    return Num(approx=float(value) ** 0.5)


# --------------------------------------------------------------------------
# state matrix
# --------------------------------------------------------------------------

def state_space(circuit, system, source_values):
    """Recover A and f in dx/dt = A x + f by probing the t = 0+ system."""
    storage = circuit.of_kind("L", "C")
    size = len(storage)
    zero_sources = {e.name: Fraction(0) for e in circuit.of_kind("V", "I")}

    def rates(solution):
        out = []
        for element in storage:
            if element.kind == "L":
                out.append(solution.element_voltage(element) / element.value)
            else:
                out.append(solution.element_current(element) / element.value)
        return out

    matrix = [[Fraction(0)] * size for _ in range(size)]
    for column, target in enumerate(storage):
        unit = {e.name: (Fraction(1) if e.name == target.name else Fraction(0))
                for e in storage}
        column_rates = rates(system.solve(zero_sources, unit))
        for row in range(size):
            matrix[row][column] = column_rates[row]

    resting = {e.name: Fraction(0) for e in storage}
    forcing = rates(system.solve(source_values, resting))
    return matrix, forcing


def characteristic_polynomial(matrix):
    """Coefficients of det(sI - A), highest power first, by Faddeev-LeVerrier.

    Exact throughout, and it works at any order, which keeps the third-order
    case honest even though no closed form is produced for it.
    """
    size = len(matrix)
    coefficients = [Fraction(1)]
    current = [[Fraction(1) if r == c else Fraction(0) for c in range(size)]
               for r in range(size)]

    for step in range(1, size + 1):
        if step > 1:
            current = _add_diagonal(_multiply(matrix, current), coefficients[-1])
        trace = sum(_multiply(matrix, current)[i][i] for i in range(size))
        coefficients.append(-trace / step)
    return coefficients


def _multiply(left, right):
    size = len(left)
    return [[sum(left[r][k] * right[k][c] for k in range(size))
             for c in range(size)] for r in range(size)]


def _add_diagonal(matrix, value):
    return [[matrix[r][c] + (value if r == c else Fraction(0))
             for c in range(len(matrix))] for r in range(len(matrix))]


# --------------------------------------------------------------------------
# damping
# --------------------------------------------------------------------------

class Dynamics(object):
    def __init__(self, order):
        self.order = order
        self.matrix = None
        self.forcing = None
        self.polynomial = []
        self.alpha = None            # exact
        self.omega0_squared = None   # exact
        self.discriminant = None     # exact
        self.omega0 = None           # Num
        self.omega_d = None          # Num, underdamped only
        self.damping = None
        self.roots = []              # list of Num, or (real, imag) pairs
        self.tau = None              # Num, first order only
        self.stable = False
        self.zeta = None             # Num, damping ratio
        self.notes = []


def analyse_dynamics(circuit, system, source_values):
    storage = circuit.of_kind("L", "C")
    order = len(storage)
    dynamics = Dynamics(order)
    if order == 0:
        return dynamics

    dynamics.matrix, dynamics.forcing = state_space(circuit, system, source_values)
    dynamics.polynomial = characteristic_polynomial(dynamics.matrix)

    if order == 1:
        rate = dynamics.matrix[0][0]
        dynamics.damping = "first-order"
        dynamics.roots = [Num(exact=rate)]
        dynamics.stable = rate < 0
        if rate != 0:
            dynamics.tau = Num(exact=-Fraction(1) / rate)
        else:
            dynamics.notes.append(
                "The single natural frequency is zero, so nothing decays: this "
                "circuit integrates rather than settling.")
        return dynamics

    if order != 2:
        dynamics.notes.append(
            "This circuit is order %d. Its characteristic polynomial is exact "
            "and shown below, but a closed-form response is only worked out for "
            "first- and second-order circuits." % order)
        return dynamics

    trace = dynamics.matrix[0][0] + dynamics.matrix[1][1]
    determinant = (dynamics.matrix[0][0] * dynamics.matrix[1][1] -
                   dynamics.matrix[0][1] * dynamics.matrix[1][0])

    # s^2 + 2*alpha*s + omega0^2 = 0
    dynamics.alpha = -trace / 2
    dynamics.omega0_squared = determinant
    dynamics.discriminant = dynamics.alpha ** 2 - determinant
    dynamics.stable = dynamics.alpha > 0 and determinant > 0

    if determinant >= 0:
        dynamics.omega0 = root_of(determinant)
        if determinant > 0:
            ratio = dynamics.alpha / _as_float_safe(dynamics.omega0)
            dynamics.zeta = Num(approx=ratio) if not _is_exactish(dynamics.omega0) \
                else Num(exact=dynamics.alpha / dynamics.omega0.exact)

    if dynamics.discriminant > 0:
        dynamics.damping = "overdamped"
        spread = root_of(dynamics.discriminant)
        dynamics.roots = [_combine(-dynamics.alpha, spread, +1),
                          _combine(-dynamics.alpha, spread, -1)]
    elif dynamics.discriminant == 0:
        dynamics.damping = "critical"
        dynamics.roots = [Num(exact=-dynamics.alpha), Num(exact=-dynamics.alpha)]
    else:
        dynamics.damping = "underdamped"
        dynamics.omega_d = root_of(-dynamics.discriminant)
        dynamics.roots = [(Num(exact=-dynamics.alpha), dynamics.omega_d),
                          (Num(exact=-dynamics.alpha),
                           Num(exact=-dynamics.omega_d.exact)
                           if dynamics.omega_d.is_exact
                           else Num(approx=-dynamics.omega_d.approx))]

    if not dynamics.stable:
        if determinant <= 0:
            dynamics.notes.append(
                "This circuit has no stable resting point, so there is no final "
                "value for the response to settle on.")
        else:
            dynamics.notes.append(
                "The natural frequencies do not decay, so this response does not "
                "settle. A circuit with no resistance in the loop behaves this way.")
    return dynamics


def _as_float_safe(num):
    return num.approx if num.approx else 1.0


def _is_exactish(num):
    return num.is_exact and num.exact != 0


def _combine(base, spread, sign):
    if spread.is_exact:
        return Num(exact=base + sign * spread.exact)
    return Num(approx=float(base) + sign * spread.approx)


def _is_negative(value):
    if value.is_exact:
        return value.exact < 0
    return value.approx is not None and value.approx < 0


def _magnitude(value):
    if value.is_exact:
        return format_number(abs(value.exact))
    return "%.6g" % abs(value.approx)


def _first(value, symbol):
    """The opening term of a sum, keeping any minus sign attached."""
    return "%s%s%s" % ("-" if _is_negative(value) else "",
                       _magnitude(value), symbol)


def _next(value, symbol):
    """A following term, rendered as ' + 3*x' or ' - 3*x'."""
    return " %s %s%s" % ("-" if _is_negative(value) else "+",
                         _magnitude(value), symbol)


def _is_zero(value):
    if value.is_exact:
        return value.exact == 0
    return value.approx == 0


def _sum_terms(pairs):
    """Join (coefficient, symbol) terms, leaving out any that are zero."""
    live = [(value, symbol) for value, symbol in pairs if not _is_zero(value)]
    if not live:
        return "0"
    out = _first(live[0][0], live[0][1])
    for value, symbol in live[1:]:
        out += _next(value, symbol)
    return out


def _tail(final, body):
    """The final value, then the natural part, with its sign folded in.

    Either half can vanish: a quantity that never moves has no natural part,
    and one that decays to nothing has no forced part.
    """
    head = format_number(final)
    if not body or body == "0":
        return head
    if final == 0:
        return body
    if body.startswith("-"):
        return "%s - %s" % (head, body[1:])
    return "%s + %s" % (head, body)


# --------------------------------------------------------------------------
# closed-form response for one quantity
# --------------------------------------------------------------------------

class Response(object):
    """y(t) for one element quantity, as terms plus a rendered formula."""

    def __init__(self, label, unit):
        self.label = label
        self.unit = unit
        self.final = None
        self.constants = []
        self.formula = None
        self.exact = True


def response_for(dynamics, label, unit, initial, derivative, final):
    """Fit the natural response to one variable.

    Every circuit variable rings at the same natural frequencies; only the
    constants differ, and those come from the value and slope at 0+ against the
    final value -- all three of which the initial-condition solver already has.
    """
    if dynamics.order not in (1, 2) or dynamics.damping is None:
        return None
    if final is None:
        return None

    response = Response(label, unit)
    response.final = final
    offset = initial - final

    if dynamics.order == 1:
        if dynamics.tau is None:
            return None
        response.exact = dynamics.tau.is_exact
        response.constants = [("A", Num(exact=offset))]
        response.formula = "%s(t) = %s" % (
            label,
            _tail(final, _first(Num(exact=offset),
                                "*e^(-t/%s)" % dynamics.tau)))
        return response

    if dynamics.damping == "overdamped":
        s1, s2 = dynamics.roots[0], dynamics.roots[1]
        if s1.is_exact and s2.is_exact and s1.exact != s2.exact:
            gap = s1.exact - s2.exact
            a1 = (derivative - s2.exact * offset) / gap
            a2 = offset - a1
            first, second = Num(exact=a1), Num(exact=a2)
            response.exact = True
        else:
            gap = s1.approx - s2.approx
            if gap == 0:
                return None
            a1 = (float(derivative) - s2.approx * float(offset)) / gap
            first, second = Num(approx=a1), Num(approx=float(offset) - a1)
            response.exact = False
        response.constants = [("A1", first), ("A2", second)]
        body = _sum_terms([(first, "*e^(%s*t)" % s1),
                           (second, "*e^(%s*t)" % s2)])
        response.formula = "%s(t) = %s" % (label, _tail(final, body))
        return response

    if dynamics.damping == "critical":
        alpha = dynamics.alpha
        a1 = offset
        a2 = derivative + alpha * offset
        response.exact = True
        response.constants = [("A1", Num(exact=a1)), ("A2", Num(exact=a2))]
        inner = _sum_terms([(Num(exact=a1), ""), (Num(exact=a2), "*t")])
        response.formula = "%s(t) = %s" % (
            label, _tail(final, "" if inner == "0" else
                         "(%s)*e^(-%s*t)" % (inner, format_number(alpha))))
        return response

    # underdamped
    alpha = dynamics.alpha
    omega_d = dynamics.omega_d
    b1 = offset
    numerator = derivative + alpha * offset
    if omega_d.is_exact and omega_d.exact != 0:
        b2 = Num(exact=numerator / omega_d.exact)
        response.exact = True
    else:
        if not omega_d.approx:
            return None
        b2 = Num(approx=float(numerator) / omega_d.approx)
        response.exact = False
    response.constants = [("B1", Num(exact=b1)), ("B2", b2)]
    inner = _sum_terms([(Num(exact=b1), "*cos(%s*t)" % omega_d),
                        (b2, "*sin(%s*t)" % omega_d)])
    response.formula = "%s(t) = %s" % (
        label, _tail(final, "" if inner == "0" else
                     "e^(-%s*t)*[%s]" % (format_number(alpha), inner)))
    return response
