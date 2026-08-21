"""Circuit description: elements, nodes, and the netlist text format.

The node order of an element fixes its sign convention, and the conventions
here are chosen to match how the symbols are drawn on a schematic:

  R, L, C, V, SW     nodes are (n+, n-).  v = V(n+) - V(n-), and the current i
                     flows from n+ to n- *through* the element.  That is the
                     passive sign convention: current enters the + terminal.

  I, G, F  (sources) nodes are (tail, head), matching the arrow printed on the
                     symbol.  Current flows tail -> head inside the source, so
                     it is injected into the head node.

  OPAMP              nodes are (in+, in-, out).

Independent sources carry two values: what they put out for t < 0 and what they
put out for t > 0.  A step source 4u(t) is simply before=0, after=4.  Switches
work the same way, with a state on each side of t = 0.
"""

from fractions import Fraction

from exact import to_fraction

GROUND_NAMES = {"0", "gnd", "GND", "ground"}

# kind -> (number of nodes, needs a control pair, needs a control element)
KIND_SPEC = {
    "R": (2, False, False),
    "L": (2, False, False),
    "C": (2, False, False),
    "V": (2, False, False),
    "I": (2, False, False),
    "SW": (2, False, False),
    "E": (2, True, False),   # VCVS  v = gain * v_ctrl
    "G": (2, True, False),   # VCCS  i = gain * v_ctrl
    "H": (2, False, True),   # CCVS  v = gain * i_ctrl
    "F": (2, False, True),   # CCCS  i = gain * i_ctrl
    "OPAMP": (3, False, False),
}

PRETTY_KIND = {
    "R": "resistor",
    "L": "inductor",
    "C": "capacitor",
    "V": "voltage source",
    "I": "current source",
    "SW": "switch",
    "E": "VCVS",
    "G": "VCCS",
    "H": "CCVS",
    "F": "CCCS",
    "OPAMP": "op-amp",
}

UNITS = {"R": "ohm", "L": "H", "C": "F", "V": "V", "I": "A"}


class CircuitError(Exception):
    """A problem with the circuit description itself, not with solving it."""


class Element(object):
    def __init__(self, kind, name, nodes, value=None, before=None, after=None,
                 ctrl_nodes=None, ctrl_element=None, gain=None,
                 state_before=None, state_after=None, ic=None):
        self.kind = kind
        self.name = name
        self.nodes = list(nodes)
        self.value = None if value is None else to_fraction(value)
        self.before = None if before is None else to_fraction(before)
        self.after = None if after is None else to_fraction(after)
        self.ctrl_nodes = list(ctrl_nodes) if ctrl_nodes else None
        self.ctrl_element = ctrl_element
        self.gain = None if gain is None else to_fraction(gain)
        self.state_before = state_before
        self.state_after = state_after
        self.ic = None if ic is None else to_fraction(ic)

    @property
    def is_storage(self):
        return self.kind in ("L", "C")

    @property
    def pretty(self):
        return PRETTY_KIND.get(self.kind, self.kind)

    def source_value(self, window):
        """Output of an independent source in the given time window."""
        return self.before if window == "before" else self.after

    def state(self, window):
        """Switch position in the given time window."""
        return self.state_before if window == "before" else self.state_after

    def __repr__(self):
        return "<%s %s %s>" % (self.kind, self.name, ":".join(self.nodes))


class Circuit(object):
    def __init__(self, title="circuit"):
        self.title = title
        self.elements = []
        self._by_name = {}

    def add(self, element):
        if element.name in self._by_name:
            raise CircuitError("duplicate element name %r" % element.name)
        self._by_name[element.name] = element
        self.elements.append(element)
        return element

    def get(self, name):
        if name not in self._by_name:
            raise CircuitError("no element named %r" % name)
        return self._by_name[name]

    def has(self, name):
        return name in self._by_name

    def of_kind(self, *kinds):
        return [e for e in self.elements if e.kind in kinds]

    @property
    def nodes(self):
        """Every node name mentioned by an element, ground first."""
        seen = []
        for element in self.elements:
            for node in element.nodes:
                if node not in seen:
                    seen.append(node)
            for node in (element.ctrl_nodes or []):
                if node not in seen:
                    seen.append(node)
        ground = [n for n in seen if is_ground(n)]
        other = sorted((n for n in seen if not is_ground(n)), key=_node_sort_key)
        return ground + other

    @property
    def free_nodes(self):
        """Nodes that get an unknown voltage, i.e. everything except ground."""
        return [n for n in self.nodes if not is_ground(n)]

    def validate(self):
        if not self.elements:
            raise CircuitError("the circuit is empty")
        if not any(is_ground(n) for element in self.elements
                   for n in element.nodes):
            raise CircuitError(
                "no ground node: mark one node as 0 so voltages have a reference")
        for element in self.elements:
            spec = KIND_SPEC.get(element.kind)
            if spec is None:
                raise CircuitError("unknown element kind %r" % element.kind)
            node_count, needs_ctrl_nodes, needs_ctrl_element = spec
            if len(element.nodes) != node_count:
                raise CircuitError("%s needs %d nodes, got %d"
                                   % (element.name, node_count, len(element.nodes)))
            if len(set(element.nodes)) != len(element.nodes):
                raise CircuitError("%s has both terminals on the same node"
                                   % element.name)
            if element.kind in ("R", "L", "C"):
                if element.value is None:
                    raise CircuitError("%s has no value" % element.name)
                if element.value <= 0:
                    raise CircuitError("%s must have a positive value (got %s)"
                                       % (element.name, element.value))
            if element.kind in ("V", "I"):
                if element.before is None or element.after is None:
                    raise CircuitError("%s needs a t<0 and a t>0 value"
                                       % element.name)
            if element.kind == "SW":
                for state in (element.state_before, element.state_after):
                    if state not in ("open", "closed"):
                        raise CircuitError(
                            "%s state must be open or closed, got %r"
                            % (element.name, state))
            if needs_ctrl_nodes and not element.ctrl_nodes:
                raise CircuitError("%s needs a controlling node pair"
                                   % element.name)
            if needs_ctrl_element:
                if not element.ctrl_element:
                    raise CircuitError("%s needs a controlling element"
                                       % element.name)
                if not self.has(element.ctrl_element):
                    raise CircuitError("%s is controlled by %r, which does not exist"
                                       % (element.name, element.ctrl_element))
            if element.kind in ("E", "G", "H", "F") and element.gain is None:
                raise CircuitError("%s has no gain" % element.name)
        self._check_control_cycles()
        return self

    def _check_control_cycles(self):
        """A CCCS chain that feeds back into itself has no defined current."""
        for element in self.of_kind("F", "H"):
            seen = set()
            cursor = element
            while cursor is not None and cursor.kind in ("F", "H"):
                if cursor.name in seen:
                    raise CircuitError(
                        "current-control loop involving %s: its controlling "
                        "current depends on itself" % element.name)
                seen.add(cursor.name)
                cursor = self.get(cursor.ctrl_element)

    def switches_change(self):
        return any(e.state_before != e.state_after for e in self.of_kind("SW"))

    def sources_change(self):
        return any(e.before != e.after for e in self.of_kind("V", "I"))


def is_ground(node):
    return node in GROUND_NAMES


def _node_sort_key(node):
    """Sort node 2 before node 10, but still cope with names like 'out'."""
    return (0, int(node), "") if node.isdigit() else (1, 0, node)


# --------------------------------------------------------------------------
# netlist text format
# --------------------------------------------------------------------------

def _parse_source_spec(name, tokens):
    """Read the value part of an independent source.

    Accepted forms:
        12              constant 12 (same before and after)
        dc 12           the same thing, spelled out
        step 4          0 before t=0, 4 after, i.e. 4u(t)
        0 4             explicit before / after pair
    """
    if not tokens:
        raise CircuitError("%s has no value" % name)
    head = tokens[0].lower()
    if head == "dc":
        if len(tokens) != 2:
            raise CircuitError("%s: dc takes one value" % name)
        value = to_fraction(tokens[1])
        return value, value
    if head in ("step", "u"):
        if len(tokens) != 2:
            raise CircuitError("%s: step takes one value" % name)
        return Fraction(0), to_fraction(tokens[1])
    if len(tokens) == 1:
        value = to_fraction(tokens[0])
        return value, value
    if len(tokens) == 2:
        return to_fraction(tokens[0]), to_fraction(tokens[1])
    raise CircuitError("%s: cannot read the value %r" % (name, " ".join(tokens)))


def _element_kind(name):
    upper = name.upper()
    if upper.startswith("SW"):
        return "SW"
    if upper.startswith("OP") or upper.startswith("OA"):
        return "OPAMP"
    letter = upper[0]
    if letter in ("R", "L", "C", "V", "I", "E", "G", "H", "F"):
        return letter
    raise CircuitError("cannot tell what kind of element %r is" % name)


def parse_netlist(text, title="circuit"):
    circuit = Circuit(title)
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if not line:
            continue
        if line.lower().startswith(".title "):
            circuit.title = line[7:].strip()
            continue
        if line.startswith("."):
            continue
        tokens = line.split()
        name = tokens[0]
        try:
            kind = _element_kind(name)
            rest = tokens[1:]
            if kind in ("R", "L", "C"):
                if len(rest) < 3:
                    raise CircuitError("%s needs two nodes and a value" % name)
                ic = None
                for extra in rest[3:]:
                    if extra.lower().startswith("ic="):
                        ic = to_fraction(extra[3:])
                    else:
                        raise CircuitError("%s: unexpected %r" % (name, extra))
                circuit.add(Element(kind, name, rest[:2], value=rest[2], ic=ic))
            elif kind in ("V", "I"):
                if len(rest) < 3:
                    raise CircuitError("%s needs two nodes and a value" % name)
                before, after = _parse_source_spec(name, rest[2:])
                circuit.add(Element(kind, name, rest[:2],
                                    before=before, after=after))
            elif kind == "SW":
                if len(rest) != 4:
                    raise CircuitError(
                        "%s needs two nodes then its t<0 and t>0 states" % name)
                circuit.add(Element(kind, name, rest[:2],
                                    state_before=rest[2].lower(),
                                    state_after=rest[3].lower()))
            elif kind in ("E", "G"):
                if len(rest) != 5:
                    raise CircuitError(
                        "%s needs two nodes, two control nodes and a gain" % name)
                circuit.add(Element(kind, name, rest[:2],
                                    ctrl_nodes=rest[2:4], gain=rest[4]))
            elif kind in ("H", "F"):
                if len(rest) != 4:
                    raise CircuitError(
                        "%s needs two nodes, a controlling element and a gain"
                        % name)
                circuit.add(Element(kind, name, rest[:2],
                                    ctrl_element=rest[2], gain=rest[3]))
            elif kind == "OPAMP":
                if len(rest) != 3:
                    raise CircuitError("%s needs in+, in- and out nodes" % name)
                circuit.add(Element(kind, name, rest))
        except CircuitError as error:
            raise CircuitError("line %d: %s" % (lineno, error))
    return circuit.validate()


def to_netlist(circuit):
    """Round-trip a circuit back to netlist text (also the web save format)."""
    lines = [".title %s" % circuit.title]
    for e in circuit.elements:
        if e.kind in ("R", "L", "C"):
            row = "%s %s %s %s" % (e.name, e.nodes[0], e.nodes[1], _num(e.value))
            if e.ic is not None:
                row += " ic=%s" % _num(e.ic)
        elif e.kind in ("V", "I"):
            if e.before == e.after:
                spec = "dc %s" % _num(e.after)
            elif e.before == 0:
                spec = "step %s" % _num(e.after)
            else:
                spec = "%s %s" % (_num(e.before), _num(e.after))
            row = "%s %s %s %s" % (e.name, e.nodes[0], e.nodes[1], spec)
        elif e.kind == "SW":
            row = "%s %s %s %s %s" % (e.name, e.nodes[0], e.nodes[1],
                                      e.state_before, e.state_after)
        elif e.kind in ("E", "G"):
            row = "%s %s %s %s %s %s" % (e.name, e.nodes[0], e.nodes[1],
                                         e.ctrl_nodes[0], e.ctrl_nodes[1],
                                         _num(e.gain))
        elif e.kind in ("H", "F"):
            row = "%s %s %s %s %s" % (e.name, e.nodes[0], e.nodes[1],
                                      e.ctrl_element, _num(e.gain))
        else:
            row = "%s %s" % (e.name, " ".join(e.nodes))
        lines.append(row)
    return "\n".join(lines) + "\n"


def _num(value):
    value = to_fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    return "%d/%d" % (value.numerator, value.denominator)
