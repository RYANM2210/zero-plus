/* Dynamics and AC steady state, mirroring ../solver/dynamics.py and
 * ../solver/phasor.py line for line so the cross-check can compare them.
 *
 * Loaded after solver.js and attached to the same CircuitSolver object.
 */
(function (S) {
  'use strict';

  const Q = S.Q;
  const toQ = S.toQ;
  const fmt = S.fmt;
  const ZERO = S.ZERO;
  const ONE = S.ONE;
  const isGround = S.isGround;
  const CircuitError = S.CircuitError;
  const Singular = S.Singular;

  function q(n, d) { return new Q(BigInt(n), BigInt(d === undefined ? 1 : d)); }

  // ------------------------------------------------------------- exact roots

  function bigintSqrt(value) {
    if (value < 0n) return null;
    if (value < 2n) return value;
    let x = value, y = (x + 1n) / 2n;
    while (y < x) { x = y; y = (x + value / x) / 2n; }
    return x * x === value ? x : null;
  }

  /* The exact square root of a rational, or null when it is irrational. */
  function exactSqrt(value) {
    if (value.n < 0n) return null;
    const n = bigintSqrt(value.n);
    const d = bigintSqrt(value.d);
    if (n === null || d === null) return null;
    return new Q(n, d);
  }

  function Num(exact, approx) {
    this.exact = exact === undefined ? null : exact;
    this.approx = this.exact !== null ? this.exact.toNumber() : approx;
  }
  Num.prototype.isExact = function () { return this.exact !== null; };
  Num.prototype.toString = function () {
    if (this.isExact()) return fmt(this.exact);
    if (this.approx === undefined || this.approx === null) return '?';
    return sixFigures(this.approx);
  };

  /* Python renders these with %.6g; S.formatSig is the faithful equivalent. */
  function sixFigures(value) {
    return S.formatSig(value, 6);
  }

  function rootOf(value) {
    const precise = exactSqrt(value);
    if (precise !== null) return new Num(precise);
    return new Num(null, Math.sqrt(value.toNumber()));
  }

  const DAMPING_LABELS = {
    overdamped: 'overdamped',
    critical: 'critically damped',
    underdamped: 'underdamped',
    'first-order': 'first order'
  };

  // -------------------------------------------------------- state matrix

  function stateSpace(circuit, system, sourceValues) {
    const storage = circuit.ofKind('L', 'C');
    const size = storage.length;
    const zeroSources = {};
    circuit.ofKind('V', 'I').forEach(function (e) { zeroSources[e.name] = ZERO; });

    function rates(solution) {
      return storage.map(function (element) {
        return element.kind === 'L'
          ? solution.elementVoltage(element).div(element.value)
          : solution.elementCurrent(element).div(element.value);
      });
    }

    const matrix = [];
    for (let r = 0; r < size; r++) matrix.push(new Array(size).fill(ZERO));
    storage.forEach(function (target, column) {
      const unit = {};
      storage.forEach(function (e) {
        unit[e.name] = e.name === target.name ? ONE : ZERO;
      });
      const columnRates = rates(system.solve(zeroSources, unit));
      for (let r = 0; r < size; r++) matrix[r][column] = columnRates[r];
    });

    const resting = {};
    storage.forEach(function (e) { resting[e.name] = ZERO; });
    return { matrix: matrix, forcing: rates(system.solve(sourceValues, resting)) };
  }

  function multiply(left, right) {
    const size = left.length;
    const out = [];
    for (let r = 0; r < size; r++) {
      const row = new Array(size).fill(ZERO);
      for (let c = 0; c < size; c++) {
        let total = ZERO;
        for (let k = 0; k < size; k++) total = total.add(left[r][k].mul(right[k][c]));
        row[c] = total;
      }
      out.push(row);
    }
    return out;
  }

  function addDiagonal(matrix, value) {
    return matrix.map(function (row, r) {
      return row.map(function (cell, c) { return r === c ? cell.add(value) : cell; });
    });
  }

  /* det(sI - A) by Faddeev-LeVerrier, exact and valid at any order. */
  function characteristicPolynomial(matrix) {
    const size = matrix.length;
    const coefficients = [ONE];
    let current = [];
    for (let r = 0; r < size; r++) {
      const row = new Array(size).fill(ZERO);
      row[r] = ONE;
      current.push(row);
    }
    for (let step = 1; step <= size; step++) {
      if (step > 1) {
        current = addDiagonal(multiply(matrix, current),
          coefficients[coefficients.length - 1]);
      }
      const product = multiply(matrix, current);
      let trace = ZERO;
      for (let i = 0; i < size; i++) trace = trace.add(product[i][i]);
      coefficients.push(trace.neg().div(q(step)));
    }
    return coefficients;
  }

  // ----------------------------------------------------------- damping

  function analyseDynamics(circuit, system, sourceValues) {
    const storage = circuit.ofKind('L', 'C');
    const order = storage.length;
    const dynamics = {
      order: order, matrix: null, forcing: null, polynomial: [],
      alpha: null, omega0Squared: null, discriminant: null,
      omega0: null, omegaD: null, damping: null, roots: [], tau: null,
      stable: false, zeta: null, notes: []
    };
    if (order === 0) return dynamics;

    const space = stateSpace(circuit, system, sourceValues);
    dynamics.matrix = space.matrix;
    dynamics.forcing = space.forcing;
    dynamics.polynomial = characteristicPolynomial(space.matrix);

    if (order === 1) {
      const rate = space.matrix[0][0];
      dynamics.damping = 'first-order';
      dynamics.roots = [new Num(rate)];
      dynamics.stable = rate.isNeg();
      if (!rate.isZero()) {
        dynamics.tau = new Num(ONE.neg().div(rate));
      } else {
        dynamics.notes.push('The single natural frequency is zero, so nothing '
          + 'decays: this circuit integrates rather than settling.');
      }
      return dynamics;
    }

    if (order !== 2) {
      dynamics.notes.push('This circuit is order ' + order + '. Its characteristic '
        + 'polynomial is exact and shown below, but a closed-form response is '
        + 'only worked out for first- and second-order circuits.');
      return dynamics;
    }

    const trace = space.matrix[0][0].add(space.matrix[1][1]);
    const determinant = space.matrix[0][0].mul(space.matrix[1][1])
      .sub(space.matrix[0][1].mul(space.matrix[1][0]));

    dynamics.alpha = trace.neg().div(q(2));
    dynamics.omega0Squared = determinant;
    dynamics.discriminant = dynamics.alpha.mul(dynamics.alpha).sub(determinant);
    dynamics.stable = !dynamics.alpha.isNeg() && !dynamics.alpha.isZero()
      && !determinant.isNeg() && !determinant.isZero();

    if (!determinant.isNeg()) {
      dynamics.omega0 = rootOf(determinant);
      if (!determinant.isZero()) {
        if (dynamics.omega0.isExact() && !dynamics.omega0.exact.isZero()) {
          dynamics.zeta = new Num(dynamics.alpha.div(dynamics.omega0.exact));
        } else {
          dynamics.zeta = new Num(null,
            dynamics.alpha.toNumber() / dynamics.omega0.approx);
        }
      }
    }

    if (!dynamics.discriminant.isNeg() && !dynamics.discriminant.isZero()) {
      dynamics.damping = 'overdamped';
      const spread = rootOf(dynamics.discriminant);
      dynamics.roots = [combine(dynamics.alpha.neg(), spread, 1),
        combine(dynamics.alpha.neg(), spread, -1)];
    } else if (dynamics.discriminant.isZero()) {
      dynamics.damping = 'critical';
      dynamics.roots = [new Num(dynamics.alpha.neg()), new Num(dynamics.alpha.neg())];
    } else {
      dynamics.damping = 'underdamped';
      dynamics.omegaD = rootOf(dynamics.discriminant.neg());
      const negated = dynamics.omegaD.isExact()
        ? new Num(dynamics.omegaD.exact.neg())
        : new Num(null, -dynamics.omegaD.approx);
      dynamics.roots = [[new Num(dynamics.alpha.neg()), dynamics.omegaD],
        [new Num(dynamics.alpha.neg()), negated]];
    }

    if (!dynamics.stable) {
      if (determinant.isNeg() || determinant.isZero()) {
        dynamics.notes.push('This circuit has no stable resting point, so there '
          + 'is no final value for the response to settle on.');
      } else {
        dynamics.notes.push('The natural frequencies do not decay, so this '
          + 'response does not settle. A circuit with no resistance in the loop '
          + 'behaves this way.');
      }
    }
    return dynamics;
  }

  function combine(base, spread, sign) {
    if (spread.isExact()) {
      return new Num(sign > 0 ? base.add(spread.exact) : base.sub(spread.exact));
    }
    return new Num(null, base.toNumber() + sign * spread.approx);
  }

  // ------------------------------------------------- closed-form response

  function isNegative(value) {
    if (value.isExact()) return value.exact.isNeg();
    return value.approx !== undefined && value.approx < 0;
  }

  function isZeroNum(value) {
    if (value.isExact()) return value.exact.isZero();
    return value.approx === 0;
  }

  function magnitudeOf(value) {
    if (value.isExact()) {
      return fmt(value.exact.isNeg() ? value.exact.neg() : value.exact);
    }
    return sixFigures(Math.abs(value.approx));
  }

  function firstTerm(value, symbol) {
    return (isNegative(value) ? '-' : '') + magnitudeOf(value) + symbol;
  }

  function nextTerm(value, symbol) {
    return ' ' + (isNegative(value) ? '-' : '+') + ' ' + magnitudeOf(value) + symbol;
  }

  function sumTerms(pairs) {
    const live = pairs.filter(function (pair) { return !isZeroNum(pair[0]); });
    if (!live.length) return '0';
    let out = firstTerm(live[0][0], live[0][1]);
    for (let i = 1; i < live.length; i++) out += nextTerm(live[i][0], live[i][1]);
    return out;
  }

  function tail(final, body) {
    const head = fmt(final);
    if (!body || body === '0') return head;
    if (final.isZero()) return body;
    if (body.charAt(0) === '-') return head + ' - ' + body.slice(1);
    return head + ' + ' + body;
  }

  function responseFor(dynamics, label, unit, initial, derivative, final) {
    if (dynamics.order !== 1 && dynamics.order !== 2) return null;
    if (!dynamics.damping || final === null || final === undefined) return null;

    const response = { label: label, unit: unit, final: final, constants: [],
      formula: null, exact: true };
    const offset = initial.sub(final);

    if (dynamics.order === 1) {
      if (!dynamics.tau) return null;
      response.exact = dynamics.tau.isExact();
      response.constants = [['A', new Num(offset)]];
      response.formula = label + '(t) = ' + tail(final,
        firstTerm(new Num(offset), '*e^(-t/' + dynamics.tau + ')'));
      return response;
    }

    if (dynamics.damping === 'overdamped') {
      const s1 = dynamics.roots[0], s2 = dynamics.roots[1];
      let first, second;
      if (s1.isExact() && s2.isExact() && !s1.exact.eq(s2.exact)) {
        const gap = s1.exact.sub(s2.exact);
        const a1 = derivative.sub(s2.exact.mul(offset)).div(gap);
        first = new Num(a1);
        second = new Num(offset.sub(a1));
        response.exact = true;
      } else {
        const gap = s1.approx - s2.approx;
        if (gap === 0) return null;
        const a1 = (derivative.toNumber() - s2.approx * offset.toNumber()) / gap;
        first = new Num(null, a1);
        second = new Num(null, offset.toNumber() - a1);
        response.exact = false;
      }
      response.constants = [['A1', first], ['A2', second]];
      const body = sumTerms([[first, '*e^(' + s1 + '*t)'],
        [second, '*e^(' + s2 + '*t)']]);
      response.formula = label + '(t) = ' + tail(final, body);
      return response;
    }

    if (dynamics.damping === 'critical') {
      const alpha = dynamics.alpha;
      const a1 = offset;
      const a2 = derivative.add(alpha.mul(offset));
      response.exact = true;
      response.constants = [['A1', new Num(a1)], ['A2', new Num(a2)]];
      const inner = sumTerms([[new Num(a1), ''], [new Num(a2), '*t']]);
      response.formula = label + '(t) = ' + tail(final,
        inner === '0' ? '' : '(' + inner + ')*e^(-' + fmt(alpha) + '*t)');
      return response;
    }

    const alpha = dynamics.alpha;
    const omegaD = dynamics.omegaD;
    const b1 = offset;
    const numerator = derivative.add(alpha.mul(offset));
    let b2;
    if (omegaD.isExact() && !omegaD.exact.isZero()) {
      b2 = new Num(numerator.div(omegaD.exact));
      response.exact = true;
    } else {
      if (!omegaD.approx) return null;
      b2 = new Num(null, numerator.toNumber() / omegaD.approx);
      response.exact = false;
    }
    response.constants = [['B1', new Num(b1)], ['B2', b2]];
    const inner = sumTerms([[new Num(b1), '*cos(' + omegaD + '*t)'],
      [b2, '*sin(' + omegaD + '*t)']]);
    response.formula = label + '(t) = ' + tail(final,
      inner === '0' ? '' : 'e^(-' + fmt(alpha) + '*t)*[' + inner + ']');
    return response;
  }

  // ==================================================================
  // AC steady state in exact complex arithmetic
  // ==================================================================

  function Cx(re, im) {
    this.re = toQ(re === undefined ? 0 : re);
    this.im = toQ(im === undefined ? 0 : im);
  }

  Cx.prototype.add = function (o) { return new Cx(this.re.add(o.re), this.im.add(o.im)); };
  Cx.prototype.sub = function (o) { return new Cx(this.re.sub(o.re), this.im.sub(o.im)); };
  Cx.prototype.mul = function (o) {
    return new Cx(this.re.mul(o.re).sub(this.im.mul(o.im)),
      this.re.mul(o.im).add(this.im.mul(o.re)));
  };
  Cx.prototype.div = function (o) {
    const denominator = o.re.mul(o.re).add(o.im.mul(o.im));
    if (denominator.isZero()) throw new CircuitError('division by a zero phasor');
    return new Cx(this.re.mul(o.re).add(this.im.mul(o.im)).div(denominator),
      this.im.mul(o.re).sub(this.re.mul(o.im)).div(denominator));
  };
  Cx.prototype.neg = function () { return new Cx(this.re.neg(), this.im.neg()); };
  Cx.prototype.isZero = function () { return this.re.isZero() && this.im.isZero(); };
  Cx.prototype.magnitude = function () {
    return Math.sqrt(Math.pow(this.re.toNumber(), 2) + Math.pow(this.im.toNumber(), 2));
  };
  Cx.prototype.degrees = function () {
    return Math.atan2(this.im.toNumber(), this.re.toNumber()) * 180 / Math.PI;
  };
  Cx.prototype.rectangular = function () {
    if (this.im.isZero()) return fmt(this.re);
    const sign = this.im.isNeg() ? '-' : '+';
    return fmt(this.re) + ' ' + sign + ' j' + fmt(this.im.isNeg() ? this.im.neg() : this.im);
  };
  Cx.prototype.polar = function () {
    return sixFigures(this.magnitude()) + ' / ' + sixFigures(this.degrees()) + ' deg';
  };

  const CZERO = new Cx(0, 0);
  const CONE = new Cx(1, 0);

  function polarToRect(magnitude, degrees) {
    const m = toQ(magnitude);
    const d = toQ(degrees === undefined || degrees === null ? 0 : degrees);
    const full = q(360);
    let turn = d;
    // reduce into [0, 360)
    while (turn.isNeg()) turn = turn.add(full);
    while (!turn.sub(full).isNeg()) turn = turn.sub(full);
    if (turn.isZero()) return new Cx(m, ZERO);
    if (turn.eq(q(90))) return new Cx(ZERO, m);
    if (turn.eq(q(180))) return new Cx(m.neg(), ZERO);
    if (turn.eq(q(270))) return new Cx(ZERO, m.neg());
    throw new CircuitError('a phase of ' + fmt(d) + ' degrees cannot be written '
      + 'exactly. Use 0, 90, 180 or 270 degrees.');
  }

  function impedance(element, omega) {
    if (element.kind === 'R') return new Cx(element.value, ZERO);
    if (element.kind === 'L') return new Cx(ZERO, omega.mul(element.value));
    if (element.kind === 'C') {
      const product = omega.mul(element.value);
      if (product.isZero()) {
        throw new CircuitError(element.name + ' is an open circuit at zero '
          + 'frequency, so there is no AC steady state to find.');
      }
      return new Cx(ZERO, ONE.div(product).neg());
    }
    throw new CircuitError(element.name + ' has no impedance');
  }

  function PhasorSystem(circuit, omega, phasors) {
    const self = this;
    this.circuit = circuit;
    this.omega = toQ(omega);
    this.phasors = phasors;

    this.nodeNames = circuit.freeNodes();
    this.nodeIndex = {};
    this.nodeNames.forEach(function (n, i) { self.nodeIndex[n] = i; });

    this.currentElements = circuit.elements.filter(function (e) {
      return self.needsCurrent(e);
    });
    const offset = this.nodeNames.length;
    this.currentIndex = {};
    this.currentElements.forEach(function (e, i) { self.currentIndex[e.name] = offset + i; });
    this.size = this.nodeNames.length + this.currentElements.length;
    this.labels = this.nodeNames.map(function (n) { return 'V(' + n + ')'; })
      .concat(this.currentElements.map(function (e) { return 'I(' + e.name + ')'; }));

    this.matrix = [];
    for (let r = 0; r < this.size; r++) this.matrix.push(new Array(this.size).fill(CZERO));
    this.rhs = new Array(this.size).fill(CZERO);
    this.build();
  }

  PhasorSystem.prototype.needsCurrent = function (element) {
    if (['V', 'E', 'H', 'OPAMP'].indexOf(element.kind) !== -1) return true;
    if (element.kind === 'SW') return element.stateAfter === 'closed';
    return false;
  };

  PhasorSystem.prototype.col = function (node) {
    return isGround(node) ? null : this.nodeIndex[node];
  };

  PhasorSystem.prototype.addAt = function (row, col, value) {
    if (row === null || col === null || row === undefined || col === undefined) return;
    this.matrix[row][col] = this.matrix[row][col].add(value);
  };

  PhasorSystem.prototype.inject = function (tail_, head, current) {
    const t = this.col(tail_), h = this.col(head);
    if (t !== null) this.rhs[t] = this.rhs[t].sub(current);
    if (h !== null) this.rhs[h] = this.rhs[h].add(current);
  };

  PhasorSystem.prototype.terminals = function (element) {
    if (element.kind === 'OPAMP') return [[element.nodes[2], CONE.neg()]];
    return [[element.nodes[0], CONE], [element.nodes[1], CONE.neg()]];
  };

  PhasorSystem.prototype.build = function () {
    const self = this;
    this.circuit.elements.forEach(function (element) {
      const kind = element.kind;
      if (['R', 'L', 'C'].indexOf(kind) !== -1) {
        self.stampAdmittance(element);
      } else if (kind === 'I') {
        self.inject(element.nodes[0], element.nodes[1], self.phasors[element.name]);
      } else if (kind === 'SW' && element.stateAfter === 'open') {
        return;
      } else if (self.needsCurrent(element)) {
        self.stampCurrentUnknown(element);
      } else if (kind === 'G') {
        const gain = new Cx(element.gain, ZERO);
        self.terminals(element).forEach(function (pair) {
          const row = self.col(pair[0]);
          self.addAt(row, self.col(element.ctrlNodes[0]), pair[1].mul(gain));
          self.addAt(row, self.col(element.ctrlNodes[1]), pair[1].mul(gain.neg()));
        });
      } else if (kind === 'F') {
        const gain = new Cx(element.gain, ZERO);
        const control = self.circuit.get(element.ctrlElement);
        const form = self.currentForm(control);
        self.terminals(element).forEach(function (pair) {
          const row = self.col(pair[0]);
          Object.keys(form).forEach(function (col) {
            self.addAt(row, parseInt(col, 10), pair[1].mul(gain).mul(form[col]));
          });
        });
        const known = self.knownCurrent(control);
        if (!known.isZero()) {
          self.inject(element.nodes[0], element.nodes[1], gain.mul(known));
        }
      }
    });
  };

  PhasorSystem.prototype.stampAdmittance = function (element) {
    const y = CONE.div(impedance(element, this.omega));
    const a = this.col(element.nodes[0]);
    const b = this.col(element.nodes[1]);
    this.addAt(a, a, y);
    this.addAt(a, b, y.neg());
    this.addAt(b, a, y.neg());
    this.addAt(b, b, y);
  };

  PhasorSystem.prototype.stampCurrentUnknown = function (element) {
    const self = this;
    const k = this.currentIndex[element.name];
    this.terminals(element).forEach(function (pair) {
      self.addAt(self.col(pair[0]), k, pair[1]);
    });

    const row = k;
    if (element.kind === 'OPAMP') {
      this.addAt(row, this.col(element.nodes[0]), CONE);
      this.addAt(row, this.col(element.nodes[1]), CONE.neg());
      return;
    }
    this.addAt(row, this.col(element.nodes[0]), CONE);
    this.addAt(row, this.col(element.nodes[1]), CONE.neg());

    if (element.kind === 'V') {
      this.rhs[row] = this.phasors[element.name];
    } else if (element.kind === 'E') {
      const gain = new Cx(element.gain, ZERO);
      this.addAt(row, this.col(element.ctrlNodes[0]), gain.neg());
      this.addAt(row, this.col(element.ctrlNodes[1]), gain);
    } else if (element.kind === 'H') {
      const gain = new Cx(element.gain, ZERO);
      const control = this.circuit.get(element.ctrlElement);
      const form = this.currentForm(control);
      Object.keys(form).forEach(function (col) {
        self.addAt(row, parseInt(col, 10), gain.neg().mul(form[col]));
      });
      const known = this.knownCurrent(control);
      if (!known.isZero()) this.rhs[row] = this.rhs[row].add(gain.mul(known));
    }
  };

  PhasorSystem.prototype.currentForm = function (element) {
    const self = this;
    if (this.needsCurrent(element)) {
      const form = {};
      form[this.currentIndex[element.name]] = CONE;
      return form;
    }
    if (['R', 'L', 'C'].indexOf(element.kind) !== -1) {
      const y = CONE.div(impedance(element, this.omega));
      const form = {};
      const a = this.col(element.nodes[0]);
      const b = this.col(element.nodes[1]);
      if (a !== null) form[a] = (form[a] || CZERO).add(y);
      if (b !== null) form[b] = (form[b] || CZERO).sub(y);
      return form;
    }
    if (element.kind === 'G') {
      const gain = new Cx(element.gain, ZERO);
      const form = {};
      const cp = this.col(element.ctrlNodes[0]);
      const cm = this.col(element.ctrlNodes[1]);
      if (cp !== null) form[cp] = (form[cp] || CZERO).add(gain);
      if (cm !== null) form[cm] = (form[cm] || CZERO).sub(gain);
      return form;
    }
    if (element.kind === 'F') {
      const base = this.currentForm(this.circuit.get(element.ctrlElement));
      const gain = new Cx(element.gain, ZERO);
      const out = {};
      Object.keys(base).forEach(function (col) { out[col] = gain.mul(base[col]); });
      return out;
    }
    return {};
  };

  PhasorSystem.prototype.knownCurrent = function (element) {
    if (element.kind === 'I') return this.phasors[element.name];
    if (element.kind === 'F') {
      return new Cx(element.gain, ZERO)
        .mul(this.knownCurrent(this.circuit.get(element.ctrlElement)));
    }
    return CZERO;
  };

  PhasorSystem.prototype.solve = function () {
    return new PhasorSolution(this, solveComplex(this.matrix, this.rhs));
  };

  function solveComplex(matrix, rhs) {
    const n = matrix.length;
    if (n === 0) return [];
    const aug = [];
    for (let i = 0; i < n; i++) aug.push(matrix[i].slice().concat([rhs[i]]));
    const pivotOfColumn = new Array(n).fill(null);
    let row = 0;
    for (let col = 0; col < n && row < n; col++) {
      let pivot = -1;
      for (let r = row; r < n; r++) {
        if (!aug[r][col].isZero()) { pivot = r; break; }
      }
      if (pivot === -1) continue;
      const swap = aug[row]; aug[row] = aug[pivot]; aug[pivot] = swap;
      const scale = aug[row][col];
      for (let c = 0; c <= n; c++) aug[row][c] = aug[row][c].div(scale);
      for (let r = 0; r < n; r++) {
        if (r === row || aug[r][col].isZero()) continue;
        const factor = aug[r][col];
        for (let c = 0; c <= n; c++) {
          aug[r][c] = aug[r][c].sub(factor.mul(aug[row][c]));
        }
      }
      pivotOfColumn[col] = row;
      row++;
    }
    if (row < n) {
      const free = [];
      for (let c = 0; c < n; c++) if (pivotOfColumn[c] === null) free.push(c);
      throw new Singular('the AC equations have no unique solution', free);
    }
    const solution = new Array(n);
    for (let c = 0; c < n; c++) solution[c] = aug[pivotOfColumn[c]][n];
    return solution;
  }

  function PhasorSolution(system, x) {
    this.system = system;
    this.x = x;
  }

  PhasorSolution.prototype.nodeVoltage = function (node) {
    return isGround(node) ? CZERO : this.x[this.system.nodeIndex[node]];
  };

  PhasorSolution.prototype.elementVoltage = function (element) {
    if (element.kind === 'OPAMP') return this.nodeVoltage(element.nodes[2]);
    return this.nodeVoltage(element.nodes[0]).sub(this.nodeVoltage(element.nodes[1]));
  };

  PhasorSolution.prototype.elementCurrent = function (element) {
    const system = this.system;
    if (system.needsCurrent(element)) return this.x[system.currentIndex[element.name]];
    if (['R', 'L', 'C'].indexOf(element.kind) !== -1) {
      return this.elementVoltage(element).div(impedance(element, system.omega));
    }
    if (element.kind === 'I') return system.phasors[element.name];
    if (element.kind === 'SW') return CZERO;
    if (element.kind === 'G') {
      return new Cx(element.gain, ZERO).mul(
        this.nodeVoltage(element.ctrlNodes[0]).sub(this.nodeVoltage(element.ctrlNodes[1])));
    }
    if (element.kind === 'F') {
      return new Cx(element.gain, ZERO).mul(
        this.elementCurrent(system.circuit.get(element.ctrlElement)));
    }
    throw new CircuitError('cannot report the current through ' + element.name);
  };

  /* Negated because both element quantities use the passive convention. */
  PhasorSolution.prototype.impedanceAt = function (element) {
    const current = this.elementCurrent(element);
    if (current.isZero()) return null;
    try {
      return this.elementVoltage(element).div(current).neg();
    } catch (error) {
      return null;
    }
  };

  function analyseAc(circuit, omega, phasors) {
    circuit.validate();
    const w = toQ(omega);
    if (w.isNeg() || w.isZero()) {
      throw new CircuitError('the frequency must be greater than zero');
    }
    const sources = circuit.ofKind('V', 'I');
    if (!sources.length) {
      throw new CircuitError('there are no sources to drive the circuit');
    }

    const resolved = {};
    sources.forEach(function (element) {
      const given = (phasors || {})[element.name];
      if (given instanceof Cx) {
        resolved[element.name] = given;
      } else if (given) {
        resolved[element.name] = polarToRect(given[0], given[1] || 0);
      } else if (element.ac !== null || element.phase !== null) {
        const magnitude = element.ac !== null ? element.ac : element.after;
        resolved[element.name] = polarToRect(magnitude, element.phase || ZERO);
      } else {
        resolved[element.name] = new Cx(element.after, ZERO);
      }
    });

    const system = new PhasorSystem(circuit, w, resolved);
    const report = { omega: w, solution: system.solve(), system: system,
      phasors: resolved, impedances: {}, notes: [] };

    sources.forEach(function (element) {
      const seen = report.solution.impedanceAt(element);
      if (seen !== null) report.impedances[element.name] = seen;
    });

    circuit.ofKind('SW').forEach(function (element) {
      report.notes.push(element.name + ' is held ' + element.stateAfter
        + ': AC steady state describes one fixed circuit, so the t > 0 position '
        + 'is the one used.');
    });
    if (circuit.ofKind('OPAMP').length) {
      report.notes.push('Op-amps are treated as ideal at every frequency, with '
        + 'no gain roll-off, so this is the textbook answer rather than what '
        + 'real silicon would do.');
    }
    return report;
  }

  // ------------------------------------------------------------------ exports

  S.DAMPING_LABELS = DAMPING_LABELS;
  S.Num = Num;
  S.exactSqrt = exactSqrt;
  S.rootOf = rootOf;
  S.stateSpace = stateSpace;
  S.characteristicPolynomial = characteristicPolynomial;
  S.analyseDynamics = analyseDynamics;
  S.responseFor = responseFor;
  S.Cx = Cx;
  S.polarToRect = polarToRect;
  S.impedance = impedance;
  S.analyseAc = analyseAc;
  S.sixFigures = sixFigures;
}(typeof module !== 'undefined' && module.exports
  ? require('./solver.js').CircuitSolver
  : window.CircuitSolver));

if (typeof module !== 'undefined' && module.exports) {
  module.exports = require('./solver.js');
}
