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

const requestScopes = {
  setup: {
    label: 'Setup & Init',
    steps: ['Init-Befehl ausführen', 'Direct-Inject-Ausgabe prüfen', 'Minimalprofil testen']
  },
  security: {
    label: 'Security & Clean Access',
    steps: ['Secrets ausschließen', 'Schreibpfade prüfen', 'Riskante Remote-Ausführung blockieren']
  },
  deploy: {
    label: 'Deploy & Offline',
    steps: ['Statische Dateien validieren', 'Service Worker Cache prüfen', 'Hosting-URL öffnen']
  },
  docs: {
    label: 'Dokumentation & QA',
    steps: ['Guide-QA ausführen', 'Nummerierung prüfen', 'Schnellstart gegen UI abgleichen']
  }
};

const riskyPatterns = [
  { label: 'Foto-/OCR-Artefakte', pattern: /\b(Foto|photo|Bildfehler|OCR)\b/i, level: 'warn' },
  { label: 'TODO/FIXME-Reste', pattern: /\b(TODO|FIXME|XXX)\b/i, level: 'warn' },
  { label: 'Blinde Remote-Ausführung', pattern: /(curl|wget).*(\|\s*(sh|bash))/i, level: 'bad' },
  { label: 'Platzhalter-Domain example.com', pattern: /example\.com/i, level: 'warn' },
  { label: 'Unklare None-Artefakte', pattern: /\bNone\b/i, level: 'warn' }
];

function requiredElement(root, selector) {
  const element = root.querySelector(selector);
  if (!element) {
    throw new Error(`Required element missing: ${selector}`);
  }
  return element;
}

function profileOrDefault(name) {
  return profiles[name] ? name : 'minimal';
}

function scopeOrDefault(value) {
  return requestScopes[value] ? value : 'setup';
}

function safeProjectName(value) {
  const cleaned = String(value || '')
    .trim()
    .replace(/[^a-zA-Z0-9._-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[.-]+|[.-]+$/g, '')
    .slice(0, 48);
  return cleaned || 'iphone-dev-check';
}

function safeRequestTitle(value) {
  return String(value || '')
    .trim()
    .replace(/\s+/g, ' ')
    .slice(0, 80) || 'iPhone Setup aktualisieren';
}

function buildInjectScript(projectNameValue, profileNameValue) {
  const name = safeProjectName(projectNameValue);
  const profileName = profileOrDefault(profileNameValue);
  const common = `set -eu\numask 077\nPROJECT="${name}"\nmkdir -p "$HOME/Developer/scratch/$PROJECT"\ncd "$HOME/Developer/scratch/$PROJECT"\ncat > README.md <<'MD'\n# ${name}\n\nAutonom erzeugtes iPhone-Entwicklungsprojekt.\nMD\ncat > hello.py <<'PY'\nprint("iPhone Direct-Inject OK")\nPY\npython3 hello.py`;

  const extras = {
    minimal: '\nprintf "\\nMinimalprofil bereit. Öffne den Ordner im Editor und committe über Working Copy.\\n"',
    linux: '\nprintf "\\nOptional in iSH ausführen: apk update && apk add git openssh python3 nodejs npm\\n"',
    hybrid: '\ncat > remote-checklist.txt <<\'TXT\'\nssh dev@dein-host\nmkdir -p ~/projects\n# git clone git@github.com:dein-name/dein-repo.git\nTXT\nprintf "\\nHybridprofil bereit. Siehe remote-checklist.txt.\\n"'
  };

  return {
    name,
    profileName,
    script: `${common}${extras[profileName]}\n`
  };
}

function buildRequestPacket(titleValue, scopeValue) {
  const title = safeRequestTitle(titleValue);
  const scope = scopeOrDefault(scopeValue);
  const scopeConfig = requestScopes[scope];
  const checklist = scopeConfig.steps.map((step) => `- [ ] ${step}`).join('\n');

  return `# Request: ${title}\n\n## Umfang\n${scopeConfig.label}\n\n## Ziel\nEine sichere, reproduzierbare Änderung an der iPhone Dev Platform umsetzen, ohne automatische externe Ausführung und ohne Secrets in Projektdateien.\n\n## Update-Plan\n${checklist}\n\n## Sicherheitsgrenzen\n- Keine Tokens, Passwörter oder privaten SSH-Keys speichern.\n- Keine blinden Remote-Ausführungen wie curl | sh einführen.\n- Direct-Inject-Blöcke müssen lesbar bleiben und lokale Pfade klar begrenzen.\n\n## Abnahme\n- [ ] npm run init\n- [ ] npm test\n- [ ] Statischer Serve-Check über http://localhost:8000\n`;
}

function checkNumbering(text) {
  const headings = [...text.matchAll(/^## (\d+)\. /gm)].map((match) => Number(match[1]));
  if (headings.length === 0) return { label: 'Top-Level-Nummerierung gefunden', ok: false, detail: 'Keine nummerierten Abschnitte gefunden.' };
  const expected = headings.map((_, index) => index + 1);
  const ok = headings.every((value, index) => value === expected[index]);
  return { label: 'Durchgehende Top-Level-Nummerierung', ok, detail: ok ? `${headings.length} Abschnitte geprüft.` : `Gefunden: ${headings.join(', ')}` };
}

function resultItem(documentRef, { label, ok, detail, level = 'ok' }) {
  const li = documentRef.createElement('li');
  const dot = documentRef.createElement('span');
  dot.className = `dot ${ok ? 'ok' : level}`;
  li.append(dot, `${label}: ${ok ? 'OK' : 'Prüfen'} — ${detail}`);
  return li;
}

function createPlatform(root = document) {
  const documentRef = root.ownerDocument || root;
  const planOutput = requiredElement(root, '#planOutput');
  const autonomyChecks = requiredElement(root, '#autonomyChecks');
  const scriptOutput = requiredElement(root, '#scriptOutput');
  const projectName = requiredElement(root, '#projectName');
  const copyStatus = requiredElement(root, '#copyStatus');
  const qaResults = requiredElement(root, '#qaResults');
  const copyButton = requiredElement(root, '#copyScript');
  const requestTitle = requiredElement(root, '#requestTitle');
  const requestScope = requiredElement(root, '#requestScope');
  const requestOutput = requiredElement(root, '#requestOutput');
  const requestStatus = requiredElement(root, '#requestStatus');
  const copyRequestButton = requiredElement(root, '#copyRequest');
  const profileButtons = [...root.querySelectorAll('.profile')];

  function renderScript(profileNameValue = root.querySelector('.profile.active')?.dataset.profile || 'minimal') {
    const output = buildInjectScript(projectName.value, profileNameValue);
    scriptOutput.textContent = output.script;
    projectName.value = output.name;
    return output;
  }

  function renderRequest() {
    const packet = buildRequestPacket(requestTitle.value, requestScope.value);
    requestOutput.textContent = packet;
    requestTitle.value = safeRequestTitle(requestTitle.value);
    return packet;
  }

  function setProfile(name) {
    const profileName = profileOrDefault(name);
    const profile = profiles[profileName];
    planOutput.replaceChildren(...profile.steps.map((step) => {
      const li = documentRef.createElement('li');
      li.textContent = step;
      return li;
    }));

    autonomyChecks.replaceChildren(...profile.checks.map((check) => {
      const label = documentRef.createElement('label');
      const box = documentRef.createElement('input');
      box.type = 'checkbox';
      box.checked = true;
      label.append(box, ` ${check}`);
      return label;
    }));

    profileButtons.forEach((button) => {
      const active = button.dataset.profile === profileName;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    renderScript(profileName);
  }

  async function copyScript() {
    try {
      await navigator.clipboard.writeText(scriptOutput.textContent);
      copyStatus.textContent = 'Skript wurde kopiert.';
    } catch {
      copyStatus.textContent = 'Kopieren nicht möglich. Bitte Skript manuell markieren.';
    }
  }

  async function copyRequest() {
    try {
      await navigator.clipboard.writeText(requestOutput.textContent);
      requestStatus.textContent = 'Request wurde kopiert.';
    } catch {
      requestStatus.textContent = 'Kopieren nicht möglich. Bitte Request manuell markieren.';
    }
  }

  async function loadGuideText() {
    try {
      const response = await fetch('docs/iphone-local-dev-setup.md', { cache: 'no-cache' });
      if (!response.ok) throw new Error('Guide nicht ladbar');
      return await response.text();
    } catch {
      return null;
    }
  }

  async function runQa() {
    const text = await loadGuideText();
    if (text === null) {
      qaResults.replaceChildren(resultItem(documentRef, {
        label: 'Guide-Ladeprüfung',
        ok: false,
        detail: 'Guide konnte nicht geladen werden. Starte die Plattform über npm run serve oder einen statischen Hoster.',
        level: 'warn'
      }));
      return;
    }

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
    qaResults.replaceChildren(...results.map((result) => resultItem(documentRef, result)));
  }

  profileButtons.forEach((button) => {
    button.addEventListener('click', () => setProfile(button.dataset.profile));
  });
  projectName.addEventListener('input', () => renderScript());
  copyButton.addEventListener('click', copyScript);
  requestTitle.addEventListener('input', renderRequest);
  requestScope.addEventListener('change', renderRequest);
  copyRequestButton.addEventListener('click', copyRequest);
  renderRequest();

  return { setProfile, renderScript, copyScript, renderRequest, copyRequest, runQa };
}

function registerServiceWorker() {
  if ('serviceWorker' in navigator && location.protocol !== 'file:') {
    navigator.serviceWorker.register('service-worker.js').catch(() => {});
  }
}

function initPlatform() {
  const platform = createPlatform(document);
  registerServiceWorker();
  platform.setProfile('minimal');
  platform.runQa();
  document.body.dataset.initStatus = 'ready';
  return platform;
}

function initWhenReady() {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPlatform, { once: true });
    return;
  }
  initPlatform();
}

if (typeof document !== 'undefined') {
  initWhenReady();
}

if (typeof module !== 'undefined') {
  module.exports = {
    buildInjectScript,
    buildRequestPacket,
    checkNumbering,
    profileOrDefault,
    safeProjectName,
    safeRequestTitle,
    scopeOrDefault
  };
}
