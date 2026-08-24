// Build a single self-contained HTML file: no server, no modules on disk, no
// network. Open it and it runs.
//
//   node tools/bundle.mjs [out.html]
//
// ES modules and AudioWorklets can only be loaded from URLs, so each module is
// turned into a blob URL and its import specifiers are rewritten to point at
// the blobs. Dependencies are built first, so a module's blob URL always exists
// by the time anything imports it.

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join, normalize } from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname;
const ENTRY = 'src/app.js';
const WORKLET = 'src/dsp/reverb-worklet.js';
const args = process.argv.slice(2);
/** Artifact hosts supply the document shell, so emit page content only. */
const ARTIFACT = args.includes('--artifact');
const out = args.find((a) => !a.startsWith('--'))
  || join(ROOT, 'dist', ARTIFACT ? 'reverbspace.artifact.html' : 'reverbspace.html');

const read = (rel) => readFileSync(join(ROOT, rel), 'utf8');

/** Every relative specifier a module imports from. */
function importsOf(src) {
  const specs = [];
  const re = /(?:^|\n)\s*(?:import|export)[\s\S]*?from\s*['"](\.[^'"]+)['"]/g;
  let m;
  while ((m = re.exec(src))) specs.push(m[1]);
  return specs;
}

const resolve = (from, spec) => normalize(join(dirname(from), spec));

// Depth-first walk, dependencies emitted before dependents.
const order = [];
const seen = new Set();
const sources = new Map();

function visit(rel, stack = []) {
  if (seen.has(rel)) return;
  if (stack.includes(rel)) throw new Error(`import cycle: ${[...stack, rel].join(' -> ')}`);
  const src = read(rel);
  sources.set(rel, src);
  for (const spec of importsOf(src)) visit(resolve(rel, spec), [...stack, rel]);
  seen.add(rel);
  order.push(rel);
}

visit(ENTRY);
visit(WORKLET);

const html = read('index.html');
const css = read('styles.css');

// Strip the parts of the page that assume files on disk.
let body = html
  .replace(/^[\s\S]*?<body>/, '')
  .replace(/<\/body>[\s\S]*$/, '')
  .replace(/\s*<script type="module" src="src\/app\.js"><\/script>/, '')
  .trim();

const head = html.match(/<link rel="icon" href="([^"]+)">/);
const title = (html.match(/<title>([^<]*)<\/title>/) || [, 'ReverbSpace'])[1];

const modules = order.map((rel) => ({ path: rel, source: sources.get(rel) }));

const shellOpen = ARTIFACT ? `<title>${title}</title>
<style>
${css}
</style>` : `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
${head ? `<link rel="icon" href="${head[1]}">` : ''}
<style>
${css}
</style>
</head>
<body>`;

const page = `${shellOpen}
${body}
<script id="reverbspace-modules" type="application/json">
${JSON.stringify(modules).replace(/</g, '\\u003c')}
</script>
<script>
(function () {
  var modules = JSON.parse(document.getElementById('reverbspace-modules').textContent);
  var urls = Object.create(null);

  function dir(p) { return p.slice(0, p.lastIndexOf('/')); }
  function resolve(from, spec) {
    var parts = (dir(from) + '/' + spec).split('/');
    var stack = [];
    for (var i = 0; i < parts.length; i++) {
      if (parts[i] === '.' || parts[i] === '') continue;
      if (parts[i] === '..') stack.pop();
      else stack.push(parts[i]);
    }
    return stack.join('/');
  }

  // Dependencies come first in this list, so every blob URL exists before the
  // module that imports it is built.
  for (var i = 0; i < modules.length; i++) {
    var m = modules[i];
    var rewritten = m.source.replace(
      /from\\s*(['"])(\\.[^'"]+)\\1/g,
      (function (path) {
        return function (match, quote, spec) {
          var target = urls[resolve(path, spec)];
          return target ? "from '" + target + "'" : match;
        };
      })(m.path));
    urls[m.path] = URL.createObjectURL(new Blob([rewritten], { type: 'text/javascript' }));
  }

  globalThis.__REVERBSPACE_WORKLET_URL__ = urls['src/dsp/reverb-worklet.js'];

  import(urls['src/app.js']).catch(function (err) {
    var el = document.getElementById('overlay');
    if (el) {
      el.classList.remove('gone');
      el.innerHTML = '<p><strong>ReverbSpace could not start.</strong></p><p>' +
        String(err && err.message || err) + '</p>';
    }
    throw err;
  });
})();
</script>
${ARTIFACT ? '' : '</body>\n</html>'}
`;

mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, page);
const kb = (page.length / 1024).toFixed(0);
console.log(`${out}  (${kb} KB, ${modules.length} modules inlined)`);
