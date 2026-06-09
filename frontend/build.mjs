#!/usr/bin/env node
/**
 * PCCS frontend build — purged Tailwind CSS + esbuild JS bundles.
 */
import * as esbuild from 'esbuild';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const jsOutDir = join(root, 'static', 'js', 'bundle');
const cssOut = join(root, 'static', 'css', 'tailwind.css');
const tailwindIn = join(dirname(fileURLToPath(import.meta.url)), 'tailwind.css');
const tailwindCli = join(
  dirname(fileURLToPath(import.meta.url)),
  'node_modules',
  '@tailwindcss',
  'cli',
  'dist',
  'index.mjs',
);

const args = new Set(process.argv.slice(2));
const cssOnly = args.has('--css-only');
const jsOnly = args.has('--js-only');
const watch = args.has('--watch');

function buildCss() {
  if (!existsSync(tailwindCli)) {
    console.error('Run npm install in frontend/ first');
    process.exit(1);
  }
  mkdirSync(dirname(cssOut), { recursive: true });
  execFileSync(
    process.execPath,
    [tailwindCli, '-i', tailwindIn, '-o', cssOut, '--minify'],
    { stdio: 'inherit', cwd: root },
  );
  console.log('✓', cssOut);
}

const jsEntries = [
  { in: join(root, 'static', 'js', 'entries', 'dashboard.js'), out: join(jsOutDir, 'dashboard.js') },
  { in: join(root, 'static', 'js', 'entries', 'diag.js'), out: join(jsOutDir, 'diag.js') },
];

async function buildJs() {
  mkdirSync(jsOutDir, { recursive: true });
  for (const { in: entry, out } of jsEntries) {
    await esbuild.build({
      entryPoints: [entry],
      outfile: out,
      bundle: true,
      format: 'iife',
      target: ['es2020'],
      sourcemap: true,
      logLevel: 'info',
    });
    console.log('✓', out);
  }
}

async function buildJsWatch() {
  mkdirSync(jsOutDir, { recursive: true });
  const contexts = await Promise.all(
    jsEntries.map(({ in: entry, out }) =>
      esbuild.context({
        entryPoints: [entry],
        outfile: out,
        bundle: true,
        format: 'iife',
        target: ['es2020'],
        sourcemap: true,
        logLevel: 'info',
      }),
    ),
  );
  await Promise.all(contexts.map((ctx) => ctx.watch()));
  console.log('watching JS entries…');
}

if (!jsOnly) buildCss();
if (!cssOnly) {
  if (watch) await buildJsWatch();
  else await buildJs();
}