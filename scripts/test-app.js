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

assert.equal(profileOrDefault('minimal'), 'minimal');
assert.equal(profileOrDefault('unknown'), 'minimal');
assert.equal(safeProjectName('../bad name!'), 'bad-name');
assert.equal(safeProjectName(''), 'iphone-dev-check');
assert.equal(safeProjectName('a'.repeat(80)).length, 48);
assert.equal(safeRequestTitle('  Bitte   updaten  '), 'Bitte updaten');
assert.equal(scopeOrDefault('deploy'), 'deploy');
assert.equal(scopeOrDefault('unknown'), 'setup');

const inject = buildInjectScript('../bad name!', 'unknown');
assert.equal(inject.name, 'bad-name');
assert.equal(inject.profileName, 'minimal');
assert.match(inject.script, /umask 077/);
assert.doesNotMatch(inject.script, /\.\./);
assert.match(inject.script, /\$HOME\/Developer\/scratch\/\$PROJECT/);

const packet = buildRequestPacket('Deploy aktualisieren', 'deploy');
assert.match(packet, /# Request: Deploy aktualisieren/);
assert.match(packet, /Deploy & Offline/);
assert.match(packet, /- \[ \] npm test/);
assert.match(buildRequestPacket('', 'unknown'), /Setup & Init/);

const numbering = checkNumbering('## 1. Eins\n## 2. Zwei\n');
assert.equal(numbering.ok, true);
assert.equal(checkNumbering('## 1. Eins\n## 3. Drei\n').ok, false);

console.log('app tests ok');
