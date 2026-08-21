"""Exact rational linear algebra.

Everything here is Fraction-based: no floating point ever touches a component
value or a solved unknown.  The algorithms are deliberately simple (textbook
Gauss-Jordan) so that the JavaScript port in ../web can mirror them line for
line and be cross-checked against this module.
"""

from fractions import Fraction


class SingularSystem(Exception):
    """The MNA matrix has no unique solution.

    ``dependent_rows`` lists the equation indices that collapsed during
    elimination; ``free_columns`` lists the unknowns they failed to pin down.
    Analysis turns these into a human diagnosis.
    """

    def __init__(self, message, dependent_rows=None, free_columns=None):
        super().__init__(message)
        self.dependent_rows = dependent_rows or []
        self.free_columns = free_columns or []


# Engineering suffixes, following the SPICE convention where m is milli and
# Meg is mega.  Values stay exact: 4.7k is 4700, 1u is 1/1000000.
SUFFIXES = [
    ("meg", Fraction(10) ** 6),
    ("t", Fraction(10) ** 12),
    ("g", Fraction(10) ** 9),
    ("k", Fraction(10) ** 3),
    ("m", Fraction(1, 10 ** 3)),
    ("u", Fraction(1, 10 ** 6)),
    ("n", Fraction(1, 10 ** 9)),
    ("p", Fraction(1, 10 ** 12)),
    ("f", Fraction(1, 10 ** 15)),
]


def to_fraction(value):
    """Coerce user input to an exact Fraction.

    Strings are parsed rather than floated, so "0.2" and "1/5" both land on
    exactly 1/5 instead of the binary approximation of 0.2.  Engineering
    suffixes such as 4k7-style "4.7k", "10u" and "1Meg" are accepted too.
    """
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("empty numeric value")
        lowered = text.lower()
        for suffix, scale in SUFFIXES:
            if lowered.endswith(suffix) and len(lowered) > len(suffix):
                head = text[:-len(suffix)].strip()
                try:
                    return Fraction(head) * scale
                except (ValueError, ZeroDivisionError):
                    break
        return Fraction(text)
    if isinstance(value, float):
        # Only reachable if a caller hands us a float; go through the decimal
        # string so 0.2 means 1/5 and not 3602879701896397/18014398509481984.
        return Fraction(repr(value))
    raise TypeError("cannot convert %r to an exact number" % (value,))


def zeros(rows, cols):
    return [[Fraction(0)] * cols for _ in range(rows)]


def solve(matrix, rhs):
    """Solve A x = b exactly.  Returns the solution vector.

    ``matrix`` is a list of rows, ``rhs`` a list of the same length.  Raises
    SingularSystem when A is not invertible.
    """
    n = len(matrix)
    if n == 0:
        return []
    if any(len(row) != n for row in matrix):
        raise ValueError("matrix must be square")
    if len(rhs) != n:
        raise ValueError("right-hand side length does not match matrix")

    # Work on an augmented copy so the caller's matrix survives untouched --
    # analysis re-solves the same matrix with several different RHS vectors.
    aug = [list(matrix[i]) + [rhs[i]] for i in range(n)]

    pivot_of_column = [None] * n
    row = 0
    for col in range(n):
        pivot = None
        for r in range(row, n):
            if aug[r][col] != 0:
                pivot = r
                break
        if pivot is None:
            continue
        aug[row], aug[pivot] = aug[pivot], aug[row]

        scale = aug[row][col]
        aug[row] = [entry / scale for entry in aug[row]]

        for r in range(n):
            if r != row and aug[r][col] != 0:
                factor = aug[r][col]
                aug[r] = [a - factor * b for a, b in zip(aug[r], aug[row])]

        pivot_of_column[col] = row
        row += 1
        if row == n:
            break

    if row < n:
        free = [c for c in range(n) if pivot_of_column[c] is None]
        dependent = list(range(row, n))
        raise SingularSystem(
            "the circuit equations do not have a unique solution",
            dependent_rows=dependent,
            free_columns=free,
        )

    solution = [Fraction(0)] * n
    for col in range(n):
        solution[col] = aug[pivot_of_column[col]][n]
    return solution


def format_number(value, max_denominator=10000):
    """Render a Fraction the way a student would write it in an answer.

    Exact integers stay integers, short fractions stay fractions, and anything
    with an ugly denominator also gets a decimal so the magnitude is readable.
    """
    value = to_fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    decimal = float(value)
    if value.denominator <= max_denominator:
        # A terminating decimal is friendlier than a fraction when it is short.
        text = ("%.6f" % decimal).rstrip("0").rstrip(".")
        if Fraction(text) == value and len(text) <= 8:
            return text
        return "%d/%d (%.4f)" % (value.numerator, value.denominator, decimal)
    return "%.6g" % decimal
