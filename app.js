const profiles = {
  minimal: {
    steps: [
      'Working Copy installieren und Git-Konto verbinden.',
      'Textastic oder Code App installieren und Repository als externen Ordner öffnen.',
      'a-Shell öffnen und python3 --version ausführen.',
      'README.md ändern, Diff in Working Copy prüfen, committen und pushen.'
    ],
    checks: ['Kein Build-Schritt', 'Funktioniert offline für Text/kleine Skripte', 'Git bleibt die Synchronisationsquelle']
  },
  linux: {
    steps: [
      'iSH installieren und apk update ausführen.',
      'Basiswerkzeuge mit apk add git openssh curl wget nano vim python3 py3-pip nodejs npm make installieren.',
      'Git-Identität und SSH-Key in iSH konfigurieren.',
      'Kleine Python-/Node-Checks ausführen, bevor große Abhängigkeiten installiert werden.'
    ],
    checks: ['Alpine-nahe Shell', 'Lokale Paketverwaltung', 'Nicht für schwere Builds optimiert']
  },
  hybrid: {
    steps: [
      'iPhone als Editor- und Git-Client nutzen.',
      'Remote-Host per SSH vorbereiten und Repository in ~/projects klonen.',
      'Builds, Docker, Datenbanken und lange Tests remote ausführen.',
      'Änderungen über Git zwischen iPhone, Remote-Host und Plattform synchronisieren.'
    ],
    checks: ['Stabil für große Projekte', 'Benötigt Remote-Host', 'Beste Option für CI-nahe Arbeit']
  }
};

const riskyPatterns = [
  { label: 'Foto-/OCR-Artefakte', pattern: /\b(Foto|photo|Bildfehler|OCR)\b/i, level: 'warn' },
  { label: 'TODO/FIXME-Reste', pattern: /\b(TODO|FIXME|XXX)\b/i, level: 'warn' },
  { label: 'Blinde Remote-Ausführung', pattern: /(curl|wget).*(\|\s*(sh|bash))/i, level: 'bad' },
  { label: 'Platzhalter-Domain example.com', pattern: /example\.com/i, level: 'warn' },
  { label: 'Unklare None-Artefakte', pattern: /\bNone\b/i, level: 'warn' }
];

function requiredElement(selector) {
  const element = document.querySelector(selector);
  if (!element) {
    throw new Error(`Required element missing: ${selector}`);
  }
  return element;
}

const planOutput = requiredElement('#planOutput');
const autonomyChecks = requiredElement('#autonomyChecks');
const scriptOutput = requiredElement('#scriptOutput');
const projectName = requiredElement('#projectName');
const copyStatus = requiredElement('#copyStatus');
const qaResults = requiredElement('#qaResults');

function setProfile(name) {
  const profileName = profiles[name] ? name : 'minimal';
  const profile = profiles[profileName];
  planOutput.replaceChildren(...profile.steps.map((step) => {
    const li = document.createElement('li');
    li.textContent = step;
    return li;
  }));

  autonomyChecks.replaceChildren(...profile.checks.map((check) => {
    const label = document.createElement('label');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = true;
    label.append(box, ` ${check}`);
    return label;
  }));

  document.querySelectorAll('.profile').forEach((button) => {
    const active = button.dataset.profile === profileName;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  renderScript(profileName);
}

function safeProjectName(value) {
  const cleaned = value
    .trim()
    .replace(/[^a-zA-Z0-9._-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[.-]+|[.-]+$/g, '')
    .slice(0, 48);
  return cleaned || 'iphone-dev-check';
}

function renderScript(profileName = document.querySelector('.profile.active')?.dataset.profile || 'minimal') {
  const name = safeProjectName(projectName.value);
  const common = `set -eu\numask 077\nPROJECT="${name}"\nmkdir -p "$HOME/Developer/scratch/$PROJECT"\ncd "$HOME/Developer/scratch/$PROJECT"\ncat > README.md <<'MD'\n# ${name}\n\nAutonom erzeugtes iPhone-Entwicklungsprojekt.\nMD\ncat > hello.py <<'PY'\nprint("iPhone Direct-Inject OK")\nPY\npython3 hello.py`;

  const extras = {
    minimal: '\nprintf "\\nMinimalprofil bereit. Öffne den Ordner im Editor und committe über Working Copy.\\n"',
    linux: '\nprintf "\\nOptional in iSH ausführen: apk update && apk add git openssh python3 nodejs npm\\n"',
    hybrid: '\ncat > remote-checklist.txt <<\'TXT\'\nssh dev@dein-host\nmkdir -p ~/projects\n# git clone git@github.com:dein-name/dein-repo.git\nTXT\nprintf "\\nHybridprofil bereit. Siehe remote-checklist.txt.\\n"'
  };

  scriptOutput.textContent = `${common}${extras[profileName] || extras.minimal}\n`;
  projectName.value = name;
}

async function copyScript() {
  try {
    await navigator.clipboard.writeText(scriptOutput.textContent);
    copyStatus.textContent = 'Skript wurde kopiert.';
  } catch {
    copyStatus.textContent = 'Kopieren nicht möglich. Bitte Skript manuell markieren.';
  }
}

async function loadGuideText() {
  try {
    const response = await fetch('docs/iphone-local-dev-setup.md', { cache: 'no-cache' });
    if (!response.ok) throw new Error('Guide nicht ladbar');
    return await response.text();
  } catch {
    return document.body.innerText;
  }
}

function checkNumbering(text) {
  const headings = [...text.matchAll(/^## (\d+)\. /gm)].map((match) => Number(match[1]));
  if (headings.length === 0) return { label: 'Top-Level-Nummerierung gefunden', ok: false, detail: 'Keine nummerierten Abschnitte gefunden.' };
  const expected = headings.map((_, index) => index + 1);
  const ok = headings.every((value, index) => value === expected[index]);
  return { label: 'Durchgehende Top-Level-Nummerierung', ok, detail: ok ? `${headings.length} Abschnitte geprüft.` : `Gefunden: ${headings.join(', ')}` };
}

function resultItem({ label, ok, detail, level = 'ok' }) {
  const li = document.createElement('li');
  const dot = document.createElement('span');
  dot.className = `dot ${ok ? 'ok' : level}`;
  li.append(dot, `${label}: ${ok ? 'OK' : 'Prüfen'} — ${detail}`);
  return li;
}

async function runQa() {
  const text = await loadGuideText();
  const results = riskyPatterns.map((rule) => {
    const match = text.match(rule.pattern);
    return {
      label: rule.label,
      ok: !match,
      detail: match ? `Treffer „${match[0]}“ gefunden.` : 'Keine Treffer.',
      level: rule.level
    };
  });
  results.push(checkNumbering(text));
  qaResults.replaceChildren(...results.map(resultItem));
}

document.querySelectorAll('.profile').forEach((button) => {
  button.addEventListener('click', () => setProfile(button.dataset.profile));
});
projectName.addEventListener('input', () => renderScript());
requiredElement('#copyScript').addEventListener('click', copyScript);

if ('serviceWorker' in navigator && location.protocol !== 'file:') {
  navigator.serviceWorker.register('service-worker.js').catch(() => {});
}

setProfile('minimal');
runQa();
