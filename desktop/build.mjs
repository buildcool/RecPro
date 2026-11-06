import { build, context } from 'esbuild';

const watch = process.argv.includes('--watch');

const common = {
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node22',
  external: ['electron'],
  sourcemap: true,
  logLevel: 'info',
};

const entries = [
  { ...common, entryPoints: ['src/main.ts'], outfile: 'dist/main.js' },
  { ...common, entryPoints: ['src/preload.ts'], outfile: 'dist/preload.js' },
  // the updater on its own, for test/updater-check.cjs (not packaged)
  { ...common, entryPoints: ['src/updater.ts'], outfile: 'dist/test/updater.js', external: ['electron', 'electron-updater'] },
];

if (watch) {
  for (const e of entries) {
    const ctx = await context(e);
    await ctx.watch();
  }
} else {
  await Promise.all(entries.map((e) => build(e)));
}
