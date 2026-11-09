/**
 * Build-time guard: every relative import reachable from server.js must exist.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * The production Dockerfile copies an explicit list of source files into the
 * runtime stage. That list went stale: server.js imports ./db.js and four
 * modules under ./publishing/, none of which were being copied. The image
 * built without error, every test passed on the host, and the container then
 * died on its first boot with
 *
 *   Error [ERR_MODULE_NOT_FOUND]: Cannot find module '/app/db.js'
 *
 * which Render surfaces only as a failed deploy. An allow-list of COPY
 * directives is guaranteed to go stale again, so the build now proves the
 * import graph resolves instead of assuming it.
 *
 * Run standalone too:  node verify-imports.mjs
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const ENTRY = path.join(ROOT, 'server.js');

// Matches  import x from './y.js'  /  export * from './y.js'  /  await import('./y.js')
const RELATIVE_IMPORT = /(?:\bfrom|\bimport)\s*\(?\s*['"](\.[^'"]+)['"]/g;

const seen = new Set();
const missing = [];

function walk(file) {
  if (seen.has(file)) return;
  seen.add(file);

  let source;
  try {
    source = fs.readFileSync(file, 'utf8');
  } catch {
    missing.push(path.relative(ROOT, file));
    return;
  }

  for (const match of source.matchAll(RELATIVE_IMPORT)) {
    walk(path.resolve(path.dirname(file), match[1]));
  }
}

walk(ENTRY);

if (missing.length) {
  console.error('Unresolvable runtime modules (the image would crash on boot):');
  missing.forEach((m) => console.error(`  - ${m}`));
  process.exit(1);
}

console.log(`Import graph OK — ${seen.size} modules resolve from server.js`);
