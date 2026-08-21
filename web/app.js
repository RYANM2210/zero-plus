/* Schematic editor and results view.
 *
 * The editor owns geometry only.  Everything electrical -- which terminals
 * share a node, what the equations are, what the answers are -- comes from
 * CircuitSolver, which is the same code the Python test suite validates.
 */
(function () {
  'use strict';

  const S = window.CircuitSolver;
  const GRID = 22;
  const COLS = 46;   // only used to centre an empty sheet
  const ROWS = 26;
  const LIMIT = 400; // how far from the origin a part may be dragged
  const SVG_NS = 'http://www.w3.org/2000/svg';

  // Two-terminal parts are placed by dragging; these are placed by clicking.
  const CLICK_PLACED = { GND: true, OPAMP: true };

  const CATALOG = [
    { kind: 'R', label: 'Resistor', prefix: 'R' },
    { kind: 'C', label: 'Capacitor', prefix: 'C' },
    { kind: 'L', label: 'Inductor', prefix: 'L' },
    { kind: 'V', label: 'Voltage src', prefix: 'V' },
    { kind: 'I', label: 'Current src', prefix: 'I' },
    { kind: 'SW', label: 'Switch', prefix: 'SW' },
    { kind: 'GND', label: 'Ground', prefix: 'GND' },
    { kind: 'E', label: 'VCVS', prefix: 'E' },
    { kind: 'G', label: 'VCCS', prefix: 'G' },
    { kind: 'H', label: 'CCVS', prefix: 'H' },
    { kind: 'F', label: 'CCCS', prefix: 'F' },
    { kind: 'OPAMP', label: 'Op-amp', prefix: 'OP' }
  ];

  const state = {
    parts: [],
    wires: [],
    tool: 'select',
    selected: null,
    nextId: 1,
    pick: null,
    result: null,
    error: null,
    overlayPhase: '0+',
    showVoltages: false
  };

  let drag = null;
  const nodeMap = { byPoint: {}, names: [], labelAt: {} };

  // ------------------------------------------------------------ geometry

  function key(p) { return p.x + ',' + p.y; }
  function px(v) { return v * GRID; }
  function samePoint(a, b) { return a.x === b.x && a.y === b.y; }

  function terminalsOf(part) {
    if (part.kind === 'GND') return [part.a];
    if (part.kind === 'OPAMP') return [part.a, part.b, part.c];
    return [part.a, part.b];
  }

  function allPointsOf(part) {
    const points = terminalsOf(part).slice();
    if (part.ctrlA) points.push(part.ctrlA);
    if (part.ctrlB) points.push(part.ctrlB);
    return points;
  }

  function clampPoint(p) {
    return {
      x: Math.max(-LIMIT, Math.min(LIMIT, p.x)),
      y: Math.max(-LIMIT, Math.min(LIMIT, p.y))
    };
  }

  /* Walk a wire cell by cell so a terminal touching it anywhere joins the node. */
  function wirePoints(wire) {
    const points = [];
    const dx = Math.sign(wire.b.x - wire.a.x);
    const dy = Math.sign(wire.b.y - wire.a.y);
    const steps = Math.max(Math.abs(wire.b.x - wire.a.x), Math.abs(wire.b.y - wire.a.y));
    for (let i = 0; i <= steps; i++) {
      points.push({ x: wire.a.x + dx * i, y: wire.a.y + dy * i });
    }
    return points;
  }

  // -------------------------------------------------------- node extraction

  function computeNodes() {
    const parent = {};
    function find(k) {
      if (!(k in parent)) { parent[k] = k; return k; }
      while (parent[k] !== k) { parent[k] = parent[parent[k]]; k = parent[k]; }
      return k;
    }
    function union(a, b) {
      const ra = find(a), rb = find(b);
      if (ra !== rb) parent[ra] = rb;
    }

    state.parts.forEach(function (part) {
      allPointsOf(part).forEach(function (p) { find(key(p)); });
    });
    state.wires.forEach(function (wire) {
      const points = wirePoints(wire);
      points.forEach(function (p) { find(key(p)); });
      for (let i = 1; i < points.length; i++) union(key(points[i - 1]), key(points[i]));
    });

    // Every ground symbol pins its point to the same reference node.
    const grounds = state.parts.filter(function (p) { return p.kind === 'GND'; });
    let groundRoot = null;
    grounds.forEach(function (part) {
      if (groundRoot === null) groundRoot = find(key(part.a));
      else union(find(key(part.a)), groundRoot);
    });
    if (groundRoot !== null) groundRoot = find(groundRoot);

    // Number the remaining nodes top-left first so the labels read sensibly.
    const members = {};
    Object.keys(parent).forEach(function (k) {
      const root = find(k);
      (members[root] = members[root] || []).push(k);
    });

    function anchorOf(root) {
      let best = null;
      members[root].forEach(function (k) {
        const parts = k.split(',');
        const point = { x: +parts[0], y: +parts[1] };
        if (!best || point.y < best.y || (point.y === best.y && point.x < best.x)) {
          best = point;
        }
      });
      return best;
    }

    const roots = Object.keys(members).filter(function (r) { return r !== groundRoot; });
    roots.sort(function (a, b) {
      const pa = anchorOf(a), pb = anchorOf(b);
      return pa.y - pb.y || pa.x - pb.x;
    });

    const nameOfRoot = {};
    if (groundRoot !== null) nameOfRoot[groundRoot] = '0';
    roots.forEach(function (root, index) { nameOfRoot[root] = String(index + 1); });

    nodeMap.byPoint = {};
    nodeMap.names = [];
    nodeMap.labelAt = {};
    Object.keys(members).forEach(function (root) {
      const name = nameOfRoot[root];
      if (nodeMap.names.indexOf(name) === -1) nodeMap.names.push(name);
      members[root].forEach(function (k) { nodeMap.byPoint[k] = name; });
      nodeMap.labelAt[name] = anchorOf(root);
    });
    return nodeMap;
  }

  function nodeAt(point) { return nodeMap.byPoint[key(point)] || null; }

  // ---------------------------------------------------------- netlist build

  function buildNetlist() {
    computeNodes();
    const lines = [];
    const problems = [];

    if (!state.parts.some(function (p) { return p.kind === 'GND'; })) {
      problems.push('Place a ground symbol. Every voltage has to be measured '
        + 'against something.');
    }

    const seenNames = {};
    state.parts.forEach(function (part) {
      if (part.kind === 'GND') return;
      if (seenNames[part.name]) {
        problems.push('Two parts are both called ' + part.name
          + '. Rename one of them.');
      }
      seenNames[part.name] = true;
    });

    state.parts.forEach(function (part) {
      if (part.kind === 'GND') return;
      const nodes = terminalsOf(part).map(nodeAt);
      if (nodes.some(function (n) { return n === null; })) {
        problems.push(part.name + ' has a terminal that is not connected to anything.');
        return;
      }
      const distinct = nodes.filter(function (n, i) { return nodes.indexOf(n) === i; });
      if (distinct.length !== nodes.length) {
        problems.push(part.name + ' has two terminals shorted to the same node, '
          + 'so it does nothing. Move it or delete the wire across it.');
        return;
      }

      const k = part.kind;
      if (k === 'R' || k === 'L' || k === 'C') {
        let line = [part.name, nodes[0], nodes[1], part.value || '0'].join(' ');
        if (part.ic !== undefined && part.ic !== null && String(part.ic).trim() !== '') {
          line += ' ic=' + String(part.ic).trim();
        }
        lines.push(line);
      } else if (k === 'V' || k === 'I') {
        lines.push([part.name, nodes[0], nodes[1],
          String(part.before || '0'), String(part.after || '0')].join(' '));
      } else if (k === 'SW') {
        lines.push([part.name, nodes[0], nodes[1],
          part.stateBefore, part.stateAfter].join(' '));
      } else if (k === 'E' || k === 'G') {
        const ca = part.ctrlA ? nodeAt(part.ctrlA) : null;
        const cb = part.ctrlB ? nodeAt(part.ctrlB) : null;
        if (!ca || !cb) {
          problems.push(part.name + ' needs both of its sensing probes placed on '
            + 'the circuit. Select it and use the Sense + / Sense - buttons.');
          return;
        }
        lines.push([part.name, nodes[0], nodes[1], ca, cb, part.gain || '0'].join(' '));
      } else if (k === 'H' || k === 'F') {
        if (!part.ctrlElement) {
          problems.push(part.name + ' needs to know which part it senses the '
            + 'current through. Select it and choose one.');
          return;
        }
        lines.push([part.name, nodes[0], nodes[1], part.ctrlElement,
          part.gain || '0'].join(' '));
      } else if (k === 'OPAMP') {
        lines.push([part.name, nodes[0], nodes[1], nodes[2]].join(' '));
      }
    });

    return { text: lines.join('\n') + '\n', problems: problems };
  }

  // ------------------------------------------------------------- rendering

  function el(name, attrs, children) {
    const node = document.createElementNS(SVG_NS, name);
    Object.keys(attrs || {}).forEach(function (k) {
      node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (child) { node.appendChild(child); });
    return node;
  }

  function line(x1, y1, x2, y2, cls) {
    return el('line', { x1: x1, y1: y1, x2: x2, y2: y2, class: cls || 'part' });
  }

  function path(d, cls) { return el('path', { d: d, class: cls || 'part' }); }

  /* Symbol bodies are drawn along +x from 0 to length, centred on the span. */
  function symbolBody(kind, length, part) {
    const shapes = [];
    const bodyWidth = kind === 'OPAMP' ? 0 : (kind === 'V' || kind === 'I'
      || kind === 'E' || kind === 'G' || kind === 'H' || kind === 'F' ? 30 : 34);
    const start = (length - bodyWidth) / 2;
    const end = start + bodyWidth;
    const mid = length / 2;

    if (start > 0.5) shapes.push(line(0, 0, start, 0));
    if (end < length - 0.5) shapes.push(line(end, 0, length, 0));

    if (kind === 'R') {
      let d = 'M ' + start + ' 0';
      const step = bodyWidth / 6;
      for (let i = 0; i < 6; i++) {
        const x = start + step * (i + 0.5);
        d += ' L ' + x + ' ' + (i % 2 === 0 ? -7 : 7);
      }
      d += ' L ' + end + ' 0';
      shapes.push(path(d));
    } else if (kind === 'L') {
      let d = 'M ' + start + ' 0';
      const r = bodyWidth / 8;
      for (let i = 0; i < 4; i++) {
        d += ' A ' + r + ' ' + r + ' 0 0 1 ' + (start + r * 2 * (i + 1)) + ' 0';
      }
      shapes.push(path(d));
    } else if (kind === 'C') {
      shapes.push(line(mid - 4, -11, mid - 4, 11));
      shapes.push(line(mid + 4, -11, mid + 4, 11));
      shapes.push(line(start, 0, mid - 4, 0));
      shapes.push(line(mid + 4, 0, end, 0));
    } else if (kind === 'V' || kind === 'I') {
      shapes.push(el('circle', { cx: mid, cy: 0, r: 13, class: 'part' }));
      if (kind === 'V') {
        shapes.push(line(mid - 8, -4, mid - 8, 4));
        shapes.push(line(mid - 11.5, 0, mid - 4.5, 0));
        shapes.push(line(mid + 4.5, 0, mid + 11.5, 0));
      } else {
        // Arrow points from terminal a to terminal b: the direction of flow.
        shapes.push(line(mid - 8, 0, mid + 7, 0));
        shapes.push(path('M ' + (mid + 8) + ' 0 L ' + (mid + 2) + ' -4 L '
          + (mid + 2) + ' 4 Z', 'part fill'));
      }
    } else if (kind === 'E' || kind === 'H' || kind === 'G' || kind === 'F') {
      shapes.push(path('M ' + start + ' 0 L ' + mid + ' -13 L ' + end + ' 0 L '
        + mid + ' 13 Z'));
      if (kind === 'E' || kind === 'H') {
        shapes.push(line(mid - 7, -3, mid - 7, 3));
        shapes.push(line(mid - 10.5, 0, mid - 3.5, 0));
        shapes.push(line(mid + 3.5, 0, mid + 10.5, 0));
      } else {
        shapes.push(line(mid - 7, 0, mid + 6, 0));
        shapes.push(path('M ' + (mid + 7) + ' 0 L ' + (mid + 1) + ' -3.5 L '
          + (mid + 1) + ' 3.5 Z', 'part fill'));
      }
    } else if (kind === 'SW') {
      shapes.push(el('circle', { cx: start, cy: 0, r: 2.2, class: 'part fill' }));
      shapes.push(el('circle', { cx: end, cy: 0, r: 2.2, class: 'part fill' }));
      const closed = part && part.stateAfter === 'closed';
      shapes.push(line(start, 0, end, closed ? 0 : -9));
    }
    return shapes;
  }

  function drawTwoTerminal(part) {
    const a = part.a, b = part.b;
    const dx = px(b.x - a.x), dy = px(b.y - a.y);
    const length = Math.sqrt(dx * dx + dy * dy);
    const angle = Math.atan2(dy, dx) * 180 / Math.PI;

    const group = el('g', {
      class: 'node' + (state.selected === part.id ? ' selected' : ''),
      'data-id': part.id
    });
    const body = el('g', {
      transform: 'translate(' + px(a.x) + ',' + px(a.y) + ') rotate(' + angle + ')'
    });
    symbolBody(part.kind, length, part).forEach(function (shape) {
      body.appendChild(shape);
    });
    body.appendChild(line(0, 0, length, 0, 'part hit'));
    group.appendChild(body);
    return group;
  }

  function drawOpamp(part) {
    const group = el('g', {
      class: 'node' + (state.selected === part.id ? ' selected' : ''),
      'data-id': part.id
    });
    const x = px(part.a.x), y = px(part.a.y);
    const tipX = px(part.c.x), tipY = px(part.c.y);
    const leftX = x + GRID;
    const top = y - GRID, bottom = y + 3 * GRID;

    group.appendChild(path('M ' + leftX + ' ' + top + ' L ' + leftX + ' ' + bottom
      + ' L ' + tipX + ' ' + tipY + ' Z'));
    group.appendChild(line(x, y, leftX, y));
    group.appendChild(line(px(part.b.x), px(part.b.y), leftX, px(part.b.y)));
    group.appendChild(el('text', {
      x: leftX + 6, y: y + 4, class: 'part-label'
    }));
    group.lastChild.textContent = '+';
    group.appendChild(el('text', {
      x: leftX + 6, y: px(part.b.y) + 4, class: 'part-label'
    }));
    group.lastChild.textContent = '−';
    group.appendChild(el('rect', {
      x: leftX, y: top, width: tipX - leftX, height: bottom - top,
      fill: 'transparent', class: 'hit', style: 'cursor:move'
    }));
    return group;
  }

  function drawGround(part) {
    const group = el('g', {
      class: 'node' + (state.selected === part.id ? ' selected' : ''),
      'data-id': part.id
    });
    const x = px(part.a.x), y = px(part.a.y);
    group.appendChild(line(x, y, x, y + 9));
    group.appendChild(line(x - 10, y + 9, x + 10, y + 9));
    group.appendChild(line(x - 6, y + 13, x + 6, y + 13));
    group.appendChild(line(x - 2.5, y + 17, x + 2.5, y + 17));
    group.appendChild(el('rect', {
      x: x - 11, y: y - 4, width: 22, height: 24,
      fill: 'transparent', class: 'hit', style: 'cursor:move'
    }));
    return group;
  }

  function labelFor(part) {
    const bits = [part.name];
    const k = part.kind;
    if (k === 'R') bits.push(part.value + 'Ω');
    else if (k === 'L') bits.push(part.value + 'H');
    else if (k === 'C') bits.push(part.value + 'F');
    else if (k === 'V' || k === 'I') {
      const unit = k === 'V' ? 'V' : 'A';
      bits.push(String(part.before) === String(part.after)
        ? part.after + unit
        : part.before + unit + '→' + part.after + unit);
    } else if (k === 'SW') {
      bits.push(part.stateBefore + '→' + part.stateAfter);
    } else if (k === 'E' || k === 'G' || k === 'H' || k === 'F') {
      bits.push('×' + part.gain);
    }
    return bits;
  }

  function drawLabels(part, into) {
    if (part.kind === 'GND') return;
    let cx, cy, vertical = false;
    if (part.kind === 'OPAMP') {
      cx = px(part.a.x) + GRID * 2;
      cy = px(part.a.y) - GRID;
    } else {
      cx = (px(part.a.x) + px(part.b.x)) / 2;
      cy = (px(part.a.y) + px(part.b.y)) / 2;
      vertical = part.a.x === part.b.x;
    }
    const bits = labelFor(part);
    bits.forEach(function (text, index) {
      const node = el('text', {
        x: vertical ? cx + 15 : cx,
        y: vertical ? cy - 2 + index * 12 : cy - 18 + index * 12,
        'text-anchor': vertical ? 'start' : 'middle',
        class: 'part-label' + (state.selected === part.id ? ' selected' : '')
      });
      node.textContent = text;
      into.appendChild(node);
    });
  }

  /* Frame the drawing instead of a fixed sheet, so the schematic fills the
     space it has and the labels stay readable however much is on the grid. */
  const MIN_SPAN_X = 20;
  const MIN_SPAN_Y = 12;
  const MARGIN = 3;

  function contentFrame() {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    let any = false;
    function consider(p) {
      any = true;
      minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
      minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
    }
    state.parts.forEach(function (part) { allPointsOf(part).forEach(consider); });
    state.wires.forEach(function (wire) { consider(wire.a); consider(wire.b); });
    if (drag && drag.kind === 'place' && drag.to) { consider(drag.from); consider(drag.to); }

    if (!any) {
      minX = COLS / 2 - MIN_SPAN_X / 2; maxX = minX + MIN_SPAN_X;
      minY = ROWS / 2 - MIN_SPAN_Y / 2; maxY = minY + MIN_SPAN_Y;
    }

    let x0 = minX - MARGIN, x1 = maxX + MARGIN;
    let y0 = minY - MARGIN, y1 = maxY + MARGIN;

    // Grow around the middle rather than blowing a single part up to fill the pane.
    if (x1 - x0 < MIN_SPAN_X) {
      const mid = (x0 + x1) / 2;
      x0 = mid - MIN_SPAN_X / 2; x1 = mid + MIN_SPAN_X / 2;
    }
    if (y1 - y0 < MIN_SPAN_Y) {
      const mid = (y0 + y1) / 2;
      y0 = mid - MIN_SPAN_Y / 2; y1 = mid + MIN_SPAN_Y / 2;
    }

    // Match the pane so the drawing fills it instead of sitting in a letterbox,
    // and the spare room becomes grid to draw on.
    const svg = document.getElementById('canvas');
    const rect = svg ? svg.getBoundingClientRect() : null;
    if (rect && rect.width >= 80 && rect.height >= 80) {
      // A pane that is briefly collapsed reports a wild aspect; clamping keeps
      // one bad measurement from stretching the sheet to nothing.
      const target = Math.min(3.5, Math.max(0.4, rect.width / rect.height));
      const width = x1 - x0, height = y1 - y0;
      if (width / height < target) {
        const wanted = height * target;
        const mid = (x0 + x1) / 2;
        x0 = mid - wanted / 2; x1 = mid + wanted / 2;
      } else {
        const wanted = width / target;
        const mid = (y0 + y1) / 2;
        y0 = mid - wanted / 2; y1 = mid + wanted / 2;
      }
    }
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  function render() {
    computeNodes();
    const svg = document.getElementById('canvas');
    const frame = contentFrame();
    svg.setAttribute('viewBox', [px(frame.x), px(frame.y), px(frame.w), px(frame.h)].join(' '));
    svg.setAttribute('data-tool', state.tool);
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    const grid = el('g', {});
    const gx0 = Math.floor(frame.x), gx1 = Math.ceil(frame.x + frame.w);
    const gy0 = Math.floor(frame.y), gy1 = Math.ceil(frame.y + frame.h);
    // Thin the dots out on a very large sheet rather than drawing thousands.
    const stride = (gx1 - gx0) * (gy1 - gy0) > 3600 ? 5 : 1;
    for (let gx = gx0; gx <= gx1; gx++) {
      for (let gy = gy0; gy <= gy1; gy++) {
        const major = gx % 5 === 0 && gy % 5 === 0;
        if (stride > 1 && !major) continue;
        grid.appendChild(el('circle', {
          cx: px(gx), cy: px(gy), r: major ? 1.3 : 0.8,
          class: 'grid-dot' + (major ? ' major' : '')
        }));
      }
    }
    svg.appendChild(grid);

    const wireLayer = el('g', {});
    state.wires.forEach(function (wire) {
      const group = el('g', {
        class: 'node' + (state.selected === wire.id ? ' selected' : ''),
        'data-id': wire.id
      });
      group.appendChild(line(px(wire.a.x), px(wire.a.y), px(wire.b.x), px(wire.b.y), 'wire'));
      group.appendChild(line(px(wire.a.x), px(wire.a.y), px(wire.b.x), px(wire.b.y), 'wire hit'));
      wireLayer.appendChild(group);
    });
    svg.appendChild(wireLayer);

    const partLayer = el('g', {});
    const ctrlLayer = el('g', {});
    state.parts.forEach(function (part) {
      if (part.kind === 'GND') partLayer.appendChild(drawGround(part));
      else if (part.kind === 'OPAMP') partLayer.appendChild(drawOpamp(part));
      else partLayer.appendChild(drawTwoTerminal(part));

      // Dashed leads show what a controlled source is sensing.
      if (part.kind === 'E' || part.kind === 'G') {
        const mx = (px(part.a.x) + px(part.b.x)) / 2;
        const my = (px(part.a.y) + px(part.b.y)) / 2;
        [part.ctrlA, part.ctrlB].forEach(function (probe, index) {
          if (!probe) return;
          ctrlLayer.appendChild(line(mx, my, px(probe.x), px(probe.y), 'ctrl-link'));
          ctrlLayer.appendChild(el('circle', {
            cx: px(probe.x), cy: px(probe.y), r: 3.4, class: 'ctrl-link'
          }));
          const tag = el('text', {
            x: px(probe.x) + 6, y: px(probe.y) - 5, class: 'node-label'
          });
          tag.textContent = index === 0 ? '+' : '−';
          ctrlLayer.appendChild(tag);
        });
      }
    });
    svg.appendChild(ctrlLayer);
    svg.appendChild(partLayer);

    // A junction dot wherever three or more wire ends or terminals coincide.
    const density = {};
    state.parts.forEach(function (part) {
      terminalsOf(part).forEach(function (p) { density[key(p)] = (density[key(p)] || 0) + 1; });
    });
    state.wires.forEach(function (wire) {
      wirePoints(wire).forEach(function (p, index, list) {
        const ends = index === 0 || index === list.length - 1;
        density[key(p)] = (density[key(p)] || 0) + (ends ? 1 : 0.5);
      });
    });
    const junctions = el('g', {});
    Object.keys(density).forEach(function (k) {
      if (density[k] < 2.5) return;
      const parts = k.split(',');
      junctions.appendChild(el('circle', {
        cx: px(+parts[0]), cy: px(+parts[1]), r: 3, class: 'junction'
      }));
    });
    svg.appendChild(junctions);

    const labels = el('g', {});
    state.parts.forEach(function (part) { drawLabels(part, labels); });

    nodeMap.names.forEach(function (name) {
      if (name === '0') return;
      const at = nodeMap.labelAt[name];
      if (!at) return;
      const tag = el('text', { x: px(at.x) + 7, y: px(at.y) - 7, class: 'node-label' });
      tag.textContent = name;
      labels.appendChild(tag);

      if (state.showVoltages && state.result) {
        const value = state.result.node(state.overlayPhase, name);
        if (value) {
          const unit = state.overlayPhase === 'd/dt' ? ' V/s' : ' V';
          const reading = el('text', {
            x: px(at.x) + 7, y: px(at.y) + 5, class: 'node-label node-value'
          });
          reading.textContent = S.fmt(value) + unit;
          labels.appendChild(reading);
        }
      }
    });
    svg.appendChild(labels);

    const overlay = el('g', { id: 'overlay' });
    svg.appendChild(overlay);
    if (drag && drag.preview) drawPreview(overlay);
  }

  function drawPreview(overlay) {
    const a = drag.from, b = drag.to;
    if (!b) return;
    overlay.appendChild(line(px(a.x), px(a.y), px(b.x), px(b.y), 'preview'));
  }

  // ------------------------------------------------------------ interaction

  function pointerGrid(event) {
    const svg = document.getElementById('canvas');
    const matrix = svg.getScreenCTM();
    if (!matrix) return { x: 0, y: 0 };
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const local = point.matrixTransform(matrix.inverse());
    return clampPoint({
      x: Math.round(local.x / GRID),
      y: Math.round(local.y / GRID)
    });
  }

  function axisSnap(from, to) {
    if (Math.abs(to.x - from.x) >= Math.abs(to.y - from.y)) {
      return { x: to.x, y: from.y };
    }
    return { x: from.x, y: to.y };
  }

  function nextName(prefix) {
    let index = 1;
    const taken = {};
    state.parts.forEach(function (p) { taken[p.name] = true; });
    while (taken[prefix + index]) index++;
    return prefix + index;
  }

  function defaultsFor(kind) {
    const base = { R: '1k', L: '1', C: '1u' };
    if (kind === 'R' || kind === 'L' || kind === 'C') return { value: base[kind], ic: '' };
    if (kind === 'V') return { before: '0', after: '10' };
    if (kind === 'I') return { before: '0', after: '1' };
    if (kind === 'SW') return { stateBefore: 'open', stateAfter: 'closed' };
    if (kind === 'E' || kind === 'H') return { gain: '2', ctrlA: null, ctrlB: null };
    if (kind === 'G' || kind === 'F') return { gain: '2', ctrlA: null, ctrlB: null };
    return {};
  }

  function addPart(kind, from, to) {
    const prefix = CATALOG.filter(function (c) { return c.kind === kind; })[0].prefix;
    const part = Object.assign({
      id: 'p' + (state.nextId++),
      kind: kind,
      name: kind === 'GND' ? 'GND' : nextName(prefix),
      a: from,
      b: to
    }, defaultsFor(kind));

    if (kind === 'OPAMP') {
      part.a = from;
      part.b = { x: from.x, y: from.y + 2 };
      part.c = { x: from.x + 4, y: from.y + 1 };
    }
    state.parts.push(part);
    state.selected = part.id;
    invalidate();
    return part;
  }

  function invalidate() {
    state.result = null;
    state.error = null;
    state.showVoltages = false;
    render();
    renderInspector();
    renderResults();
    syncStageBar();
  }

  function capture(svg, event) {
    // Pointer capture is a convenience, not a requirement; never let it throw.
    try { svg.setPointerCapture(event.pointerId); } catch (error) { /* ignore */ }
  }

  function onPointerDown(event) {
    const svg = document.getElementById('canvas');
    const point = pointerGrid(event);

    if (state.pick) {
      const part = findPart(state.pick.partId);
      if (part) { part[state.pick.which] = point; }
      state.pick = null;
      invalidate();
      return;
    }

    const hitId = event.target.closest('[data-id]');
    if (state.tool === 'select') {
      if (hitId) {
        state.selected = hitId.getAttribute('data-id');
        drag = {
          kind: 'move', id: state.selected, origin: point, moved: false,
          snapshot: snapshotOf(state.selected)
        };
        capture(svg, event);
        render();
        renderInspector();
      } else {
        state.selected = null;
        render();
        renderInspector();
      }
      return;
    }

    if (CLICK_PLACED[state.tool]) {
      addPart(state.tool, point, point);
      state.tool = 'select';
      syncTools();
      return;
    }

    drag = { kind: 'place', from: point, to: point, preview: true };
    capture(svg, event);
  }

  function snapshotOf(id) {
    const part = findPart(id);
    if (part) {
      return JSON.parse(JSON.stringify({
        a: part.a, b: part.b, c: part.c, ctrlA: part.ctrlA, ctrlB: part.ctrlB
      }));
    }
    const wire = findWire(id);
    return wire ? JSON.parse(JSON.stringify({ a: wire.a, b: wire.b })) : null;
  }

  function onPointerMove(event) {
    if (!drag) return;
    const point = pointerGrid(event);

    if (drag.kind === 'place') {
      drag.to = axisSnap(drag.from, point);
      render();
      return;
    }

    if (drag.kind === 'move') {
      const dx = point.x - drag.origin.x;
      const dy = point.y - drag.origin.y;
      if (dx === 0 && dy === 0) return;
      drag.moved = true;
      const target = findPart(drag.id) || findWire(drag.id);
      if (!target || !drag.snapshot) return;
      ['a', 'b', 'c', 'ctrlA', 'ctrlB'].forEach(function (field) {
        if (!drag.snapshot[field]) return;
        target[field] = clampPoint({
          x: drag.snapshot[field].x + dx,
          y: drag.snapshot[field].y + dy
        });
      });
      render();
    }
  }

  function onPointerUp() {
    if (!drag) return;
    const finished = drag;
    drag = null;

    if (finished.kind === 'place') {
      const from = finished.from;
      const to = finished.to;
      const span = Math.abs(to.x - from.x) + Math.abs(to.y - from.y);
      if (span >= (state.tool === 'wire' ? 1 : 2)) {
        if (state.tool === 'wire') {
          state.wires.push({ id: 'w' + (state.nextId++), a: from, b: to });
          state.selected = null;
        } else {
          addPart(state.tool, from, to);
          state.tool = 'select';
          syncTools();
        }
      }
      invalidate();
      return;
    }

    if (finished.moved) invalidate();
  }

  function findPart(id) {
    return state.parts.filter(function (p) { return p.id === id; })[0] || null;
  }
  function findWire(id) {
    return state.wires.filter(function (w) { return w.id === id; })[0] || null;
  }

  function deleteSelected() {
    if (!state.selected) return;
    const id = state.selected;
    const part = findPart(id);
    if (part) {
      // Anything sensing this part loses its reference.
      state.parts.forEach(function (other) {
        if (other.ctrlElement === part.name) other.ctrlElement = null;
      });
    }
    state.parts = state.parts.filter(function (p) { return p.id !== id; });
    state.wires = state.wires.filter(function (w) { return w.id !== id; });
    state.selected = null;
    invalidate();
  }

  // -------------------------------------------------------------- inspector

  function fieldRow(labelText, inputEl, note) {
    const wrap = document.createElement('div');
    wrap.className = 'field';
    const label = document.createElement('label');
    label.textContent = labelText;
    const id = 'f' + Math.random().toString(36).slice(2, 8);
    label.setAttribute('for', id);
    inputEl.id = id;
    wrap.appendChild(label);
    wrap.appendChild(inputEl);
    if (note) {
      const hint = document.createElement('div');
      hint.className = 'note';
      hint.textContent = note;
      wrap.appendChild(hint);
    }
    return wrap;
  }

  function textInput(value, onChange, placeholder) {
    const input = document.createElement('input');
    input.type = 'text';
    input.value = value === undefined || value === null ? '' : String(value);
    if (placeholder) input.placeholder = placeholder;
    input.addEventListener('change', function () { onChange(input.value.trim()); });
    return input;
  }

  function selectInput(options, value, onChange) {
    const select = document.createElement('select');
    options.forEach(function (option) {
      const node = document.createElement('option');
      node.value = option.value;
      node.textContent = option.label;
      if (option.value === value) node.selected = true;
      select.appendChild(node);
    });
    select.addEventListener('change', function () { onChange(select.value); });
    return select;
  }

  function button(text, onClick, variant) {
    const node = document.createElement('button');
    node.className = 'btn';
    node.type = 'button';
    if (variant) node.setAttribute('data-variant', variant);
    node.textContent = text;
    node.addEventListener('click', onClick);
    return node;
  }

  function renderInspector() {
    const host = document.getElementById('inspector-body');
    host.innerHTML = '';

    const wire = findWire(state.selected);
    if (wire) {
      const head = document.createElement('div');
      head.className = 'inspector-head';
      head.innerHTML = '<strong>Wire</strong><span>joins two nodes</span>';
      host.appendChild(head);
      host.appendChild(button('Delete wire', deleteSelected, 'danger'));
      return;
    }

    const part = findPart(state.selected);
    if (!part) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.innerHTML =
        '<p>Pick a part on the left, then drag on the grid to place it. '
        + 'Drag with <b>Wire</b> to join things up.</p>'
        + '<p>Click a part to edit it here. <kbd>Delete</kbd> removes it, '
        + '<kbd>Esc</kbd> goes back to the pointer.</p>'
        + '<p>Terminals that touch are connected. The small blue numbers on the '
        + 'grid are the node numbers the solver worked out — check them '
        + 'against your own drawing before trusting an answer.</p>';
      host.appendChild(empty);
      return;
    }

    const head = document.createElement('div');
    head.className = 'inspector-head';
    const strong = document.createElement('strong');
    strong.textContent = part.name;
    const span = document.createElement('span');
    span.textContent = S.PRETTY_KIND[part.kind] || part.kind;
    head.appendChild(strong);
    head.appendChild(span);
    host.appendChild(head);

    if (part.kind !== 'GND') {
      host.appendChild(fieldRow('Name', textInput(part.name, function (v) {
        const old = part.name;
        part.name = v || old;
        state.parts.forEach(function (other) {
          if (other.ctrlElement === old) other.ctrlElement = part.name;
        });
        invalidate();
      })));
    }

    const k = part.kind;
    if (k === 'R' || k === 'L' || k === 'C') {
      const unit = k === 'R' ? 'ohms' : (k === 'L' ? 'henries' : 'farads');
      host.appendChild(fieldRow('Value (' + unit + ')',
        textInput(part.value, function (v) { part.value = v; invalidate(); }),
        'Fractions and suffixes both work: 1/5, 0.2, 4k7 as 4.7k, 10u, 100n.'));
      if (k === 'L' || k === 'C') {
        host.appendChild(fieldRow(
          k === 'L' ? 'Starting current (A)' : 'Starting voltage (V)',
          textInput(part.ic, function (v) { part.ic = v; invalidate(); }, 'work it out'),
          'Leave blank and the solver finds it from the t < 0 circuit. Fill it '
          + 'in only when the question states it.'));
      }
    } else if (k === 'V' || k === 'I') {
      const unit = k === 'V' ? 'V' : 'A';
      const row = document.createElement('div');
      row.className = 'field-row';
      row.appendChild(fieldRow('Before t=0 (' + unit + ')',
        textInput(part.before, function (v) { part.before = v; invalidate(); })));
      row.appendChild(fieldRow('After t=0 (' + unit + ')',
        textInput(part.after, function (v) { part.after = v; invalidate(); })));
      host.appendChild(row);
      const chips = document.createElement('div');
      chips.className = 'chip-row';
      chips.appendChild(button('Make it a step', function () {
        part.before = '0';
        if (part.after === '0') part.after = k === 'V' ? '10' : '1';
        invalidate();
      }));
      chips.appendChild(button('Make it constant', function () {
        part.before = part.after;
        invalidate();
      }));
      host.appendChild(chips);
      const note = document.createElement('div');
      note.className = 'note';
      note.style.marginTop = '-6px';
      note.textContent = k === 'V'
        ? 'The + terminal is the one you drew first. Flip it below if the sign is wrong.'
        : 'The arrow shows which way current flows out of the source.';
      host.appendChild(note);
    } else if (k === 'SW') {
      const row = document.createElement('div');
      row.className = 'field-row';
      const options = [{ value: 'open', label: 'open' }, { value: 'closed', label: 'closed' }];
      row.appendChild(fieldRow('Before t=0',
        selectInput(options, part.stateBefore, function (v) {
          part.stateBefore = v; invalidate();
        })));
      row.appendChild(fieldRow('After t=0',
        selectInput(options, part.stateAfter, function (v) {
          part.stateAfter = v; invalidate();
        })));
      host.appendChild(row);
    } else if (k === 'E' || k === 'G') {
      host.appendChild(fieldRow(k === 'E' ? 'Gain (V per V)' : 'Gain (A per V)',
        textInput(part.gain, function (v) { part.gain = v; invalidate(); })));
      const chips = document.createElement('div');
      chips.className = 'chip-row';
      chips.appendChild(button(part.ctrlA ? 'Move sense +' : 'Place sense +', function () {
        state.pick = { partId: part.id, which: 'ctrlA' };
        syncStageBar();
      }));
      chips.appendChild(button(part.ctrlB ? 'Move sense −' : 'Place sense −', function () {
        state.pick = { partId: part.id, which: 'ctrlB' };
        syncStageBar();
      }));
      host.appendChild(chips);
      const note = document.createElement('div');
      note.className = 'note';
      note.textContent = 'This source watches the voltage between the two probe '
        + 'points and multiplies it by the gain.';
      host.appendChild(note);
    } else if (k === 'H' || k === 'F') {
      host.appendChild(fieldRow(k === 'H' ? 'Gain (V per A)' : 'Gain (A per A)',
        textInput(part.gain, function (v) { part.gain = v; invalidate(); })));
      const candidates = state.parts
        .filter(function (p) { return p.kind !== 'GND' && p.id !== part.id; })
        .map(function (p) { return { value: p.name, label: p.name }; });
      candidates.unshift({ value: '', label: 'choose a part…' });
      host.appendChild(fieldRow('Senses the current through',
        selectInput(candidates, part.ctrlElement || '', function (v) {
          part.ctrlElement = v || null;
          invalidate();
        }),
        'Current is measured in the direction that part was drawn.'));
    } else if (k === 'OPAMP') {
      const note = document.createElement('div');
      note.className = 'note';
      note.style.marginBottom = '12px';
      note.textContent = 'Ideal op-amp: the two inputs are forced to the same '
        + 'voltage and draw no current. It needs a feedback path from the output '
        + 'back to the − input.';
      host.appendChild(note);
    }

    const footer = document.createElement('div');
    footer.className = 'chip-row';
    if (k !== 'GND' && k !== 'OPAMP') {
      footer.appendChild(button('Flip ±', function () {
        const swap = part.a; part.a = part.b; part.b = swap;
        invalidate();
      }));
    }
    if (k === 'OPAMP') {
      footer.appendChild(button('Swap inputs', function () {
        const swap = part.a; part.a = part.b; part.b = swap;
        invalidate();
      }));
    }
    footer.appendChild(button('Delete', deleteSelected, 'danger'));
    host.appendChild(footer);

    const nodes = terminalsOf(part).map(nodeAt);
    const wiring = document.createElement('div');
    wiring.className = 'note';
    const labels = k === 'OPAMP' ? ['in+', 'in−', 'out']
      : (k === 'I' || k === 'G' || k === 'F' ? ['from', 'to'] : ['+', '−']);
    wiring.textContent = 'Wired to ' + labels.map(function (name, index) {
      return name + ': node ' + (nodes[index] === null ? '—' : nodes[index]);
    }).join(', ') + '.';
    host.appendChild(wiring);
  }

  // ---------------------------------------------------------------- solving

  function solve() {
    const built = buildNetlist();
    state.result = null;
    state.error = null;

    if (built.problems.length) {
      state.error = { title: 'The drawing is not finished yet', items: built.problems };
      renderResults();
      syncStageBar();
      return;
    }

    try {
      const circuit = S.parseNetlist(built.text, 'Your circuit');
      state.result = S.analyse(circuit);
    } catch (error) {
      state.error = {
        title: error instanceof S.AnalysisError
          ? 'These equations have no single answer'
          : 'That circuit cannot be read',
        items: [error.message]
      };
    }
    renderResults();
    syncStageBar();
    render();
    const results = document.getElementById('results');
    if (results.firstChild) results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  const PHASE_TITLE = {
    't<0': 'Before the switch',
    '0+': 'The instant after',
    'd/dt': 'How fast it is changing',
    'inf': 'Long afterwards'
  };
  const PHASE_SUB = {
    't<0': 't < 0, steady state',
    '0+': 't = 0+',
    'd/dt': 'd/dt at t = 0+',
    'inf': 't → ∞'
  };
  const PHASE_COLUMN = {
    't<0': 't < 0', '0+': 't = 0+', 'd/dt': 'd/dt at 0+', 'inf': 't → ∞'
  };

  function h(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderResults() {
    const host = document.getElementById('results');
    host.innerHTML = '';

    if (state.error) {
      const banner = h('div', 'banner');
      const body = h('div');
      body.appendChild(h('strong', null, state.error.title));
      state.error.items.forEach(function (item) {
        body.appendChild(h('div', null, item));
      });
      banner.appendChild(body);
      host.appendChild(banner);
      return;
    }
    if (!state.result) return;

    const result = state.result;
    const circuit = result.circuit;

    result.notes.forEach(function (note) {
      const banner = h('div', 'banner info');
      banner.appendChild(h('div', null, note));
      host.appendChild(banner);
    });

    // Headline answers first: this is what the question actually asks for.
    const targets = circuit.ofKind('L', 'C', 'R');
    if (targets.length) {
      const card = h('div', 'answers');
      card.appendChild(h('h2', null, 'Answers'));
      card.appendChild(h('p', null,
        'Exact values. Every one of these came out of the equations below, not '
        + 'from rounding.'));
      const groups = h('div', 'answer-groups');
      [['0+', 'Just after switching'], ['d/dt', 'Rate of change at 0+'],
        ['inf', 'Final values']].forEach(function (pair) {
        if (!result.phases[pair[0]]) return;
        const group = h('div', 'answer-group');
        group.appendChild(h('h3', null, pair[1]));
        const list = document.createElement('dl');
        targets.forEach(function (element) {
          const quantity = element.kind === 'L' ? 'i' : 'v';
          const value = result.value(pair[0], element.name, quantity);
          if (value === null) return;
          const symbol = quantity + '_' + element.name;
          const dt = h('dt', null, pair[0] === 'd/dt'
            ? 'd' + symbol + '/dt'
            : symbol + (pair[0] === '0+' ? '(0⁺)' : '(∞)'));
          const unitText = (quantity === 'v' ? 'V' : 'A') + (pair[0] === 'd/dt' ? '/s' : '');
          const dd = h('dd', null, S.fmt(value) + ' ' + unitText);
          list.appendChild(dt);
          list.appendChild(dd);
        });
        group.appendChild(list);
        groups.appendChild(group);
      });
      card.appendChild(groups);
      host.appendChild(card);
    }

    const head = h('div', 'section-head');
    head.appendChild(h('h2', null, 'How it was worked out'));
    head.appendChild(h('p', null,
      'Open any step to see the circuit it solved and the equations it wrote.'));
    host.appendChild(head);

    let stepNumber = 0;
    S.PHASE_ORDER.forEach(function (phaseKey) {
      const phase = result.phases[phaseKey];
      if (!phase) return;
      stepNumber++;

      const details = document.createElement('details');
      details.className = 'step';
      if (phaseKey === '0+') details.open = true;
      const summary = document.createElement('summary');
      summary.appendChild(h('span', 'step-no', String(stepNumber)));
      summary.appendChild(h('span', null, PHASE_TITLE[phaseKey]));
      summary.appendChild(h('span', 'step-sub', PHASE_SUB[phaseKey]));
      details.appendChild(summary);

      const body = h('div', 'step-body');

      if (phase.description.length) {
        body.appendChild(h('h4', null, 'What the circuit becomes'));
        const list = document.createElement('ul');
        phase.description.forEach(function (item) {
          list.appendChild(h('li', null, item));
        });
        body.appendChild(list);
      }

      body.appendChild(h('h4', null, 'The equations it solved'));
      const wrap = h('div', 'equations');
      const table = document.createElement('table');
      phase.system.equationLines(phase.solution.rhs).forEach(function (row) {
        const tr = document.createElement('tr');
        tr.appendChild(h('td', 'eq-label', row.label));
        tr.appendChild(h('td', null, row.left + '  ='));
        tr.appendChild(h('td', 'eq-rhs', row.right));
        tr.appendChild(h('td', 'eq-slack'));
        table.appendChild(tr);
      });
      wrap.appendChild(table);
      body.appendChild(wrap);

      body.appendChild(h('h4', null, 'Which gives'));
      const solved = h('div', 'solved-list');
      circuit.nodes().forEach(function (node) {
        if (S.isGround(node)) return;
        const span = h('span', null, 'V(' + node + ') = ');
        const bold = h('b', null, S.fmt(phase.solution.nodeVoltage(node))
          + (phaseKey === 'd/dt' ? ' V/s' : ' V'));
        span.appendChild(bold);
        solved.appendChild(span);
      });
      body.appendChild(solved);

      const carriedOver = circuit.ofKind('L', 'C').filter(function (element) {
        return result.icSources[element.name] === 'solved';
      });
      if (phaseKey === 't<0' && carriedOver.length) {
        body.appendChild(h('h4', null, 'What carries across t = 0'));
        const carried = h('div', 'solved-list');
        carriedOver.forEach(function (element) {
          const isL = element.kind === 'L';
          const span = h('span', null,
            (isL ? 'i_' : 'v_') + element.name + '(0⁻) = ');
          span.appendChild(h('b', null,
            S.fmt(result.initialConditions[element.name]) + (isL ? ' A' : ' V')));
          carried.appendChild(span);
        });
        body.appendChild(carried);
      }

      if (phaseKey === '0+') {
        const storage = circuit.ofKind('L', 'C');
        if (storage.length) {
          body.appendChild(h('h4', null, 'Why those substitutions are allowed'));
          const list = document.createElement('ul');
          storage.forEach(function (element) {
            const value = result.initialConditions[element.name];
            const origin = result.icSources[element.name] === 'given'
              ? 'you gave this' : 'from the previous step';
            list.appendChild(h('li', null, element.kind === 'L'
              ? 'i_' + element.name + '(0⁺) = i_' + element.name + '(0⁻) = '
                + S.fmt(value) + ' A — ' + origin
                + '; an inductor current cannot change instantly.'
              : 'v_' + element.name + '(0⁺) = v_' + element.name + '(0⁻) = '
                + S.fmt(value) + ' V — ' + origin
                + '; a capacitor voltage cannot change instantly.'));
          });
          body.appendChild(list);
        }
      }

      if (phaseKey === 'd/dt') {
        const storage = circuit.ofKind('L', 'C');
        if (storage.length) {
          body.appendChild(h('h4', null, 'Where the driving values came from'));
          const list = document.createElement('ul');
          const zeroPlus = result.phases['0+'].solution;
          storage.forEach(function (element) {
            const derivative = result.derivativeStorage[element.name];
            list.appendChild(h('li', null, element.kind === 'L'
              ? 'di_' + element.name + '/dt = v_' + element.name + '(0⁺) / L = '
                + S.fmt(zeroPlus.elementVoltage(element)) + ' / '
                + S.fmt(element.value) + ' = ' + S.fmt(derivative) + ' A/s'
              : 'dv_' + element.name + '/dt = i_' + element.name + '(0⁺) / C = '
                + S.fmt(zeroPlus.elementCurrent(element)) + ' / '
                + S.fmt(element.value) + ' = ' + S.fmt(derivative) + ' V/s'));
          });
          body.appendChild(list);
        }
      }

      details.appendChild(body);
      host.appendChild(details);
    });

    const tableHead = h('div', 'section-head');
    tableHead.appendChild(h('h2', null, 'Every part, every stage'));
    tableHead.appendChild(h('p', null,
      'v is measured + to − across the part as you drew it, and i flows from '
      + 'its first terminal to its second. The d/dt column is in V/s and A/s.'));
    host.appendChild(tableHead);

    const columns = S.PHASE_ORDER.filter(function (k) { return !!result.phases[k]; });
    const wrap = h('div', 'table-wrap');
    const table = h('table', 'grid');
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    ['Part', 'Quantity'].concat(columns.map(function (k) { return PHASE_COLUMN[k]; }))
      .forEach(function (title) {
        headRow.appendChild(h('th', null, title));
      });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    circuit.elements.forEach(function (element) {
      ['v', 'i'].forEach(function (quantity) {
        const tr = document.createElement('tr');
        tr.appendChild(h('td', 'name', quantity === 'v' ? element.name : ''));
        tr.appendChild(h('td', null, quantity === 'v' ? 'v  (V)' : 'i  (A)'));
        columns.forEach(function (phaseKey) {
          const value = result.value(phaseKey, element.name, quantity);
          tr.appendChild(h('td', 'val', value === null ? '—' : S.fmt(value)));
        });
        tbody.appendChild(tr);
      });
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    host.appendChild(wrap);
  }

  // ------------------------------------------------------------------ chrome

  function toolIcon(kind) {
    const svg = el('svg', { viewBox: '-2 -9 30 18' });
    if (kind === 'select') {
      svg.appendChild(path('M 4 -7 L 4 6 L 8 2 L 11 8 L 13 7 L 10 1 L 15 1 Z'));
    } else if (kind === 'wire') {
      svg.appendChild(line(0, 4, 10, 4));
      svg.appendChild(line(10, 4, 10, -5));
      svg.appendChild(line(10, -5, 24, -5));
      svg.appendChild(el('circle', { cx: 10, cy: 4, r: 1.8, class: 'solid' }));
    } else if (kind === 'GND') {
      svg.appendChild(line(12, -7, 12, 0));
      svg.appendChild(line(5, 0, 19, 0));
      svg.appendChild(line(8, 4, 16, 4));
      svg.appendChild(line(10.5, 8, 13.5, 8));
    } else if (kind === 'OPAMP') {
      svg.appendChild(path('M 6 -8 L 6 8 L 21 0 Z'));
      svg.appendChild(line(0, -4, 6, -4));
      svg.appendChild(line(0, 4, 6, 4));
      svg.appendChild(line(21, 0, 26, 0));
    } else {
      symbolBody(kind, 26, { stateAfter: 'open' }).forEach(function (shape) {
        svg.appendChild(shape);
      });
    }
    return svg;
  }

  function buildRail() {
    const rail = document.getElementById('rail');
    rail.innerHTML = '';

    function group(title, items) {
      rail.appendChild(h('h2', null, title));
      items.forEach(function (item) {
        const btn = document.createElement('button');
        btn.className = 'tool';
        btn.type = 'button';
        btn.setAttribute('data-tool', item.kind);
        btn.setAttribute('aria-pressed', String(state.tool === item.kind));
        btn.appendChild(toolIcon(item.kind));
        btn.appendChild(h('span', null, item.label));
        btn.addEventListener('click', function () {
          state.tool = item.kind;
          state.pick = null;
          syncTools();
          syncStageBar();
        });
        rail.appendChild(btn);
      });
    }

    group('Tools', [
      { kind: 'select', label: 'Pointer' },
      { kind: 'wire', label: 'Wire' }
    ]);
    group('Basics', CATALOG.slice(0, 7));
    group('Dependent', CATALOG.slice(7));
  }

  function syncTools() {
    Array.prototype.forEach.call(document.querySelectorAll('.tool'), function (btn) {
      btn.setAttribute('aria-pressed', String(btn.getAttribute('data-tool') === state.tool));
    });
    const svg = document.getElementById('canvas');
    if (svg) svg.setAttribute('data-tool', state.tool);
  }

  function syncStageBar() {
    const hint = document.getElementById('stage-hint');
    if (state.pick) {
      hint.textContent = 'Click the point on the circuit this source should sense.';
    } else if (state.tool === 'select') {
      hint.textContent = 'Click to select, drag to move.';
    } else if (state.tool === 'wire') {
      hint.textContent = 'Drag to run a wire. Anything it touches joins that node.';
    } else if (CLICK_PLACED[state.tool]) {
      hint.textContent = 'Click where you want it.';
    } else {
      hint.textContent = 'Drag across two or more squares to place it.';
    }

    const overlayBox = document.getElementById('overlay-controls');
    overlayBox.hidden = !state.result;
    const select = document.getElementById('overlay-phase');
    if (state.result) {
      const available = S.PHASE_ORDER.filter(function (k) { return !!state.result.phases[k]; });
      if (available.indexOf(state.overlayPhase) === -1) state.overlayPhase = available[0];
      select.innerHTML = '';
      available.forEach(function (k) {
        const option = document.createElement('option');
        option.value = k;
        option.textContent = PHASE_COLUMN[k];
        if (k === state.overlayPhase) option.selected = true;
        select.appendChild(option);
      });
    }
  }

  // ------------------------------------------------------------- persistence

  function serialise() {
    return JSON.stringify({
      parts: state.parts, wires: state.wires, nextId: state.nextId
    });
  }

  function load(data) {
    state.parts = data.parts || [];
    state.wires = data.wires || [];
    state.nextId = data.nextId || (state.parts.length + state.wires.length + 1);
    state.selected = null;
    state.tool = 'select';
    syncTools();
    invalidate();
  }

  /* The lecture example, pre-wired: a parallel RLC driven by 4u(t) A and 6 A. */
  function exampleCircuit() {
    return {
      nextId: 40,
      parts: [
        { id: 'p1', kind: 'I', name: 'I1', a: { x: 6, y: 15 }, b: { x: 6, y: 7 },
          before: '0', after: '4' },
        { id: 'p2', kind: 'C', name: 'C1', a: { x: 14, y: 7 }, b: { x: 14, y: 15 },
          value: '1/5', ic: '' },
        { id: 'p3', kind: 'R', name: 'R1', a: { x: 14, y: 7 }, b: { x: 24, y: 7 },
          value: '5' },
        { id: 'p4', kind: 'L', name: 'L1', a: { x: 24, y: 7 }, b: { x: 24, y: 15 },
          value: '2' },
        { id: 'p5', kind: 'I', name: 'I2', a: { x: 32, y: 15 }, b: { x: 32, y: 7 },
          before: '6', after: '6' },
        { id: 'p6', kind: 'GND', name: 'GND', a: { x: 19, y: 15 }, b: { x: 19, y: 15 } }
      ],
      wires: [
        { id: 'w1', a: { x: 6, y: 7 }, b: { x: 14, y: 7 } },
        { id: 'w2', a: { x: 24, y: 7 }, b: { x: 32, y: 7 } },
        { id: 'w3', a: { x: 6, y: 15 }, b: { x: 32, y: 15 } }
      ]
    };
  }

  function openDialog(title, message, value, onAccept) {
    const dialog = document.getElementById('io-dialog');
    document.getElementById('io-title').textContent = title;
    document.getElementById('io-message').textContent = message;
    const area = document.getElementById('io-text');
    area.value = value;
    const accept = document.getElementById('io-accept');
    accept.hidden = !onAccept;
    accept.onclick = function () {
      if (onAccept) onAccept(area.value);
      dialog.close();
    };
    dialog.showModal();
    area.focus();
    if (!onAccept) area.select();
  }

  // ------------------------------------------------------------------- boot

  function init() {
    buildRail();

    const svg = document.getElementById('canvas');
    svg.addEventListener('pointerdown', onPointerDown);
    svg.addEventListener('pointermove', onPointerMove);
    svg.addEventListener('pointerup', onPointerUp);
    svg.addEventListener('pointercancel', onPointerUp);

    document.addEventListener('keydown', function (event) {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName);
      if (event.key === 'Escape') {
        state.pick = null;
        state.tool = 'select';
        syncTools();
        syncStageBar();
        return;
      }
      if (typing) return;
      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        deleteSelected();
      }
      if (event.key === 'w' || event.key === 'W') {
        state.tool = 'wire'; syncTools(); syncStageBar();
      }
      if (event.key === 'v' || event.key === 'V') {
        state.tool = 'select'; syncTools(); syncStageBar();
      }
    });

    document.getElementById('btn-solve').addEventListener('click', solve);
    document.getElementById('btn-example').addEventListener('click', function () {
      load(exampleCircuit());
    });
    document.getElementById('btn-clear').addEventListener('click', function () {
      if (state.parts.length && !window.confirm('Clear the whole schematic?')) return;
      load({ parts: [], wires: [], nextId: 1 });
    });
    document.getElementById('btn-export').addEventListener('click', function () {
      const built = buildNetlist();
      const body = built.problems.length
        ? built.text + '\n# unfinished:\n# ' + built.problems.join('\n# ')
        : built.text;
      openDialog('Netlist',
        'This is your drawing as text. The Python version of this solver reads '
        + 'exactly this format, so you can check any answer in a second place.',
        body, null);
    });
    document.getElementById('btn-save').addEventListener('click', function () {
      openDialog('Save or restore',
        'Copy this out to keep the drawing, or paste an old one back in and press '
        + 'Load.', serialise(), function (text) {
          try {
            load(JSON.parse(text));
          } catch (error) {
            window.alert('That does not look like a saved schematic.');
          }
        });
    });
    document.getElementById('io-close').addEventListener('click', function () {
      document.getElementById('io-dialog').close();
    });

    const toggle = document.getElementById('show-voltages');
    toggle.addEventListener('change', function () {
      state.showVoltages = toggle.checked;
      render();
    });
    document.getElementById('overlay-phase').addEventListener('change', function (event) {
      state.overlayPhase = event.target.value;
      render();
    });

    load(exampleCircuit());
    syncStageBar();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());
