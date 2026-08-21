"""Turn a solved Result into the working a student would be expected to show.

Nothing here computes anything.  Every number printed comes straight out of the
solver, so the working and the answers cannot drift apart.
"""

from circuit import UNITS, is_ground
from exact import format_number

PHASE_ORDER = ["t<0", "0+", "d/dt", "inf"]
PHASE_HEADING = {
    "t<0": "t < 0  --  steady state before switching",
    "0+": "t = 0+  --  the instant after switching",
    "d/dt": "d/dt at t = 0+  --  the same equations, differentiated",
    "inf": "t -> infinity  --  steady state long after switching",
}


def unit(element, quantity, phase):
    base = "V" if quantity == "v" else "A"
    return base + "/s" if phase == "d/dt" else base


def quantity_name(element, quantity, phase):
    symbol = "v" if quantity == "v" else "i"
    label = "%s_%s" % (symbol, element.name)
    if phase == "d/dt":
        return "d%s/dt(0+)" % label
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

        if key == "d/dt":
            _derivative_block(result, add)

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

    return "\n".join(out)


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


def _derivative_block(result, add):
    circuit = result.circuit
    storage = circuit.of_kind("L", "C")
    if not storage:
        return
    add("")
    add("  Where the driving values came from:")
    zero_plus = result.phases["0+"].solution
    for element in storage:
        derivative = result.derivative_storage[element.name]
        if element.kind == "L":
            add("    di_%s/dt(0+) = v_%s(0+)/L = %s / %s = %s A/s"
                % (element.name, element.name,
                   format_number(zero_plus.element_voltage(element)),
                   format_number(element.value), format_number(derivative)))
        else:
            add("    dv_%s/dt(0+) = i_%s(0+)/C = %s / %s = %s V/s"
                % (element.name, element.name,
                   format_number(zero_plus.element_current(element)),
                   format_number(element.value), format_number(derivative)))


def _answer_table(result, add):
    columns = [key for key in PHASE_ORDER if key in result.phases]
    headers = {"t<0": "t < 0", "0+": "t = 0+", "d/dt": "d/dt at 0+",
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
