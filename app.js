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

/**
 * Retrieve an element matching a CSS selector from the document, throwing if none is found.
 *
 * @param {string} selector - CSS selector to locate the element via document.querySelector.
 * @returns {Element} The matched DOM element.
 * @throws {Error} If no element matches the selector; error message is `Required element missing: {selector}`.
 */
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

/**
 * Selects a setup profile and updates the UI to reflect that selection.
 *
 * Updates the plan checklist, autonomy checkboxes, and the visual/ARIA state of all `.profile` buttons for the chosen profile; if `name` does not match a known profile, the `'minimal'` profile is selected. After updating the UI, regenerates the script for the active profile.
 *
 * @param {string} name - The requested profile identifier; falls back to `'minimal'` when unknown.
 */
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

/**
 * Normalize a user-provided project name into a compact, safe identifier.
 * @param {string} value - Raw project name input from the user.
 * @returns {string} The cleaned name: trims whitespace, replaces disallowed characters with `-`, collapses repeated `-`, strips leading/trailing `.` or `-`, and truncates to 48 characters. Returns `'iphone-dev-check'` if the result is empty.
 */
function safeProjectName(value) {
  const cleaned = value
    .trim()
    .replace(/[^a-zA-Z0-9._-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[.-]+|[.-]+$/g, '')
    .slice(0, 48);
  return cleaned || 'iphone-dev-check';
}

/**
 * Updates the generated shell script and the project-name input according to the chosen profile and a sanitized project name.
 *
 * Writes the assembled script into the `scriptOutput` element's textContent and updates `projectName.value` with the sanitized name.
 *
 * @param {string} [profileName] - Profile key controlling the extra script snippet; commonly "minimal", "linux", or "hybrid". Defaults to the currently active `.profile` button's `data-profile` or `"minimal"`.
 */
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

/**
 * Copies the generated script text to the clipboard and updates the copy status message.
 *
 * On success sets copyStatus.textContent to 'Skript wurde kopiert.'; on failure sets it to
 * 'Kopieren nicht möglich. Bitte Skript manuell markieren.'.
 */
async function copyScript() {
  try {
    await navigator.clipboard.writeText(scriptOutput.textContent);
    copyStatus.textContent = 'Skript wurde kopiert.';
  } catch {
    copyStatus.textContent = 'Kopieren nicht möglich. Bitte Skript manuell markieren.';
  }
}

/**
 * Load the guide markdown from docs/iphone-local-dev-setup.md, falling back to the document body text if fetching fails.
 * @returns {string} The guide content: the fetched markdown text when successful, otherwise `document.body.innerText`.
 */
async function loadGuideText() {
  try {
    const response = await fetch('docs/iphone-local-dev-setup.md', { cache: 'no-cache' });
    if (!response.ok) throw new Error('Guide nicht ladbar');
    return await response.text();
  } catch {
    return document.body.innerText;
  }
}

/**
 * Verify that top-level markdown headings of the form `## N. ` form a contiguous sequence starting at 1.
 * @param {string} text - Markdown text to scan for top-level numbered headings (`## N. `).
 * @returns {{label: string, ok: boolean, detail: string}} An object describing the check:
 *   - `label`: a short description of the check.
 *   - `ok`: `true` if the extracted heading numbers equal `[1, 2, ..., n]`, `false` otherwise.
 *   - `detail`: when `ok` is `true`, a summary like "`<n> Abschnitte geprüft.`"; when `ok` is `false`, a string showing the found sequence (e.g. "`Gefunden: 1, 3, 4`") or a message indicating no numbered sections were found.
 */
function checkNumbering(text) {
  const headings = [...text.matchAll(/^## (\d+)\. /gm)].map((match) => Number(match[1]));
  if (headings.length === 0) return { label: 'Top-Level-Nummerierung gefunden', ok: false, detail: 'Keine nummerierten Abschnitte gefunden.' };
  const expected = headings.map((_, index) => index + 1);
  const ok = headings.every((value, index) => value === expected[index]);
  return { label: 'Durchgehende Top-Level-Nummerierung', ok, detail: ok ? `${headings.length} Abschnitte geprüft.` : `Gefunden: ${headings.join(', ')}` };
}

/**
 * Create a list item element representing a QA/result entry.
 *
 * @param {Object} options - Configuration for the result item.
 * @param {string} options.label - Short title of the check.
 * @param {boolean} options.ok - Whether the check passed.
 * @param {string} options.detail - Human-readable details or context for the result.
 * @param {string} [options.level='ok'] - Visual severity class used when `ok` is false (e.g., 'warning', 'error').
 * @returns {HTMLLIElement} An <li> element containing a status dot and formatted text for the result.
 */
function resultItem({ label, ok, detail, level = 'ok' }) {
  const li = document.createElement('li');
  const dot = document.createElement('span');
  dot.className = `dot ${ok ? 'ok' : level}`;
  li.append(dot, `${label}: ${ok ? 'OK' : 'Prüfen'} — ${detail}`);
  return li;
}

/**
 * Run the QA checks against the guide text and render the results into the UI.
 *
 * Loads the guide text, evaluates each rule in `riskyPatterns` and the top-level
 * heading numbering check, then replaces the children of `qaResults` with list
 * items summarizing each check. Each result includes the rule label, whether it
 * passed, a textual detail (including the first matched snippet when present),
 * and the rule severity level.
 */
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
