# Zero Plus

Works out initial conditions, their first derivatives, and final conditions for
switched linear circuits — the `x(0⁺)`, `dx/dt(0⁺)`, `x(∞)` questions — and
shows the working.

There are two front ends over one method: a **schematic editor in the browser**
(`web/`) and a **command line tool** (`solve.py`). They implement the same
algorithm in Python and JavaScript, and a test step compares them value by value
so an answer from one can be checked against the other.

## Why the answers can be trusted

No part of this guesses or approximates.

- **Nothing is a floating-point number.** Every component value, matrix entry
  and answer is an exact rational — `fractions.Fraction` in Python, BigInt pairs
  in JavaScript. `1/3` stays `1/3`. There is no rounding to accumulate.
- **The method is fixed, not inferred.** Modified Nodal Analysis builds the
  equations from the netlist mechanically. The same circuit always produces the
  same matrix.
- **It refuses rather than invents.** A circuit whose equations have no unique
  solution raises an error naming the node or the loop responsible. It never
  returns a plausible-looking number for an underdetermined circuit.
- **Two independent implementations agree.** `run_tests.py` solves hundreds of
  randomly generated circuits in both languages and compares every node voltage
  and branch quantity as exact fractions. Any disagreement fails the build.

The working shown on screen is the actual system of equations that was solved,
rendered from the matrix — not a narrative written afterwards.

## The method

Four solves, in order:

1. **t < 0** — steady state of the pre-switch circuit. Inductors become shorts,
   capacitors become opens. This is where `i_L(0⁻)` and `v_C(0⁻)` come from.
2. **t = 0⁺** — the post-switch circuit, with each inductor replaced by a
   current source holding `i_L(0⁻)` and each capacitor by a voltage source
   holding `v_C(0⁻)`. Those two quantities are the only ones that cannot change
   instantaneously; everything else (`v_R`, `i_C`, `v_L`) follows from solving.
3. **d/dt at 0⁺** — the same equations differentiated once. The matrix is
   unchanged; only the right-hand side moves, because the storage elements now
   hold `di_L/dt = v_L(0⁺)/L` and `dv_C/dt = i_C(0⁺)/C`, and constant sources
   differentiate to zero.
4. **t → ∞** — steady state of the post-switch circuit, shorts and opens again.

Steps 1 and 4 are the same code with a different time window. Steps 2 and 3 are
the same matrix with a different right-hand side.

## What it handles

Resistors, inductors, capacitors, independent voltage and current sources
(constant, stepped, or with a different value each side of `t = 0`), switches
that open or close at `t = 0`, all four dependent sources (VCVS, VCCS, CCVS,
CCCS), and ideal op-amps.

A dependent source can be controlled by the current through *any* branch,
including an inductor, because branch currents are split into an unknown part
that goes into the matrix and a known part that goes into the right-hand side.

## Putting it on another device

```bash
python package.py
```

Builds everything into `dist/`:

| File | Size | Needs |
| --- | --- | --- |
| `zero-plus-offline.html` | 605 KB | a browser. Nothing else — no network, no server, no install. |
| `zeroplus.pyz` | 61 KB | Python 3, no packages. `python zeroplus.pyz circuit.net` |
| `zero-plus.zip` | 847 KB | both of the above, plus examples, `HOW-TO-RUN.txt`, and full source |

The HTML file is genuinely self-contained: markup, styles, solver, and the web
fonts are all inlined as one document, so it renders the same on a machine that
has never seen the internet. `build.py` checks this and refuses to claim
otherwise — it scans the output for external URLs and reports any it finds.

To move it: copy the one file. A memory stick, a cloud drive, an email
attachment, or a phone's Files app all work. There is nothing to install and
nothing to keep next to it.

`zeroplus.pyz` is a Python zipapp: the solver and its modules zipped into a
single runnable file. Copy it anywhere and run it from any directory.

Fonts are embedded from `web/fonts.css`, which `fetch_fonts.py` generates. That
file is checked in, so `build.py` and `package.py` never need a network. Re-run
`fetch_fonts.py` only if the typefaces change.

## Using the web version

Open `dist/zero-plus-offline.html`, or run `python build.py` after editing
anything in `web/` to rebuild it.

Pick a part from the left rail, drag across two or more grid squares to place
it. Terminals that touch are connected; drag with **Wire** to join things
further apart. The small blue numbers are the node numbers the solver worked
out — check those against your own drawing before trusting an answer. Click a
part to set its value, flip its polarity, or delete it.

**Netlist** exports the drawing as text that `solve.py` reads, so any answer can
be confirmed in a second place.

## Using the command line version

```bash
python solve.py tests/ex2.net
```

Needs Python 3 only — no dependencies.

## Netlist format

```
R1  1 2 5             # nodes n+ n-, then the value
C1  1 0 1/5           # 0 is ground; fractions, decimals and 4k7/10u all work
L1  2 0 2   ic=3      # ic= states a starting value instead of solving for it
I1  0 1 step 4        # 0 before t=0, 4 after: this is 4u(t)
I2  0 2 dc 6          # the same before and after
V1  1 0 3 12          # explicit before/after pair
SW1 2 3 closed open   # state before t=0, then after
E1  3 0 1 2 10        # VCVS: v(3,0) = 10 * v(1,2)
G1  0 3 1 2 0.01      # VCCS: current into node 3 = 0.01 * v(1,2)
H1  3 0 R1 5          # CCVS: v(3,0) = 5 * i(R1)
F1  0 3 R1 2          # CCCS: current into node 3 = 2 * i(R1)
OP1 1 2 3             # op-amp: in+, in-, out
```

Sign conventions, which decide what the answers mean:

- `R L C V SW` — nodes are `(n+, n-)`. `v = V(n+) − V(n−)`, and `i` flows from
  `n+` to `n−` *through* the part. Current enters the `+` terminal.
- `I G F` — nodes are `(tail, head)`, matching the arrow on the symbol. Current
  flows tail → head inside the source, so it is injected into `head`.

## Running the tests

```bash
python run_tests.py
```

Runs the worked examples, then cross-checks Python against JavaScript on those
and on several hundred random circuits. Pass a number to change how many
random circuits are generated.

Every expected value in `tests/test_cases.py` was worked out by hand before it
was written down, including the lecture example this was built for, a series
RLC step response, an inductive kick from an opening switch, an op-amp
integrator ramping at −Vin/RC, and cases the solver must *refuse*.

## Layout

```
solver/      the Python solver, source of truth
  exact.py     rational arithmetic and exact Gauss-Jordan
  circuit.py   elements, nodes, netlist parsing
  mna.py       the stamps and the matrix
  analysis.py  the four-phase procedure and failure diagnosis
  report.py    the printed working
web/         the browser version
  solver.js    a line-for-line port of the Python solver
  app.js       schematic editor and results view
  fonts.css    the web fonts as data URIs, generated, checked in
build.py     inlines web/ into self-contained pages in dist/
package.py   builds the pages, the zipapp, and the handover zip
fetch_fonts.py  regenerates web/fonts.css (the only script needing a network)
solve.py     command line front end
run_tests.py everything
```

## Limits worth knowing

- Linear, time-invariant circuits only: no diodes, transistors, or saturation.
- One switching instant, at `t = 0`.
- Sources are constant either side of `t = 0`, so every source derivative in
  step 3 is zero. Ramps and sinusoids are out of scope.
- Op-amps are ideal and assumed to stay in their linear region.
- The `t → ∞` column is the steady state the equations give. For a circuit with
  no resistance, that is not a value the circuit actually settles at, and the
  page says so.
