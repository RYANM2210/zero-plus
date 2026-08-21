# Zero Plus

An exact-rational solver for switched linear circuits. It computes initial
conditions, their derivatives at `t = 0⁺`, final conditions, the natural
frequencies and damping, the closed-form transient response, and the AC steady
state — and shows the equations it solved at each stage.

Live: <https://ryanm2210.github.io/zero-plus/>

```bash
git clone https://github.com/RYANM2210/zero-plus.git
```

Two front ends share one method: a schematic editor in the browser and a command
line tool. Each push runs both implementations against each other on several
hundred random circuits and publishes only if they agree.

## Basis for correctness

The solver is deterministic. No stage estimates, samples, or approximates a
quantity that can be represented exactly.

**Exact arithmetic throughout.** Component values, matrix entries, and results
are rational numbers — `fractions.Fraction` in Python, BigInt pairs in
JavaScript. AC analysis extends this to Gaussian rationals, so impedances and
phasors are also exact. Floating point appears only where a value is genuinely
irrational: a square root, a magnitude, an angle. Those are labelled.

**Failure is explicit.** A circuit whose equations have no unique solution
raises an error identifying the responsible node or loop. No value is returned
for an underdetermined circuit.

**Two independent implementations.** `run_tests.py` solves random circuits in
both languages and compares every node voltage, branch quantity, damping
classification, response coefficient, and AC phasor as exact values. It also
compares rendered output, so a formatting divergence fails the build alongside
an arithmetic one.

The working displayed is the system of equations that was solved, rendered from
the matrix itself rather than composed afterwards.

## Method

### Initial and final conditions

Four solves:

1. **t < 0.** Steady state of the pre-switch circuit. Inductors become shorts,
   capacitors become opens. Yields `i_L(0⁻)` and `v_C(0⁻)`.
2. **t = 0⁺.** The post-switch circuit with each inductor replaced by a current
   source holding `i_L(0⁻)` and each capacitor by a voltage source holding
   `v_C(0⁻)`. Those two quantities cannot change instantaneously; every other
   quantity follows from solving.
3. **Derivatives at 0⁺.** The same equations differentiated. The matrix is
   unchanged; only the right-hand side moves, since the storage elements now
   hold `di_L/dt = v_L(0⁺)/L` and `dv_C/dt = i_C(0⁺)/C`, and constant sources
   differentiate to zero. Each order feeds the next, so the procedure extends to
   any order. Two are computed by default.
4. **t → ∞.** Steady state of the post-switch circuit.

Steps 1 and 4 are the same code with a different time window. Steps 2 and 3 are
the same matrix with a different right-hand side.

### Natural frequencies and the transient response

The `t = 0⁺` system maps a stored state to its own rate of change, and that map
is linear. Probing it with unit states recovers the state matrix without the
differential equations being written out:

```
dx/dt = A x + f          x = inductor currents and capacitor voltages
```

Column `k` of `A` is `dx/dt` when only storage element `k` holds one unit and
all sources are off. `f` is `dx/dt` with nothing stored and the sources at their
`t > 0` values.

For a second-order circuit, `α = −tr(A)/2` and `ω₀² = det(A)`, both exact
rationals, and the sign of `α² − ω₀²` classifies the damping by exact
comparison. Roots may be irrational and are marked when they are. The
characteristic polynomial is computed by Faddeev–LeVerrier at any order.

The complete response for any quantity is fitted from three values the solver
already holds: the value at `0⁺`, its slope at `0⁺`, and the final value.
Closed forms are produced for first- and second-order circuits; above that the
characteristic polynomial is reported and the closed form is not.

### AC steady state

At a fixed angular frequency each impedance is a Gaussian rational — `R`,
`jωL`, `1/(jωC)` — so nodal analysis proceeds in exact complex arithmetic.
Frequency is specified in rad/s; `ω = 2πf` would introduce an irrational number
into every impedance. Source phases are restricted to quarter turns, which are
the values expressible exactly.

## Scope

Resistors, inductors, capacitors, independent voltage and current sources
(constant, stepped, or differing either side of `t = 0`), switches that change
state at `t = 0`, all four dependent sources, and ideal op-amps.

A dependent source may be controlled by the current through any branch,
including an inductor, because branch currents are separated into an unknown
part entering the matrix and a known part entering the right-hand side.

## Distribution

```bash
python package.py
```

| File | Size | Requires |
| --- | --- | --- |
| `dist/zero-plus-offline.html` | ~645 KB | a browser; no network, server, or install |
| `dist/zeroplus.pyz` | ~65 KB | Python 3, no packages |
| `dist/zero-plus.zip` | ~890 KB | the above, plus examples and full source |

The HTML file is self-contained: markup, styles, solver, and web fonts are
inlined into one document. `build.py` scans its output for external URLs and
reports any found.

Fonts come from `web/fonts.css`, generated by `fetch_fonts.py` and committed, so
neither `build.py` nor CI requires a network.

## Command line use

```bash
python solve.py tests/ex2.net
```

Add `--no-equations` to omit the matrices. The **Netlist** button in the browser
exports the drawing in this format, allowing any result to be confirmed against
the second implementation.

## Netlist format

```
R1  1 2 5             # nodes n+ n-, then the value
C1  1 0 1/5           # 0 is ground; fractions, decimals and 4.7k / 10u accepted
L1  2 0 2   ic=3      # ic= states a starting value instead of solving for it
I1  0 1 step 4        # 0 before t=0, 4 after: 4u(t)
I2  0 2 dc 6          # identical either side
V1  1 0 3 12          # explicit before / after pair
SW1 2 3 closed open   # state before t=0, then after
E1  3 0 1 2 10        # VCVS: v(3,0) = 10 * v(1,2)
G1  0 3 1 2 0.01      # VCCS: current into node 3 = 0.01 * v(1,2)
H1  3 0 R1 5          # CCVS: v(3,0) = 5 * i(R1)
F1  0 3 R1 2          # CCCS: current into node 3 = 2 * i(R1)
OP1 1 2 3             # op-amp: in+, in-, out
.ac 1000              # angular frequency in rad/s, enables AC analysis
V2  1 0 dc 5 ac=10 phase=90   # AC magnitude and phase, in degrees
```

Sign conventions determine what the results mean:

- `R L C V SW` — nodes are `(n+, n-)`. `v = V(n+) − V(n−)`, and `i` flows from
  `n+` to `n−` through the element. Current enters the `+` terminal.
- `I G F` — nodes are `(tail, head)`, matching the arrow on the symbol. Current
  flows tail → head inside the source and is injected at `head`.

## Tests

```bash
python run_tests.py
```

Runs the worked examples, then cross-checks Python against JavaScript on those
and on several hundred random circuits. An argument sets the number of random
circuits.

Every expected value in `tests/test_cases.py` was derived by hand before being
recorded: the lecture example this began as, a series RLC in all three damping
regimes, an inductive kick from an opening switch, an op-amp integrator ramping
at `−Vin/RC`, second derivatives checked against differentiated closed forms, AC
impedances checked against `Z = R + jωL`, and circuits the solver must refuse.

## Layout

```
solver/            the Python solver, source of truth
  exact.py           rational arithmetic and exact Gauss-Jordan
  circuit.py         elements, nodes, netlist parsing
  mna.py             element stamps and the matrix
  analysis.py        the phase procedure and failure diagnosis
  dynamics.py        state matrix, damping, closed-form response
  phasor.py          AC steady state in exact complex arithmetic
  report.py          the printed working
web/               the browser version
  solver.js          port of exact.py, circuit.py, mna.py, analysis.py
  extras.js          port of dynamics.py and phasor.py
  app.js             schematic editor and results view
  fonts.css          web fonts as data URIs, generated and committed
build.py           inlines web/ into self-contained pages
package.py         builds the pages, the zipapp, and the handover archive
fetch_fonts.py     regenerates web/fonts.css; the only script needing a network
solve.py           command line front end
run_tests.py       the full suite
```

Changes to the solver must be made in both `solver/` and `web/`. The two are
deliberate ports of each other and the tests compare them value by value; that
agreement is the basis for trusting the browser version.

## Limitations

- Linear, time-invariant circuits only. No diodes, transistors, or saturation.
- One switching instant, at `t = 0`.
- Sources are constant either side of `t = 0`, so every source derivative is
  zero. Ramps and sinusoidal transients are out of scope; sinusoidal steady
  state is handled separately by the AC analysis.
- Closed-form responses are produced for first- and second-order circuits only.
- Op-amps are ideal and assumed to remain in their linear region.
- AC source phases must be a multiple of 90°, the values representable exactly.
- The `t → ∞` column reports the steady state the equations give. For a circuit
  with no resistance that is not a value the circuit settles at, and the output
  says so.
