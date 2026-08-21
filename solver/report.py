"""Turn a solved Result into the working a student would be expected to show.

Nothing here computes anything.  Every number printed comes straight out of the
solver, so the working and the answers cannot drift apart.
"""

from circuit import UNITS, is_ground
from dynamics import DAMPING_LABELS
from exact import format_number

PHASE_ORDER = ["t<0", "0+", "d/dt", "d2/dt2", "d3/dt3", "inf"]
PHASE_HEADING = {
    "t<0": "t < 0  --  steady state before switching",
    "0+": "t = 0+  --  the instant after switching",
    "d/dt": "d/dt at t = 0+  --  the same equations, differentiated",
    "d2/dt2": "d2/dt2 at t = 0+  --  differentiated a second time",
    "d3/dt3": "d3/dt3 at t = 0+  --  differentiated a third time",
    "inf": "t -> infinity  --  steady state long after switching",
}
DERIVATIVE_PHASES = {"d/dt": 1, "d2/dt2": 2, "d3/dt3": 3}


def unit(element, quantity, phase):
    base = "V" if quantity == "v" else "A"
    order = DERIVATIVE_PHASES.get(phase)
    if not order:
        return base
    return base + "/s" + ("" if order == 1 else str(order))


def quantity_name(element, quantity, phase):
    symbol = "v" if quantity == "v" else "i"
    label = "%s_%s" % (symbol, element.name)
    order = DERIVATIVE_PHASES.get(phase)
    if order == 1:
        return "d%s/dt(0+)" % label
    if order:
        return "d%d%s/dt%d(0+)" % (order, label, order)
    suffix = {"t<0": "(0-)", "0+": "(0+)", "inf": "(inf)"}[phase]
    return label + suffix


def render(result, show_equations=True):
    circuit = result.circuit
    out = []
    add = out.append

    add("=" * 72)
    add(circuit.title)
    add("=" * 72)

    add("")
    add("CIRCUIT")
    for element in circuit.elements:
        add("  " + _element_line(element))

    if result.notes:
        add("")
        add("NOTES")
        for note in result.notes:
            add("  * " + _wrap(note, 68, "    "))

    step = 0
    for key in PHASE_ORDER:
        phase = result.phases.get(key)
        if phase is None:
            continue
        step += 1
        add("")
        add("-" * 72)
        add("STEP %d.  %s" % (step, PHASE_HEADING[key]))
        add("-" * 72)

        if phase.description:
            add("")
            add("  Replace each element by what it looks like in this window:")
            for line in phase.description:
                add("    - " + line)

        if show_equations:
            add("")
            add("  The node equations for that circuit:")
            for line in phase.system.equation_lines(phase.rhs):
                add("    " + line)

        add("")
        add("  Solving gives:")
        for node in circuit.nodes:
            if is_ground(node):
                continue
            value = phase.solution.node_voltage(node)
            add("    V(%s) = %s %s" % (node, format_number(value),
                                       "V/s" if key == "d/dt" else "V"))

        if key == "t<0":
            add("")
            add("  The two quantities that carry across the switch:")
            for element in circuit.of_kind("L", "C"):
                if result.ic_sources.get(element.name) != "solved":
                    continue
                quantity = "i" if element.kind == "L" else "v"
                value = result.initial_conditions[element.name]
                add("    %s = %s %s" % (quantity_name(element, quantity, "t<0"),
                                        format_number(value),
                                        "A" if quantity == "i" else "V"))

        if key == "0+":
            _continuity_block(result, add)

        if key in DERIVATIVE_PHASES:
            _derivative_block(result, add, DERIVATIVE_PHASES[key])

    add("")
    add("=" * 72)
    add("ANSWERS")
    add("=" * 72)
    _answer_table(result, add)

    storage = circuit.of_kind("L", "C")
    if storage:
        add("")
        add("The quantities these questions usually ask for:")
        _classic_answers(result, add)

    if result.dynamics is not None and result.dynamics.order:
        _dynamics_block(result, add)

    if result.ac is not None:
        _ac_block(result, add)

    return "\n".join(out)


def _ac_block(result, add):
    """AC steady state at one frequency, in exact complex arithmetic."""
    report = result.ac
    circuit = result.circuit
    add("")
    add("=" * 72)
    add("AC STEADY STATE")
    add("=" * 72)
    add("")
    add("  Angular frequency omega = %s rad/s" % format_number(report.omega))
    add("  Every impedance below is exact. Only the magnitude and angle of "
        "each")
    add("  answer are rounded, and the rectangular form beside them is not.")

    for note in report.notes:
        add("  * " + _wrap(note, 68, "    "))

    add("")
    add("  Source phasors:")
    for element in circuit.of_kind("V", "I"):
        phasor = report.phasors[element.name]
        add("    %-6s %-18s = %s" % (element.name, phasor.rectangular(),
                                     phasor.polar()))

    add("")
    add("  Impedances:")
    for element in circuit.of_kind("R", "L", "C"):
        from phasor import impedance
        z = impedance(element, report.omega)
        add("    Z(%-4s) = %-18s = %s" % (element.name, z.rectangular(),
                                          z.polar()))
    for name, z in report.impedances.items():
        add("    seen by %-4s = %-16s = %s" % (name, z.rectangular(), z.polar()))

    add("")
    add("  Node voltages:")
    for node in circuit.nodes:
        if is_ground(node):
            continue
        value = report.solution.node_voltage(node)
        add("    V(%-3s) = %-20s = %s" % (node, value.rectangular(),
                                          value.polar()))

    add("")
    add("  Branch quantities:")
    rows = [["element", "V (rect)", "V (polar)", "I (rect)", "I (polar)"]]
    for element in circuit.elements:
        voltage = report.solution.element_voltage(element)
        current = report.solution.element_current(element)
        rows.append([element.name, voltage.rectangular(), voltage.polar(),
                     current.rectangular(), current.polar()])
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for index, row in enumerate(rows):
        add("    " + "  ".join(cell.ljust(widths[i])
                               for i, cell in enumerate(row)))
        if index == 0:
            add("    " + "  ".join("-" * width for width in widths))


def _dynamics_block(result, add):
    """Natural frequencies, damping, and the complete response."""
    dynamics = result.dynamics
    add("")
    add("=" * 72)
    add("HOW IT GETS THERE")
    add("=" * 72)
    add("")
    add("  This is an order %d circuit." % dynamics.order)

    if dynamics.order == 1:
        add("  One time constant, so the approach is a plain exponential.")
        if dynamics.tau is not None:
            add("    tau = %s s" % dynamics.tau)
            add("    natural frequency s = %s per second" % dynamics.roots[0])
    elif dynamics.order == 2:
        add("  Characteristic equation:  s^2 + 2*alpha*s + omega0^2 = 0")
        add("    alpha    = %s" % format_number(dynamics.alpha))
        add("    omega0^2 = %s" % format_number(dynamics.omega0_squared))
        if dynamics.omega0 is not None:
            add("    omega0   = %s rad/s" % dynamics.omega0)
        if dynamics.zeta is not None:
            add("    zeta     = %s" % dynamics.zeta)
        add("    alpha^2 - omega0^2 = %s" % format_number(dynamics.discriminant))
        add("")
        add("  The sign of that discriminant decides the damping. It is an "
            "exact")
        add("  comparison, so the classification cannot be a rounding "
            "artefact.")
        add("")
        add("    ->  %s" % DAMPING_LABELS[dynamics.damping].upper())
        add("")
        if dynamics.damping == "underdamped":
            add("    roots  s = -%s +/- j%s"
                % (format_number(dynamics.alpha), dynamics.omega_d))
            add("    damped frequency omega_d = %s rad/s" % dynamics.omega_d)
        elif dynamics.damping == "critical":
            add("    repeated root  s = %s" % dynamics.roots[0])
        else:
            add("    roots  s1 = %s,  s2 = %s"
                % (dynamics.roots[0], dynamics.roots[1]))
    else:
        add("  Characteristic polynomial, highest power of s first:")
        add("    " + ", ".join(format_number(c) for c in dynamics.polynomial))

    if not result.responses:
        return

    add("")
    add("  Complete response, forced value plus natural response:")
    add("")
    approximate = False
    for element in result.circuit.elements:
        forms = result.responses.get(element.name)
        if not forms:
            continue
        for quantity in ("v", "i"):
            form = forms.get(quantity)
            if form is None:
                continue
            add("    " + form.formula)
            approximate = approximate or not form.exact
    if approximate:
        add("")
        add("  Where a root is irrational its constants are given to six "
            "figures.")
        add("  alpha, omega0^2 and the damping stay exact regardless.")


def _element_line(element):
    kind = element.kind
    where = " and ".join(element.nodes[:2])
    if kind in ("R", "L", "C"):
        text = "%-6s %-14s %s %-4s between nodes %s" % (
            element.name, element.pretty, format_number(element.value),
            UNITS[kind], where)
        if element.ic is not None:
            text += "   (initial %s = %s)" % (
                "current" if kind == "L" else "voltage",
                format_number(element.ic))
        return text
    if kind in ("V", "I"):
        unit_text = UNITS[kind]
        if element.before == element.after:
            spec = "%s %s constant" % (format_number(element.after), unit_text)
        else:
            spec = "%s %s for t<0, %s %s for t>0" % (
                format_number(element.before), unit_text,
                format_number(element.after), unit_text)
        direction = ("from node %s to node %s (arrow points at %s)"
                     % (element.nodes[0], element.nodes[1], element.nodes[1])
                     if kind == "I" else
                     "+ at node %s, - at node %s" % (element.nodes[0],
                                                     element.nodes[1]))
        return "%-6s %-14s %s, %s" % (element.name, element.pretty, spec, direction)
    if kind == "SW":
        return "%-6s %-14s %s before t=0, %s after, between nodes %s" % (
            element.name, element.pretty, element.state_before,
            element.state_after, where)
    if kind in ("E", "G"):
        return "%-6s %-14s gain %s, controlled by V(%s) - V(%s)" % (
            element.name, element.pretty, format_number(element.gain),
            element.ctrl_nodes[0], element.ctrl_nodes[1])
    if kind in ("H", "F"):
        return "%-6s %-14s gain %s, controlled by the current through %s" % (
            element.name, element.pretty, format_number(element.gain),
            element.ctrl_element)
    if kind == "OPAMP":
        return "%-6s %-14s in+ %s, in- %s, out %s" % (
            element.name, element.pretty, element.nodes[0], element.nodes[1],
            element.nodes[2])
    return "%-6s %s" % (element.name, element.pretty)


def _continuity_block(result, add):
    circuit = result.circuit
    storage = circuit.of_kind("L", "C")
    if not storage:
        return
    add("")
    add("  Why those substitutions are allowed:")
    for element in storage:
        value = result.initial_conditions[element.name]
        source = result.ic_sources.get(element.name)
        origin = "given in the question" if source == "given" else "from step 1"
        if element.kind == "L":
            add("    i_%s(0+) = i_%s(0-) = %s A   (%s; an inductor current "
                "cannot change instantly)"
                % (element.name, element.name, format_number(value), origin))
        else:
            add("    v_%s(0+) = v_%s(0-) = %s V   (%s; a capacitor voltage "
                "cannot change instantly)"
                % (element.name, element.name, format_number(value), origin))


def _derivative_block(result, add, order=1):
    """Each order is driven by the one before it, so name that source."""
    circuit = result.circuit
    storage = circuit.of_kind("L", "C")
    if not storage:
        return
    source_key = "0+" if order == 1 else PHASE_ORDER[order]
    source = result.phases[source_key].solution
    lower = "" if order == 1 else "^%d" % (order - 1)
    prime = "" if order == 1 else "^%d" % order
    add("")
    add("  Where the driving values came from:")
    for element in storage:
        derivative = result.derivative_storage[order][element.name]
        if element.kind == "L":
            add("    d%si_%s/dt%s = (d%sv_%s/dt%s) / L = %s / %s = %s"
                % (prime, element.name, prime, lower, element.name, lower,
                   format_number(source.element_voltage(element)),
                   format_number(element.value), format_number(derivative)))
        else:
            add("    d%sv_%s/dt%s = (d%si_%s/dt%s) / C = %s / %s = %s"
                % (prime, element.name, prime, lower, element.name, lower,
                   format_number(source.element_current(element)),
                   format_number(element.value), format_number(derivative)))


def _answer_table(result, add):
    columns = [key for key in PHASE_ORDER if key in result.phases]
    headers = {"t<0": "t < 0", "0+": "t = 0+", "d/dt": "d/dt at 0+",
               "d2/dt2": "d2/dt2 at 0+", "d3/dt3": "d3/dt3 at 0+",
               "inf": "t -> inf"}

    rows = [["element", "quantity"] + [headers[key] for key in columns]]
    for element in result.circuit.elements:
        for quantity in ("v", "i"):
            row = [element.name, "v (V)" if quantity == "v" else "i (A)"]
            for key in columns:
                value = result.value(key, element.name, quantity)
                row.append("-" if value is None else format_number(value))
            rows.append(row)

    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    add("")
    for index, row in enumerate(rows):
        add("  " + "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
        if index == 0:
            add("  " + "  ".join("-" * width for width in widths))
    add("")
    add("  The d/dt column holds dv/dt in V/s and di/dt in A/s.")
    add("  Signs follow each element as it is wired: v = V(first node) - "
        "V(second node),")
    add("  and i flows from the first node to the second through the element.")


def _classic_answers(result, add):
    circuit = result.circuit
    targets = circuit.of_kind("L", "C", "R")
    parts = [("a", "0+", "values just after switching"),
             ("b", "d/dt", "first derivatives just after switching"),
             ("c", "inf", "final values")]
    for letter, key, caption in parts:
        if key not in result.phases:
            continue
        add("")
        add("  (%s) %s" % (letter, caption))
        for element in targets:
            quantity = "i" if element.kind == "L" else "v"
            value = result.value(key, element.name, quantity)
            add("      %-16s = %s %s"
                % (quantity_name(element, quantity, key),
                   format_number(value), unit(element, quantity, key)))


def _wrap(text, width, indent):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    if current:
        lines.append(current)
    return ("\n" + indent).join(lines)
