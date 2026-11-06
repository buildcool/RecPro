// Version bumps and release checks (the steps are in docs/DEVELOPMENT.md → Releasing).
//   node scripts/release.mjs set 0.2.0     writes the version everywhere, opens its changelog section,
//                                          drafts docs/releases/v0.2.0.md from it
//   node scripts/release.mjs check 0.2.0   versions agree, the changelog has [0.2.0], the notes are written
//                                          (the release workflow runs this before tagging)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const rel = (p) => path.join(ROOT, p);
const read = (p) => fs.readFileSync(rel(p), 'utf8');
const write = (p, s) => fs.writeFileSync(rel(p), s);
const DRAFT = '<!-- draft: replace with what changed for people using RecPro -->';

const [cmd, version] = process.argv.slice(2);
if (!['set', 'check'].includes(cmd) || !/^\d+\.\d+\.\d+$/.test(version || '')) {
  console.error('usage: node scripts/release.mjs set|check X.Y.Z');
  process.exit(2);
}

function versions() {
  const out = {};
  out['engine/pyproject.toml'] = read('engine/pyproject.toml').match(/^version = "([^"]+)"/m)?.[1];
  out['engine/recpro/__init__.py'] = read('engine/recpro/__init__.py').match(/__version__ = "([^"]+)"/)?.[1];
  out['engine/uv.lock'] = read('engine/uv.lock').match(/name = "recpro-engine"\nversion = "([^"]+)"/)?.[1];
  for (const p of ['package.json', 'desktop/package.json', 'ui/package.json']) out[p] = JSON.parse(read(p)).version;
  const lock = JSON.parse(read('package-lock.json'));
  out['package-lock.json'] = lock.version;
  out['package-lock.json packages[""]'] = lock.packages[''].version;
  for (const ws of ['desktop', 'ui']) out[`package-lock.json packages/${ws}`] = lock.packages[ws].version;
  return out;
}

function setVersion(v) {
  write('engine/pyproject.toml', read('engine/pyproject.toml').replace(/^version = "[^"]+"/m, `version = "${v}"`));
  write('engine/recpro/__init__.py', read('engine/recpro/__init__.py').replace(/__version__ = "[^"]+"/, `__version__ = "${v}"`));
  write('engine/uv.lock', read('engine/uv.lock').replace(/(name = "recpro-engine"\nversion = )"[^"]+"/, `$1"${v}"`));
  for (const p of ['package.json', 'desktop/package.json', 'ui/package.json']) {
    write(p, read(p).replace(/("version": )"[^"]+"/, `$1"${v}"`));
  }
  const lock = JSON.parse(read('package-lock.json'));
  lock.version = v;
  lock.packages[''].version = v;
  for (const ws of ['desktop', 'ui']) lock.packages[ws].version = v;
  write('package-lock.json', JSON.stringify(lock, null, 2) + '\n');
}

function changelogSection(v) {
  const log = read('CHANGELOG.md');
  const start = log.indexOf(`## [${v}]`);
  if (start < 0) return null;
  const next = log.indexOf('\n## ', start + 4);
  return log.slice(start, next < 0 ? undefined : next).trim();
}

if (cmd === 'set') {
  setVersion(version);
  let log = read('CHANGELOG.md');
  if (!log.includes(`## [${version}]`)) {
    const date = new Date().toISOString().slice(0, 10);
    log = log.replace(/^## Unreleased\s*$/m, `## Unreleased\n\n## [${version}] — ${date}`);
    write('CHANGELOG.md', log);
  }
  const notes = `docs/releases/v${version}.md`;
  if (!fs.existsSync(rel(notes))) {
    fs.mkdirSync(rel('docs/releases'), { recursive: true });
    const body = (changelogSection(version) || '').split('\n').slice(1).join('\n').trim();
    write(notes, `# RecPro v${version}\n\n${DRAFT}\n\n${body}\n\nThe app updates itself to this version, or asks first (Settings → Updates).\n`);
  }
  console.log(`version ${version} set; edit ${notes}, then: node scripts/release.mjs check ${version}`);
} else {
  const problems = [];
  for (const [file, v] of Object.entries(versions())) if (v !== version) problems.push(`${file} has ${v}, not ${version}`);
  if (!changelogSection(version)) problems.push(`CHANGELOG.md has no "## [${version}]" section`);
  const notes = `docs/releases/v${version}.md`;
  if (!fs.existsSync(rel(notes))) problems.push(`${notes} is missing`);
  else if (read(notes).includes(DRAFT)) problems.push(`${notes} is still the draft`);
  if (problems.length) {
    console.error(problems.map((p) => `- ${p}`).join('\n'));
    process.exit(1);
  }
  console.log(`release ${version}: versions agree, changelog and notes are ready`);
}
