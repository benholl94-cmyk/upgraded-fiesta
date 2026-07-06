const assert = require('node:assert/strict');
const {
  buildInjectScript,
  buildRequestPacket,
  checkNumbering,
  profileOrDefault,
  safeProjectName,
  safeRequestTitle,
  scopeOrDefault
} = require('../app.js');

// --- profileOrDefault ---
assert.equal(profileOrDefault('minimal'), 'minimal');
assert.equal(profileOrDefault('linux'), 'linux');
assert.equal(profileOrDefault('hybrid'), 'hybrid');
assert.equal(profileOrDefault('unknown'), 'minimal');
assert.equal(profileOrDefault(''), 'minimal');
assert.equal(profileOrDefault(null), 'minimal');
assert.equal(profileOrDefault(undefined), 'minimal');

// --- scopeOrDefault ---
assert.equal(scopeOrDefault('setup'), 'setup');
assert.equal(scopeOrDefault('security'), 'security');
assert.equal(scopeOrDefault('deploy'), 'deploy');
assert.equal(scopeOrDefault('docs'), 'docs');
assert.equal(scopeOrDefault('unknown'), 'setup');
assert.equal(scopeOrDefault(''), 'setup');
assert.equal(scopeOrDefault(null), 'setup');

// --- safeProjectName ---
assert.equal(safeProjectName('../bad name!'), 'bad-name');
assert.equal(safeProjectName(''), 'iphone-dev-check');
assert.equal(safeProjectName(null), 'iphone-dev-check');
assert.equal(safeProjectName(undefined), 'iphone-dev-check');
assert.equal(safeProjectName('a'.repeat(80)).length, 48);
assert.equal(safeProjectName('a'.repeat(48)).length, 48);
assert.equal(safeProjectName('valid-name_1.0'), 'valid-name_1.0');
assert.equal(safeProjectName('  spaces  '), 'spaces');
// leading/trailing dots stripped
assert.equal(safeProjectName('...dotted...'), 'dotted');
// only dots → fallback
assert.equal(safeProjectName('...'), 'iphone-dev-check');
// multiple consecutive special chars collapse to single dash
assert.equal(safeProjectName('foo!!bar'), 'foo-bar');
// path traversal chars become dashes then cleaned
assert.doesNotMatch(safeProjectName('../../etc/passwd'), /\.\./);
// numbers only is valid
assert.equal(safeProjectName('123'), '123');

// --- safeRequestTitle ---
assert.equal(safeRequestTitle('  Bitte   updaten  '), 'Bitte updaten');
assert.equal(safeRequestTitle(''), 'iPhone Setup aktualisieren');
assert.equal(safeRequestTitle(null), 'iPhone Setup aktualisieren');
assert.equal(safeRequestTitle(undefined), 'iPhone Setup aktualisieren');
// exactly 80 chars preserved
assert.equal(safeRequestTitle('a'.repeat(80)).length, 80);
// over 80 chars truncated
assert.equal(safeRequestTitle('a'.repeat(100)).length, 80);
// internal whitespace collapsed
assert.equal(safeRequestTitle('foo   bar\t\nbaz'), 'foo bar baz');

// --- buildInjectScript ---
// unknown profile falls back to minimal
const inject = buildInjectScript('../bad name!', 'unknown');
assert.equal(inject.name, 'bad-name');
assert.equal(inject.profileName, 'minimal');
assert.match(inject.script, /umask 077/);
assert.match(inject.script, /set -eu/);
assert.doesNotMatch(inject.script, /\.\./);
assert.match(inject.script, /\$HOME\/Developer\/scratch\/\$PROJECT/);
assert.match(inject.script, /python3 hello\.py/);

// minimal profile specific text
const injectMinimal = buildInjectScript('my-project', 'minimal');
assert.equal(injectMinimal.profileName, 'minimal');
assert.match(injectMinimal.script, /Minimalprofil bereit/);
assert.doesNotMatch(injectMinimal.script, /apk/);

// linux profile specific text
const injectLinux = buildInjectScript('my-project', 'linux');
assert.equal(injectLinux.profileName, 'linux');
assert.match(injectLinux.script, /apk/);
assert.doesNotMatch(injectLinux.script, /remote-checklist/);

// hybrid profile specific text
const injectHybrid = buildInjectScript('my-project', 'hybrid');
assert.equal(injectHybrid.profileName, 'hybrid');
assert.match(injectHybrid.script, /remote-checklist\.txt/);
assert.match(injectHybrid.script, /Hybridprofil bereit/);

// project name appears in generated script content
const injectNamed = buildInjectScript('my-app', 'minimal');
assert.match(injectNamed.script, /PROJECT="my-app"/);
assert.match(injectNamed.script, /# my-app/);

// script ends with newline
assert.ok(injectMinimal.script.endsWith('\n'));

// --- buildRequestPacket ---
const packetDeploy = buildRequestPacket('Deploy aktualisieren', 'deploy');
assert.match(packetDeploy, /# Request: Deploy aktualisieren/);
assert.match(packetDeploy, /Deploy & Offline/);
assert.match(packetDeploy, /- \[ \] npm test/);
assert.match(packetDeploy, /- \[ \] npm run init/);
assert.match(packetDeploy, /Sicherheitsgrenzen/);
assert.match(packetDeploy, /Abnahme/);
assert.match(packetDeploy, /curl \| sh/);

// empty title and unknown scope → defaults
const packetDefault = buildRequestPacket('', 'unknown');
assert.match(packetDefault, /Setup & Init/);
assert.match(packetDefault, /iPhone Setup aktualisieren/);

// security scope
const packetSecurity = buildRequestPacket('Sicherheit prüfen', 'security');
assert.match(packetSecurity, /Security & Clean Access/);
assert.match(packetSecurity, /Secrets ausschließen/);

// docs scope
const packetDocs = buildRequestPacket('Doku aktualisieren', 'docs');
assert.match(packetDocs, /Dokumentation & QA/);
assert.match(packetDocs, /Guide-QA ausführen/);

// setup scope
const packetSetup = buildRequestPacket('Init testen', 'setup');
assert.match(packetSetup, /Setup & Init/);
assert.match(packetSetup, /Init-Befehl ausführen/);

// checklist items use markdown checkbox format
assert.match(packetDeploy, /- \[ \] Statische Dateien validieren/);
assert.match(packetSecurity, /- \[ \] Schreibpfade prüfen/);

// --- checkNumbering ---
// sequential headings → ok
const num2 = checkNumbering('## 1. Eins\n## 2. Zwei\n');
assert.equal(num2.ok, true);
assert.match(num2.detail, /2 Abschnitte/);

// non-sequential → not ok
const numBad = checkNumbering('## 1. Eins\n## 3. Drei\n');
assert.equal(numBad.ok, false);
assert.match(numBad.detail, /1, 3/);

// no headings → not ok with specific label
const numEmpty = checkNumbering('# Titel\n### Unterabschnitt\n');
assert.equal(numEmpty.ok, false);
assert.match(numEmpty.detail, /Keine nummerierten Abschnitte/);

// single heading starting at 1 → ok
const numOne = checkNumbering('## 1. Einziger\n');
assert.equal(numOne.ok, true);
assert.match(numOne.detail, /1 Abschnitte/);

// starts at 2 instead of 1 → not ok
const numWrongStart = checkNumbering('## 2. Zweiter\n## 3. Dritter\n');
assert.equal(numWrongStart.ok, false);

// large sequential sequence → ok
const largeSeq = Array.from({ length: 20 }, (_, i) => `## ${i + 1}. Abschnitt ${i + 1}`).join('\n') + '\n';
assert.equal(checkNumbering(largeSeq).ok, true);

// detail includes count for ok case
const numThree = checkNumbering('## 1. A\n## 2. B\n## 3. C\n');
assert.match(numThree.detail, /3 Abschnitte/);

console.log('app tests ok');
