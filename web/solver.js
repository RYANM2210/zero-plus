/* Exact-rational circuit solver.
 *
 * This is a deliberate line-for-line mirror of ../solver/*.py so the two can be
 * cross-checked against each other.  All arithmetic is BigInt rationals: no
 * floating point ever touches a component value or a solved unknown, so 1/3
 * stays 1/3 and answers come out as exact fractions.
 *
 * See the Python modules for the commentary on why the method works.  The
 * short version: solve the DC steady state before the switch, carry i_L and
 * v_C across t = 0 because those cannot jump, solve again with L as a current
 * source and C as a voltage source, then re-solve the same matrix with a
 * differentiated right-hand side to get the derivatives.
 */
(function (root) {
  'use strict';

  // ---------------------------------------------------------------- rationals

  function bigAbs(a) { return a < 0n ? -a : a; }

  function gcd(a, b) {
    a = bigAbs(a); b = bigAbs(b);
    while (b) { const t = a % b; a = b; b = t; }
    return a;
  }

  function Q(n, d) {
    if (d === undefined) d = 1n;
    if (d === 0n) throw new SolveError('division by zero');
    if (d < 0n) { n = -n; d = -d; }
    const g = gcd(n, d) || 1n;
    this.n = n / g;
    this.d = d / g;
  }

  Q.prototype.add = function (o) { return new Q(this.n * o.d + o.n * this.d, this.d * o.d); };
  Q.prototype.sub = function (o) { return new Q(this.n * o.d - o.n * this.d, this.d * o.d); };
  Q.prototype.mul = function (o) { return new Q(this.n * o.n, this.d * o.d); };
  Q.prototype.div = function (o) {
    if (o.n === 0n) throw new SolveError('division by zero');
    return new Q(this.n * o.d, this.d * o.n);
  };
  Q.prototype.neg = function () { return new Q(-this.n, this.d); };
  Q.prototype.isZero = function () { return this.n === 0n; };
  Q.prototype.eq = function (o) { return this.n === o.n && this.d === o.d; };
  Q.prototype.isNeg = function () { return this.n < 0n; };
  Q.prototype.toNumber = function () { return Number(this.n) / Number(this.d); };
  Q.prototype.toString = function () {
    return this.d === 1n ? String(this.n) : this.n + '/' + this.d;
  };

  const ZERO = new Q(0n, 1n);
  const ONE = new Q(1n, 1n);

  function qInt(value) { return new Q(BigInt(value), 1n); }

  // SPICE-style engineering suffixes: m is milli, Meg is mega.
  const SUFFIXES = [
    ['meg', new Q(1000000n, 1n)],
    ['t', new Q(1000000000000n, 1n)],
    ['g', new Q(1000000000n, 1n)],
    ['k', new Q(1000n, 1n)],
    ['m', new Q(1n, 1000n)],
    ['u', new Q(1n, 1000000n)],
    ['n', new Q(1n, 1000000000n)],
    ['p', new Q(1n, 1000000000000n)],
    ['f', new Q(1n, 1000000000000000n)]
  ];

  function parseDecimal(text) {
    const m = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(text);
    if (!m || (!m[2] && !m[3])) throw new SolveError('cannot read the number "' + text + '"');
    const sign = m[1] === '-' ? -1n : 1n;
    const whole = m[2] || '0';
    const frac = m[3] || '';
    let n = BigInt(whole + frac) * sign;
    let d = 10n ** BigInt(frac.length);
    const exp = m[4] ? parseInt(m[4], 10) : 0;
    if (exp > 0) n *= 10n ** BigInt(exp);
    else if (exp < 0) d *= 10n ** BigInt(-exp);
    return new Q(n, d);
  }

  /* Turn user input into an exact rational.  Accepts 5, 0.2, 1/5, 4.7k, 10u. */
  function toQ(value) {
    if (value instanceof Q) return value;
    if (typeof value === 'bigint') return new Q(value, 1n);
    if (typeof value === 'number') {
      if (!isFinite(value)) throw new SolveError('not a finite number');
      return parseDecimal(String(value));
    }
    let text = String(value).trim();
    if (!text) throw new SolveError('empty value');
    const lowered = text.toLowerCase();
    for (let i = 0; i < SUFFIXES.length; i++) {
      const [suffix, scale] = SUFFIXES[i];
      if (lowered.length > suffix.length && lowered.endsWith(suffix)) {
        const head = text.slice(0, text.length - suffix.length).trim();
        try { return parseSimple(head).mul(scale); } catch (e) { break; }
      }
    }
    return parseSimple(text);
  }

  function parseSimple(text) {
    if (text.indexOf('/') !== -1) {
      const parts = text.split('/');
      if (parts.length !== 2) throw new SolveError('cannot read the number "' + text + '"');
      return parseDecimal(parts[0].trim()).div(parseDecimal(parts[1].trim()));
    }
    return parseDecimal(text);
  }

  /* Render a value the way a student would write it in an answer. */
  function fmt(value) {
    if (value === null || value === undefined) return '-';
    const q = toQ(value);
    if (q.d === 1n) return String(q.n);
    const decimal = q.toNumber();
    const short = trimZeros(decimal.toFixed(6));
    if (short.length <= 8 && parseSimple(short).eq(q)) return short;
    if (q.d <= 100000n) return q.n + '/' + q.d + ' (' + trimZeros(decimal.toFixed(4)) + ')';
    return formatSig(decimal, 6);
  }

  function trimZeros(text) {
    if (text.indexOf('.') === -1) return text;
    return text.replace(/0+$/, '').replace(/\.$/, '');
  }

  function formatSig(value, digits) {
    if (value === 0) return '0';
    const magnitude = Math.abs(value);
    if (magnitude >= 1e-4 && magnitude < 1e7) {
      return trimZeros(value.toPrecision(digits));
    }
    return value.toExponential(Math.max(0, digits - 1)).replace(/e([+-])(\d)$/, 'e$1$2');
  }

  // ------------------------------------------------------------------- errors

  function SolveError(message) {
    this.name = 'SolveError';
    this.message = message;
  }
  SolveError.prototype = Object.create(Error.prototype);
  SolveError.prototype.constructor = SolveError;

  function CircuitError(message) {
    this.name = 'CircuitError';
    this.message = message;
  }
  CircuitError.prototype = Object.create(Error.prototype);
  CircuitError.prototype.constructor = CircuitError;

  function Singular(message, freeColumns) {
    this.name = 'Singular';
    this.message = message;
    this.freeColumns = freeColumns || [];
  }
  Singular.prototype = Object.create(Error.prototype);
  Singular.prototype.constructor = Singular;

  // ------------------------------------------------------- linear algebra

  function zeros(rows, cols) {
    const out = [];
    for (let r = 0; r < rows; r++) {
      const row = new Array(cols);
      for (let c = 0; c < cols; c++) row[c] = ZERO;
      out.push(row);
    }
    return out;
  }

  /* Exact Gauss-Jordan.  Throws Singular when A has no unique solution. */
  function solveLinear(matrix, rhs) {
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
      throw new Singular('the circuit equations do not have a unique solution', free);
    }

    const solution = new Array(n);
    for (let col = 0; col < n; col++) solution[col] = aug[pivotOfColumn[col]][n];
    return solution;
  }

  // ------------------------------------------------------------ circuit model

  const GROUND_NAMES = { '0': true, 'gnd': true, 'GND': true, 'ground': true };
  function isGround(node) { return Object.prototype.hasOwnProperty.call(GROUND_NAMES, node); }

  const KIND_SPEC = {
    R: [2, false, false], L: [2, false, false], C: [2, false, false],
    V: [2, false, false], I: [2, false, false], SW: [2, false, false],
    E: [2, true, false], G: [2, true, false],
    H: [2, false, true], F: [2, false, true],
    OPAMP: [3, false, false]
  };

  const PRETTY_KIND = {
    R: 'resistor', L: 'inductor', C: 'capacitor', V: 'voltage source',
    I: 'current source', SW: 'switch', E: 'VCVS', G: 'VCCS', H: 'CCVS',
    F: 'CCCS', OPAMP: 'op-amp'
  };

  const UNITS = { R: 'ohm', L: 'H', C: 'F', V: 'V', I: 'A' };

  function Element(spec) {
    this.kind = spec.kind;
    this.name = spec.name;
    this.nodes = spec.nodes.slice();
    this.value = spec.value == null ? null : toQ(spec.value);
    this.before = spec.before == null ? null : toQ(spec.before);
    this.after = spec.after == null ? null : toQ(spec.after);
    this.ctrlNodes = spec.ctrlNodes ? spec.ctrlNodes.slice() : null;
    this.ctrlElement = spec.ctrlElement || null;
    this.gain = spec.gain == null ? null : toQ(spec.gain);
    this.stateBefore = spec.stateBefore || null;
    this.stateAfter = spec.stateAfter || null;
    this.ic = spec.ic == null ? null : toQ(spec.ic);
  }

  Element.prototype.pretty = function () { return PRETTY_KIND[this.kind] || this.kind; };
  Element.prototype.sourceValue = function (window) {
    return window === 'before' ? this.before : this.after;
  };
  Element.prototype.state = function (window) {
    return window === 'before' ? this.stateBefore : this.stateAfter;
  };

  function Circuit(title) {
    this.title = title || 'circuit';
    this.elements = [];
    this.byName = {};
  }

  Circuit.prototype.add = function (element) {
    if (this.byName[element.name]) {
      throw new CircuitError('duplicate element name ' + element.name);
    }
    this.byName[element.name] = element;
    this.elements.push(element);
    return element;
  };

  Circuit.prototype.get = function (name) {
    const element = this.byName[name];
    if (!element) throw new CircuitError('no element named ' + name);
    return element;
  };

  Circuit.prototype.has = function (name) { return !!this.byName[name]; };

  Circuit.prototype.ofKind = function () {
    const kinds = Array.prototype.slice.call(arguments);
    return this.elements.filter(function (e) { return kinds.indexOf(e.kind) !== -1; });
  };

  Circuit.prototype.nodes = function () {
    const seen = [];
    this.elements.forEach(function (element) {
      element.nodes.forEach(function (node) {
        if (seen.indexOf(node) === -1) seen.push(node);
      });
      (element.ctrlNodes || []).forEach(function (node) {
        if (seen.indexOf(node) === -1) seen.push(node);
      });
    });
    const ground = seen.filter(isGround);
    const other = seen.filter(function (n) { return !isGround(n); }).sort(nodeSort);
    return ground.concat(other);
  };

  Circuit.prototype.freeNodes = function () {
    return this.nodes().filter(function (n) { return !isGround(n); });
  };

  Circuit.prototype.sourcesChange = function () {
    return this.ofKind('V', 'I').some(function (e) { return !e.before.eq(e.after); });
  };

  Circuit.prototype.switchesChange = function () {
    return this.ofKind('SW').some(function (e) { return e.stateBefore !== e.stateAfter; });
  };

  function nodeSort(a, b) {
    const na = /^\d+$/.test(a), nb = /^\d+$/.test(b);
    if (na && nb) return parseInt(a, 10) - parseInt(b, 10);
    if (na) return -1;
    if (nb) return 1;
    return a < b ? -1 : (a > b ? 1 : 0);
  }

  Circuit.prototype.validate = function () {
    const self = this;
    if (!this.elements.length) throw new CircuitError('the circuit is empty');
    const hasGround = this.elements.some(function (e) { return e.nodes.some(isGround); });
    if (!hasGround) {
      throw new CircuitError(
        'no ground node: mark one node as ground so voltages have a reference');
    }
    this.elements.forEach(function (element) {
      const spec = KIND_SPEC[element.kind];
      if (!spec) throw new CircuitError('unknown element kind ' + element.kind);
      if (element.nodes.length !== spec[0]) {
        throw new CircuitError(element.name + ' needs ' + spec[0] + ' nodes');
      }
      const unique = element.nodes.filter(function (n, i) {
        return element.nodes.indexOf(n) === i;
      });
      if (unique.length !== element.nodes.length) {
        throw new CircuitError(element.name + ' has both terminals on the same node');
      }
      if (['R', 'L', 'C'].indexOf(element.kind) !== -1) {
        if (element.value === null) throw new CircuitError(element.name + ' has no value');
        if (element.value.n <= 0n) {
          throw new CircuitError(element.name + ' must have a positive value (got '
            + fmt(element.value) + ')');
        }
      }
      if (['V', 'I'].indexOf(element.kind) !== -1) {
        if (element.before === null || element.after === null) {
          throw new CircuitError(element.name + ' needs a t<0 and a t>0 value');
        }
      }
      if (element.kind === 'SW') {
        [element.stateBefore, element.stateAfter].forEach(function (state) {
          if (state !== 'open' && state !== 'closed') {
            throw new CircuitError(element.name + ' state must be open or closed');
          }
        });
      }
      if (spec[1] && (!element.ctrlNodes || element.ctrlNodes.length !== 2)) {
        throw new CircuitError(element.name + ' needs a controlling node pair');
      }
      if (spec[2]) {
        if (!element.ctrlElement) {
          throw new CircuitError(element.name + ' needs a controlling element');
        }
        if (!self.has(element.ctrlElement)) {
          throw new CircuitError(element.name + ' is controlled by '
            + element.ctrlElement + ', which does not exist');
        }
      }
      if (['E', 'G', 'H', 'F'].indexOf(element.kind) !== -1 && element.gain === null) {
        throw new CircuitError(element.name + ' has no gain');
      }
    });

    this.ofKind('F', 'H').forEach(function (element) {
      const seen = {};
      let cursor = element;
      while (cursor && (cursor.kind === 'F' || cursor.kind === 'H')) {
        if (seen[cursor.name]) {
          throw new CircuitError('current-control loop involving ' + element.name
            + ': its controlling current depends on itself');
        }
        seen[cursor.name] = true;
        cursor = self.get(cursor.ctrlElement);
      }
    });
    return this;
  };

  // ------------------------------------------------------------------- netlist

  function parseSourceSpec(name, tokens) {
    if (!tokens.length) throw new CircuitError(name + ' has no value');
    const head = tokens[0].toLowerCase();
    if (head === 'dc') {
      if (tokens.length !== 2) throw new CircuitError(name + ': dc takes one value');
      const value = toQ(tokens[1]);
      return [value, value];
    }
    if (head === 'step' || head === 'u') {
      if (tokens.length !== 2) throw new CircuitError(name + ': step takes one value');
      return [ZERO, toQ(tokens[1])];
    }
    if (tokens.length === 1) {
      const value = toQ(tokens[0]);
      return [value, value];
    }
    if (tokens.length === 2) return [toQ(tokens[0]), toQ(tokens[1])];
    throw new CircuitError(name + ': cannot read the value ' + tokens.join(' '));
  }

  function elementKind(name) {
    const upper = name.toUpperCase();
    if (upper.indexOf('SW') === 0) return 'SW';
    if (upper.indexOf('OP') === 0 || upper.indexOf('OA') === 0) return 'OPAMP';
    const letter = upper.charAt(0);
    if ('RLCVIEGHF'.indexOf(letter) !== -1) return letter;
    throw new CircuitError('cannot tell what kind of element ' + name + ' is');
  }

  function parseNetlist(text, title) {
    const circuit = new Circuit(title);
    const lines = String(text).split(/\r?\n/);
    for (let index = 0; index < lines.length; index++) {
      let line = lines[index].split('#')[0].split(';')[0].trim();
      if (!line) continue;
      if (line.toLowerCase().indexOf('.title ') === 0) {
        circuit.title = line.slice(7).trim();
        continue;
      }
      if (line.charAt(0) === '.') continue;
      const tokens = line.split(/\s+/);
      const name = tokens[0];
      const rest = tokens.slice(1);
      try {
        const kind = elementKind(name);
        if (['R', 'L', 'C'].indexOf(kind) !== -1) {
          if (rest.length < 3) throw new CircuitError(name + ' needs two nodes and a value');
          let ic = null;
          for (let k = 3; k < rest.length; k++) {
            if (rest[k].toLowerCase().indexOf('ic=') === 0) ic = toQ(rest[k].slice(3));
            else throw new CircuitError(name + ': unexpected ' + rest[k]);
          }
          circuit.add(new Element({
            kind: kind, name: name, nodes: rest.slice(0, 2), value: rest[2], ic: ic
          }));
        } else if (kind === 'V' || kind === 'I') {
          if (rest.length < 3) throw new CircuitError(name + ' needs two nodes and a value');
          const pair = parseSourceSpec(name, rest.slice(2));
          circuit.add(new Element({
            kind: kind, name: name, nodes: rest.slice(0, 2),
            before: pair[0], after: pair[1]
          }));
        } else if (kind === 'SW') {
          if (rest.length !== 4) {
            throw new CircuitError(name + ' needs two nodes then its t<0 and t>0 states');
          }
          circuit.add(new Element({
            kind: kind, name: name, nodes: rest.slice(0, 2),
            stateBefore: rest[2].toLowerCase(), stateAfter: rest[3].toLowerCase()
          }));
        } else if (kind === 'E' || kind === 'G') {
          if (rest.length !== 5) {
            throw new CircuitError(name + ' needs two nodes, two control nodes and a gain');
          }
          circuit.add(new Element({
            kind: kind, name: name, nodes: rest.slice(0, 2),
            ctrlNodes: rest.slice(2, 4), gain: rest[4]
          }));
        } else if (kind === 'H' || kind === 'F') {
          if (rest.length !== 4) {
            throw new CircuitError(name + ' needs two nodes, a controlling element and a gain');
          }
          circuit.add(new Element({
            kind: kind, name: name, nodes: rest.slice(0, 2),
            ctrlElement: rest[2], gain: rest[3]
          }));
        } else if (kind === 'OPAMP') {
          if (rest.length !== 3) throw new CircuitError(name + ' needs in+, in- and out nodes');
          circuit.add(new Element({ kind: kind, name: name, nodes: rest }));
        }
      } catch (error) {
        throw new CircuitError('line ' + (index + 1) + ': ' + error.message);
      }
    }
    return circuit.validate();
  }

  function toNetlist(circuit) {
    const lines = ['.title ' + circuit.title];
    circuit.elements.forEach(function (e) {
      let row;
      if (['R', 'L', 'C'].indexOf(e.kind) !== -1) {
        row = [e.name, e.nodes[0], e.nodes[1], e.value.toString()].join(' ');
        if (e.ic !== null) row += ' ic=' + e.ic.toString();
      } else if (e.kind === 'V' || e.kind === 'I') {
        let spec;
        if (e.before.eq(e.after)) spec = 'dc ' + e.after.toString();
        else if (e.before.isZero()) spec = 'step ' + e.after.toString();
        else spec = e.before.toString() + ' ' + e.after.toString();
        row = [e.name, e.nodes[0], e.nodes[1], spec].join(' ');
      } else if (e.kind === 'SW') {
        row = [e.name, e.nodes[0], e.nodes[1], e.stateBefore, e.stateAfter].join(' ');
      } else if (e.kind === 'E' || e.kind === 'G') {
        row = [e.name, e.nodes[0], e.nodes[1], e.ctrlNodes[0], e.ctrlNodes[1],
          e.gain.toString()].join(' ');
      } else if (e.kind === 'H' || e.kind === 'F') {
        row = [e.name, e.nodes[0], e.nodes[1], e.ctrlElement, e.gain.toString()].join(' ');
      } else {
        row = [e.name].concat(e.nodes).join(' ');
      }
      lines.push(row);
    });
    return lines.join('\n') + '\n';
  }

  // ----------------------------------------------------------------- MNA

  const CURRENT_UNKNOWN_ROLES = ['short', 'vsrc', 'vsrc_indep', 'vctrl'];

  function roleOf(element, window, storage) {
    const kind = element.kind;
    if (kind === 'R') return 'resistor';
    if (kind === 'L') return storage === 'dc' ? 'short' : 'isrc';
    if (kind === 'C') return storage === 'dc' ? 'open' : 'vsrc';
    if (kind === 'V') return 'vsrc_indep';
    if (kind === 'I') return 'isrc_indep';
    if (kind === 'SW') return element.state(window) === 'closed' ? 'short' : 'open';
    if (kind === 'E' || kind === 'H' || kind === 'OPAMP') return 'vctrl';
    if (kind === 'G' || kind === 'F') return 'ictrl';
    throw new CircuitError('no analysis role for element kind ' + kind);
  }

  function MnaSystem(circuit, window, storage) {
    const self = this;
    this.circuit = circuit;
    this.window = window;
    this.storage = storage;

    this.nodeNames = circuit.freeNodes();
    this.nodeIndex = {};
    this.nodeNames.forEach(function (name, i) { self.nodeIndex[name] = i; });

    this.roles = {};
    circuit.elements.forEach(function (e) {
      self.roles[e.name] = roleOf(e, window, storage);
    });

    this.currentElements = circuit.elements.filter(function (e) {
      return CURRENT_UNKNOWN_ROLES.indexOf(self.roles[e.name]) !== -1;
    });
    const offset = this.nodeNames.length;
    this.currentIndex = {};
    this.currentElements.forEach(function (e, i) { self.currentIndex[e.name] = offset + i; });

    this.size = this.nodeNames.length + this.currentElements.length;
    this.labels = this.nodeNames.map(function (n) { return 'V(' + n + ')'; })
      .concat(this.currentElements.map(function (e) { return 'i(' + e.name + ')'; }));
    this.rowLabels = this.nodeNames.map(function (n) { return 'KCL at node ' + n; })
      .concat(this.currentElements.map(function (e) { return self.constraintLabel(e); }));

    this.matrix = zeros(this.size, this.size);
    this.buildMatrix();
  }

  MnaSystem.prototype.col = function (node) {
    if (isGround(node)) return null;
    if (!(node in this.nodeIndex)) throw new CircuitError('unknown node ' + node);
    return this.nodeIndex[node];
  };

  MnaSystem.prototype.constraintLabel = function (element) {
    const role = this.roles[element.name];
    if (role === 'short') {
      return element.kind === 'L' ? element.name + ' is a short'
        : element.name + ' is closed';
    }
    if (role === 'vsrc') return element.name + ' holds its voltage';
    if (role === 'vsrc_indep') return element.name + ' sets its voltage';
    if (element.kind === 'OPAMP') return element.name + ' virtual short';
    return element.name + ' defining equation';
  };

  /* (node, sign) pairs: sign is +1 where the current leaves through the element. */
  MnaSystem.prototype.kclTerminals = function (element) {
    if (element.kind === 'OPAMP') {
      return [[element.nodes[2], ONE.neg()]];
    }
    return [[element.nodes[0], ONE], [element.nodes[1], ONE.neg()]];
  };

  MnaSystem.prototype.addAt = function (row, col, value) {
    if (row === null || col === null) return;
    this.matrix[row][col] = this.matrix[row][col].add(value);
  };

  MnaSystem.prototype.buildMatrix = function () {
    const self = this;
    this.circuit.elements.forEach(function (element) {
      const role = self.roles[element.name];
      if (role === 'resistor') self.stampResistor(element);
      else if (role === 'ictrl') self.stampControlledCurrent(element);
      else if (CURRENT_UNKNOWN_ROLES.indexOf(role) !== -1) self.stampCurrentUnknown(element);
      // open, isrc and isrc_indep contribute to b only.
    });
  };

  MnaSystem.prototype.stampResistor = function (element) {
    const a = this.col(element.nodes[0]);
    const b = this.col(element.nodes[1]);
    const g = ONE.div(element.value);
    this.addAt(a, a, g);
    this.addAt(a, b, g.neg());
    this.addAt(b, a, g.neg());
    this.addAt(b, b, g);
  };

  MnaSystem.prototype.stampCurrentUnknown = function (element) {
    const self = this;
    const k = this.currentIndex[element.name];
    this.kclTerminals(element).forEach(function (pair) {
      self.addAt(self.col(pair[0]), k, pair[1]);
    });

    const row = k;
    if (element.kind === 'OPAMP') {
      this.addAt(row, this.col(element.nodes[0]), ONE);
      this.addAt(row, this.col(element.nodes[1]), ONE.neg());
      return;
    }

    this.addAt(row, this.col(element.nodes[0]), ONE);
    this.addAt(row, this.col(element.nodes[1]), ONE.neg());

    if (element.kind === 'E') {
      this.addAt(row, this.col(element.ctrlNodes[0]), element.gain.neg());
      this.addAt(row, this.col(element.ctrlNodes[1]), element.gain);
    } else if (element.kind === 'H') {
      const form = this.currentForm(this.circuit.get(element.ctrlElement));
      Object.keys(form).forEach(function (col) {
        self.addAt(row, parseInt(col, 10), element.gain.neg().mul(form[col]));
      });
    }
  };

  MnaSystem.prototype.stampControlledCurrent = function (element) {
    const self = this;
    const form = this.currentForm(element);
    this.kclTerminals(element).forEach(function (pair) {
      const row = self.col(pair[0]);
      Object.keys(form).forEach(function (col) {
        self.addAt(row, parseInt(col, 10), pair[1].mul(form[col]));
      });
    });
  };

  /* The part of a branch current that depends on the unknowns. */
  MnaSystem.prototype.currentForm = function (element) {
    const self = this;
    const role = this.roles[element.name];
    if (CURRENT_UNKNOWN_ROLES.indexOf(role) !== -1) {
      const form = {};
      form[this.currentIndex[element.name]] = ONE;
      return form;
    }
    if (role === 'resistor') {
      const g = ONE.div(element.value);
      return combine({}, this.col(element.nodes[0]), g, this.col(element.nodes[1]), g.neg());
    }
    if (role === 'open' || role === 'isrc' || role === 'isrc_indep') return {};
    if (role === 'ictrl') {
      if (element.kind === 'G') {
        return combine({}, this.col(element.ctrlNodes[0]), element.gain,
          this.col(element.ctrlNodes[1]), element.gain.neg());
      }
      const base = this.currentForm(this.circuit.get(element.ctrlElement));
      const out = {};
      Object.keys(base).forEach(function (col) { out[col] = element.gain.mul(base[col]); });
      return out;
    }
    throw new CircuitError('cannot express the current through ' + element.name);
  };

  /* The part of a branch current that is already a plain number. */
  MnaSystem.prototype.knownCurrent = function (element, sourceValues, storageValues) {
    const role = this.roles[element.name];
    if (role === 'isrc') return storageValues[element.name];
    if (role === 'isrc_indep') return sourceValues[element.name];
    if (role === 'ictrl' && element.kind === 'F') {
      const inner = this.knownCurrent(this.circuit.get(element.ctrlElement),
        sourceValues, storageValues);
      return element.gain.mul(inner);
    }
    return ZERO;
  };

  MnaSystem.prototype.buildRhs = function (sourceValues, storageValues) {
    const self = this;
    const rhs = [];
    for (let i = 0; i < this.size; i++) rhs.push(ZERO);

    function inject(tail, head, current) {
      const t = self.col(tail);
      const h = self.col(head);
      if (t !== null) rhs[t] = rhs[t].sub(current);
      if (h !== null) rhs[h] = rhs[h].add(current);
    }

    this.circuit.elements.forEach(function (element) {
      const role = self.roles[element.name];
      if (role === 'isrc' || role === 'isrc_indep') {
        inject(element.nodes[0], element.nodes[1],
          self.knownCurrent(element, sourceValues, storageValues));
      } else if (role === 'vsrc_indep') {
        rhs[self.currentIndex[element.name]] = sourceValues[element.name];
      } else if (role === 'vsrc') {
        rhs[self.currentIndex[element.name]] = storageValues[element.name];
      } else if (role === 'ictrl') {
        const known = self.knownCurrent(element, sourceValues, storageValues);
        if (!known.isZero()) inject(element.nodes[0], element.nodes[1], known);
      } else if (role === 'vctrl' && element.kind === 'H') {
        const known = self.knownCurrent(self.circuit.get(element.ctrlElement),
          sourceValues, storageValues);
        if (!known.isZero()) {
          const k = self.currentIndex[element.name];
          rhs[k] = rhs[k].add(element.gain.mul(known));
        }
      }
    });
    return rhs;
  };

  MnaSystem.prototype.solve = function (sourceValues, storageValues) {
    const rhs = this.buildRhs(sourceValues, storageValues);
    const x = solveLinear(this.matrix, rhs);
    return new Solution(this, x, sourceValues, storageValues, rhs);
  };

  MnaSystem.prototype.equationLines = function (rhs) {
    const lines = [];
    for (let r = 0; r < this.size; r++) {
      const terms = [];
      for (let c = 0; c < this.size; c++) {
        const coef = this.matrix[r][c];
        if (coef.isZero()) continue;
        terms.push(term(coef, this.labels[c], terms.length === 0));
      }
      lines.push({
        label: this.rowLabels[r],
        left: terms.length ? terms.join(' ') : '0',
        right: fmt(rhs[r])
      });
    }
    return lines;
  };

  function combine(target, colA, coefA, colB, coefB) {
    [[colA, coefA], [colB, coefB]].forEach(function (pair) {
      if (pair[0] === null) return;
      const key = pair[0];
      target[key] = (target[key] || ZERO).add(pair[1]);
    });
    return target;
  }

  function term(coef, label, first) {
    const negative = coef.isNeg();
    const magnitude = negative ? coef.neg() : coef;
    const body = magnitude.eq(ONE) ? label : fmt(magnitude) + '*' + label;
    if (first) return (negative ? '-' : '') + body;
    return (negative ? '- ' : '+ ') + body;
  }

  function Solution(system, x, sourceValues, storageValues, rhs) {
    this.system = system;
    this.x = x;
    this.sourceValues = sourceValues;
    this.storageValues = storageValues;
    this.rhs = rhs;
  }

  Solution.prototype.nodeVoltage = function (node) {
    if (isGround(node)) return ZERO;
    return this.x[this.system.nodeIndex[node]];
  };

  Solution.prototype.elementVoltage = function (element) {
    if (element.kind === 'OPAMP') return this.nodeVoltage(element.nodes[2]);
    return this.nodeVoltage(element.nodes[0]).sub(this.nodeVoltage(element.nodes[1]));
  };

  Solution.prototype.elementCurrent = function (element) {
    const system = this.system;
    const role = system.roles[element.name];
    if (CURRENT_UNKNOWN_ROLES.indexOf(role) !== -1) {
      return this.x[system.currentIndex[element.name]];
    }
    if (role === 'resistor') return this.elementVoltage(element).div(element.value);
    if (role === 'open') return ZERO;
    if (role === 'isrc' || role === 'isrc_indep') {
      return system.knownCurrent(element, this.sourceValues, this.storageValues);
    }
    if (role === 'ictrl') {
      if (element.kind === 'G') {
        return element.gain.mul(this.nodeVoltage(element.ctrlNodes[0])
          .sub(this.nodeVoltage(element.ctrlNodes[1])));
      }
      return element.gain.mul(this.elementCurrent(system.circuit.get(element.ctrlElement)));
    }
    throw new CircuitError('cannot report the current through ' + element.name);
  };

  // -------------------------------------------------------------- analysis

  function AnalysisError(message) {
    this.name = 'AnalysisError';
    this.message = message;
  }
  AnalysisError.prototype = Object.create(Error.prototype);
  AnalysisError.prototype.constructor = AnalysisError;

  const PHASE_ORDER = ['t<0', '0+', 'd/dt', 'inf'];

  function sourceValues(circuit, window) {
    const out = {};
    circuit.ofKind('V', 'I').forEach(function (e) { out[e.name] = e.sourceValue(window); });
    return out;
  }

  function analyse(circuit) {
    circuit.validate();
    const storage = circuit.ofKind('L', 'C');
    const result = {
      circuit: circuit,
      phases: {},
      initialConditions: {},
      icSources: {},
      derivativeStorage: {},
      notes: []
    };

    noteAssumptions(circuit, result, storage);

    // phase 1: t < 0
    const givenIcs = {};
    storage.forEach(function (e) { if (e.ic !== null) givenIcs[e.name] = e.ic; });
    const allIcsGiven = storage.length > 0 && Object.keys(givenIcs).length === storage.length;

    const beforeSystem = new MnaSystem(circuit, 'before', 'dc');
    try {
      const solution = beforeSystem.solve(sourceValues(circuit, 'before'), {});
      result.phases['t<0'] = {
        key: 't<0', title: 'Steady state before switching',
        system: beforeSystem, solution: solution,
        description: describeDc(circuit, 'before')
      };
    } catch (error) {
      if (!(error instanceof Singular)) throw error;
      const reason = diagnose(beforeSystem, error);
      if (!allIcsGiven) {
        throw new AnalysisError('The t < 0 circuit has no unique steady state: ' + reason
          + ' If the question states the starting values, set them on the components '
          + 'as initial conditions and the solver will use those instead.');
      }
      result.notes.push('The t < 0 circuit has no unique steady state (' + reason
        + ') so the given initial conditions are used directly.');
    }

    storage.forEach(function (element) {
      if (element.name in givenIcs) {
        result.initialConditions[element.name] = givenIcs[element.name];
        result.icSources[element.name] = 'given';
      } else {
        const solution = result.phases['t<0'].solution;
        result.initialConditions[element.name] = element.kind === 'L'
          ? solution.elementCurrent(element)
          : solution.elementVoltage(element);
        result.icSources[element.name] = 'solved';
      }
    });

    // phase 2: t = 0+
    const zeroPlusSystem = new MnaSystem(circuit, 'after', 'ic');
    let zeroPlus;
    try {
      zeroPlus = zeroPlusSystem.solve(sourceValues(circuit, 'after'),
        result.initialConditions);
    } catch (error) {
      if (!(error instanceof Singular)) throw error;
      throw new AnalysisError('At t = 0+: ' + diagnose(zeroPlusSystem, error));
    }
    result.phases['0+'] = {
      key: '0+', title: 'The instant after switching',
      system: zeroPlusSystem, solution: zeroPlus,
      description: describeIc(circuit, result.initialConditions)
    };

    // phase 3: derivatives at 0+
    storage.forEach(function (element) {
      result.derivativeStorage[element.name] = element.kind === 'L'
        ? zeroPlus.elementVoltage(element).div(element.value)
        : zeroPlus.elementCurrent(element).div(element.value);
    });
    const zeroSources = {};
    circuit.ofKind('V', 'I').forEach(function (e) { zeroSources[e.name] = ZERO; });
    let derivatives;
    try {
      derivatives = zeroPlusSystem.solve(zeroSources, result.derivativeStorage);
    } catch (error) {
      if (!(error instanceof Singular)) throw error;
      throw new AnalysisError('While differentiating at 0+: '
        + diagnose(zeroPlusSystem, error));
    }
    result.phases['d/dt'] = {
      key: 'd/dt', title: 'First derivatives at t = 0+',
      system: zeroPlusSystem, solution: derivatives,
      description: describeDerivative(circuit, result.derivativeStorage)
    };

    // phase 4: t -> infinity
    const finalSystem = new MnaSystem(circuit, 'after', 'dc');
    try {
      const final = finalSystem.solve(sourceValues(circuit, 'after'), {});
      result.phases.inf = {
        key: 'inf', title: 'Steady state long after switching',
        system: finalSystem, solution: final,
        description: describeDc(circuit, 'after')
      };
    } catch (error) {
      if (!(error instanceof Singular)) throw error;
      result.notes.push('There is no final steady state to report: '
        + diagnose(finalSystem, error)
        + ' Physically this circuit does not settle to fixed values, which is what '
        + 'an integrator or a source-free floating node looks like.');
    }

    result.value = function (phaseKey, elementName, quantity) {
      const phase = result.phases[phaseKey];
      if (!phase) return null;
      const element = circuit.get(elementName);
      return quantity === 'v' ? phase.solution.elementVoltage(element)
        : phase.solution.elementCurrent(element);
    };
    result.node = function (phaseKey, nodeName) {
      const phase = result.phases[phaseKey];
      return phase ? phase.solution.nodeVoltage(nodeName) : null;
    };
    return result;
  }

  function describeDc(circuit, window) {
    const lines = [];
    circuit.ofKind('L').forEach(function (e) {
      lines.push(e.name + ' becomes a short circuit (steady state, so v = L di/dt = 0)');
    });
    circuit.ofKind('C').forEach(function (e) {
      lines.push(e.name + ' becomes an open circuit (steady state, so i = C dv/dt = 0)');
    });
    circuit.ofKind('V', 'I').forEach(function (e) {
      if (!e.before.eq(e.after)) {
        const value = e.sourceValue(window);
        lines.push(e.name + ' is at ' + fmt(value) + ' ' + (e.kind === 'V' ? 'V' : 'A')
          + ' (' + (value.isZero() ? 'off' : 'on') + ' here)');
      }
    });
    circuit.ofKind('SW').forEach(function (e) {
      lines.push(e.name + ' is ' + e.state(window));
    });
    return lines;
  }

  function describeIc(circuit, initialConditions) {
    const lines = [];
    circuit.ofKind('L').forEach(function (e) {
      lines.push(e.name + ' becomes a current source of ' + fmt(initialConditions[e.name])
        + ' A, because inductor current cannot jump');
    });
    circuit.ofKind('C').forEach(function (e) {
      lines.push(e.name + ' becomes a voltage source of ' + fmt(initialConditions[e.name])
        + ' V, because capacitor voltage cannot jump');
    });
    circuit.ofKind('V', 'I').forEach(function (e) {
      if (!e.before.eq(e.after)) {
        lines.push(e.name + ' is at its t > 0 value of ' + fmt(e.after) + ' '
          + (e.kind === 'V' ? 'V' : 'A'));
      }
    });
    circuit.ofKind('SW').forEach(function (e) {
      lines.push(e.name + ' is ' + e.stateAfter);
    });
    return lines;
  }

  function describeDerivative(circuit, derivativeStorage) {
    const lines = [
      'the same equations as t = 0+, differentiated once with respect to time',
      'every source is constant for t > 0, so all source terms become 0'
    ];
    circuit.ofKind('L').forEach(function (e) {
      lines.push(e.name + ' carries di/dt = v_L(0+)/L = '
        + fmt(derivativeStorage[e.name]) + ' A/s');
    });
    circuit.ofKind('C').forEach(function (e) {
      lines.push(e.name + ' holds dv/dt = i_C(0+)/C = '
        + fmt(derivativeStorage[e.name]) + ' V/s');
    });
    return lines;
  }

  function noteAssumptions(circuit, result, storage) {
    if (!storage.length) {
      result.notes.push('There are no inductors or capacitors, so nothing changes '
        + 'with time: every column below gives the same answer.');
    }
    if (circuit.ofKind('L').length && !circuit.ofKind('R').length) {
      result.notes.push('This circuit has no resistance in it. A lossless LC circuit '
        + 'rings forever, so the final column is the steady state the equations give, '
        + 'not a value the circuit actually settles at.');
    }
    if (!circuit.sourcesChange() && !circuit.switchesChange()) {
      result.notes.push('No source steps and no switch changes state at t = 0, so the '
        + 'circuit is already in steady state and nothing transient happens.');
    }
    if (circuit.ofKind('OPAMP').length) {
      result.notes.push('Op-amps are treated as ideal: infinite gain, no input current, '
        + 'and an output that can supply whatever it needs to. The solver assumes the '
        + 'op-amp stays in its linear region.');
    }
  }

  // ------------------------------------------------------------- diagnosis

  const CONDUCTIVE_ROLES = ['resistor', 'short', 'vsrc', 'vsrc_indep'];

  function diagnose(system, error) {
    const floating = floatingNodes(system);
    if (floating.length) {
      const hint = 'its voltage is not determined by anything. Give it a resistive '
        + 'path to ground, or set an initial condition on the capacitor.';
      if (floating.length === 1) {
        return 'node ' + floating[0] + ' is isolated in this configuration, so ' + hint;
      }
      return 'nodes ' + floating.join(', ') + ' are isolated in this configuration, so '
        + hint;
    }
    const conflict = voltageConflict(system);
    if (conflict) return conflict;
    if (system.circuit.ofKind('OPAMP').length) {
      return 'the equations are inconsistent. With an ideal op-amp this usually means '
        + 'there is no negative feedback path from the output back to the inverting input.';
    }
    const undetermined = (error.freeColumns || [])
      .filter(function (c) { return c < system.labels.length; })
      .map(function (c) { return system.labels[c]; });
    if (undetermined.length) {
      return 'the equations do not pin down ' + undetermined.join(', ')
        + '. Check for a loop of voltage sources, or current sources in series.';
    }
    return 'the equations have no unique solution. Check for a loop of voltage sources, '
      + 'or current sources in series with each other.';
  }

  function floatingNodes(system) {
    const parent = {};
    system.circuit.nodes().forEach(function (n) { parent[n] = n; });

    function find(node) {
      while (parent[node] !== node) {
        parent[node] = parent[parent[node]];
        node = parent[node];
      }
      return node;
    }
    function union(a, b) {
      const ra = find(a), rb = find(b);
      if (ra !== rb) parent[ra] = rb;
    }

    const ground = system.circuit.nodes().filter(isGround);
    for (let i = 1; i < ground.length; i++) union(ground[i], ground[0]);

    system.circuit.elements.forEach(function (element) {
      const role = system.roles[element.name];
      if (CONDUCTIVE_ROLES.indexOf(role) !== -1) {
        union(element.nodes[0], element.nodes[1]);
      } else if (role === 'vctrl') {
        if (element.kind === 'OPAMP') union(element.nodes[2], ground[0]);
        else union(element.nodes[0], element.nodes[1]);
      }
    });

    const root = find(ground[0]);
    return system.circuit.freeNodes().filter(function (n) { return find(n) !== root; });
  }

  function voltageConflict(system) {
    const seen = {};
    let found = null;
    system.circuit.elements.forEach(function (element) {
      if (found) return;
      const role = system.roles[element.name];
      if (['vsrc', 'vsrc_indep', 'short'].indexOf(role) === -1) return;
      const key = element.nodes.slice(0, 2).sort().join('|');
      if (seen[key]) {
        found = seen[key] + ' and ' + element.name + ' are both connected straight '
          + 'across the same pair of nodes, so they fight over the same voltage.';
        return;
      }
      seen[key] = element.name;
    });
    return found;
  }

  // ------------------------------------------------------------------ exports

  root.CircuitSolver = {
    Q: Q, toQ: toQ, fmt: fmt, ZERO: ZERO, ONE: ONE,
    Circuit: Circuit, Element: Element,
    parseNetlist: parseNetlist, toNetlist: toNetlist,
    MnaSystem: MnaSystem, analyse: analyse,
    isGround: isGround, PHASE_ORDER: PHASE_ORDER,
    PRETTY_KIND: PRETTY_KIND, UNITS: UNITS,
    CircuitError: CircuitError, AnalysisError: AnalysisError, Singular: Singular,
    solveLinear: solveLinear
  };
}(typeof module !== 'undefined' && module.exports ? module.exports : window));
