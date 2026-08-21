/* Emit every solved quantity for the whole test corpus through the JS solver.
 * Compare the output against results_python.json to catch porting bugs. */

const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const solver = require(path.join(HERE, '..', 'web', 'extras.js')).CircuitSolver;

const PHASES = ['t<0', '0+', 'd/dt', 'd2/dt2', 'inf'];

function exact(q) { return q.n + '/' + q.d; }

function dumpOne(netlist) {
  let circuit;
  let result;
  try {
    circuit = solver.parseNetlist(netlist);
    result = solver.analyse(circuit);
  } catch (error) {
    if (error instanceof solver.CircuitError) return { error: 'CircuitError' };
    if (error instanceof solver.AnalysisError) return { error: 'AnalysisError' };
    return { error: 'Unexpected: ' + error.name + ': ' + error.message };
  }

  const out = { phases: {}, notes: result.notes.length, error: null, ics: {} };
  Object.keys(result.initialConditions).forEach(function (name) {
    out.ics[name] = exact(result.initialConditions[name]);
  });

  PHASES.forEach(function (key) {
    const phase = result.phases[key];
    if (!phase) { out.phases[key] = null; return; }
    const entry = { nodes: {}, elements: {} };
    circuit.nodes().forEach(function (node) {
      entry.nodes[node] = exact(phase.solution.nodeVoltage(node));
    });
    circuit.elements.forEach(function (element) {
      entry.elements[element.name] = {
        v: exact(phase.solution.elementVoltage(element)),
        i: exact(phase.solution.elementCurrent(element))
      };
    });
    out.phases[key] = entry;
  });

  const d = result.dynamics;
  if (d && d.order) {
    out.dynamics = {
      order: d.order,
      damping: d.damping || '',
      alpha: d.alpha ? exact(d.alpha) : '',
      omega0sq: d.omega0Squared ? exact(d.omega0Squared) : '',
      disc: d.discriminant ? exact(d.discriminant) : '',
      stable: !!d.stable,
      poly: d.polynomial.map(exact),
      tau: d.tau ? String(d.tau) : '',
      roots: d.roots.map(function (r) { return String(r); })
    };
    out.responses = {};
    Object.keys(result.responses).forEach(function (name) {
      const forms = {};
      Object.keys(result.responses[name]).forEach(function (q) {
        forms[q] = result.responses[name][q].formula;
      });
      out.responses[name] = forms;
    });
  }

  if (result.ac) {
    const nodes = {};
    circuit.nodes().forEach(function (node) {
      const value = result.ac.solution.nodeVoltage(node);
      nodes[node] = exact(value.re) + '|' + exact(value.im);
    });
    const branches = {};
    circuit.elements.forEach(function (element) {
      const v = result.ac.solution.elementVoltage(element);
      const i = result.ac.solution.elementCurrent(element);
      branches[element.name] = {
        v: exact(v.re) + '|' + exact(v.im),
        i: exact(i.re) + '|' + exact(i.im)
      };
    });
    const z = {};
    Object.keys(result.ac.impedances).forEach(function (n) {
      const value = result.ac.impedances[n];
      z[n] = exact(value.re) + '|' + exact(value.im);
    });
    out.ac = { omega: exact(result.ac.omega), nodes: nodes, branches: branches, z: z };
  }
  return out;
}

const suffix = process.argv[2] ? '_' + process.argv[2] : '';
const corpus = JSON.parse(fs.readFileSync(path.join(HERE, 'corpus' + suffix + '.json'), 'utf8'));
const results = {};
Object.keys(corpus).forEach(function (name) {
  results[name] = dumpOne(corpus[name]);
});

fs.writeFileSync(path.join(HERE, 'results_js' + suffix + '.json'),
  JSON.stringify(results, null, 1));
console.log('dumped ' + Object.keys(corpus).length + ' circuits');
