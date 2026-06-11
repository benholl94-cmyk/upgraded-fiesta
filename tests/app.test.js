'use strict';

/**
 * Tests for app.js
 *
 * Strategy:
 * - Pure functions (safeProjectName, checkNumbering) are redefined locally for isolation.
 * - DOM-dependent functions are tested by setting up the required HTML in document.body
 *   before using jest.isolateModules() to load app.js fresh per describe block.
 * - Async functions (copyScript, loadGuideText, runQa) use mock implementations.
 */

// ---------------------------------------------------------------------------
// Helpers: redefined pure functions from app.js for isolated unit testing
// ---------------------------------------------------------------------------

function safeProjectName(value) {
  const cleaned = value
    .trim()
    .replace(/[^a-zA-Z0-9._-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[.-]+|[.-]+$/g, '')
    .slice(0, 48);
  return cleaned || 'iphone-dev-check';
}

function checkNumbering(text) {
  const headings = [...text.matchAll(/^## (\d+)\. /gm)].map((match) => Number(match[1]));
  if (headings.length === 0)
    return { label: 'Top-Level-Nummerierung gefunden', ok: false, detail: 'Keine nummerierten Abschnitte gefunden.' };
  const expected = headings.map((_, index) => index + 1);
  const ok = headings.every((value, index) => value === expected[index]);
  return {
    label: 'Durchgehende Top-Level-Nummerierung',
    ok,
    detail: ok ? `${headings.length} Abschnitte geprüft.` : `Gefunden: ${headings.join(', ')}`
  };
}

// ---------------------------------------------------------------------------
// Minimal DOM scaffold required by app.js at module load time
// ---------------------------------------------------------------------------
function buildScaffold() {
  document.body.innerHTML = `
    <ol id="planOutput"></ol>
    <div id="autonomyChecks"></div>
    <code id="scriptOutput"></code>
    <input id="projectName" value="iphone-dev-check" />
    <p id="copyStatus"></p>
    <ul id="qaResults"></ul>
    <button id="copyScript"></button>
    <button class="profile active" data-profile="minimal" aria-pressed="true"></button>
    <button class="profile" data-profile="linux" aria-pressed="false"></button>
    <button class="profile" data-profile="hybrid" aria-pressed="false"></button>
  `;
}

// ---------------------------------------------------------------------------
// 1. safeProjectName
// ---------------------------------------------------------------------------
describe('safeProjectName', () => {
  test('returns input unchanged when already clean', () => {
    expect(safeProjectName('my-project')).toBe('my-project');
  });

  test('trims leading and trailing whitespace', () => {
    expect(safeProjectName('  hello  ')).toBe('hello');
  });

  test('replaces spaces with hyphens', () => {
    expect(safeProjectName('my project')).toBe('my-project');
  });

  test('replaces disallowed characters with hyphens', () => {
    expect(safeProjectName('hello@world!')).toBe('hello-world');
  });

  test('collapses multiple consecutive hyphens into one', () => {
    expect(safeProjectName('a--b---c')).toBe('a-b-c');
  });

  test('strips leading dots and hyphens', () => {
    expect(safeProjectName('...my-project')).toBe('my-project');
    expect(safeProjectName('---my-project')).toBe('my-project');
  });

  test('strips trailing dots and hyphens', () => {
    expect(safeProjectName('my-project...')).toBe('my-project');
    expect(safeProjectName('my-project---')).toBe('my-project');
  });

  test('truncates at 48 characters', () => {
    const longName = 'a'.repeat(60);
    expect(safeProjectName(longName)).toHaveLength(48);
  });

  test('returns iphone-dev-check when result would be empty', () => {
    expect(safeProjectName('')).toBe('iphone-dev-check');
    expect(safeProjectName('   ')).toBe('iphone-dev-check');
    expect(safeProjectName('...')).toBe('iphone-dev-check');
    expect(safeProjectName('---')).toBe('iphone-dev-check');
  });

  test('preserves dots and underscores in the middle', () => {
    expect(safeProjectName('my.project_name')).toBe('my.project_name');
  });

  test('handles mixed disallowed characters with boundary dots', () => {
    // Leading/trailing dots stripped, interior disallowed chars become hyphens
    expect(safeProjectName('.hello world.')).toBe('hello-world');
  });

  test('48-character boundary: exactly 48 chars kept', () => {
    const name = 'abcdefghij'.repeat(4) + 'xyz789'; // 46 chars
    const padded = name + 'AB'; // 48 chars
    expect(safeProjectName(padded)).toBe(padded);
  });

  test('48-character boundary: 49th character is removed', () => {
    const name = 'a'.repeat(49);
    expect(safeProjectName(name)).toHaveLength(48);
  });
});

// ---------------------------------------------------------------------------
// 2. checkNumbering
// ---------------------------------------------------------------------------
describe('checkNumbering', () => {
  test('returns ok=false with detail message when no numbered headings found', () => {
    const result = checkNumbering('# No numbered headings here\nSome text');
    expect(result.ok).toBe(false);
    expect(result.label).toBe('Top-Level-Nummerierung gefunden');
    expect(result.detail).toBe('Keine nummerierten Abschnitte gefunden.');
  });

  test('returns ok=true for a single heading numbered 1', () => {
    const result = checkNumbering('## 1. Introduction\nSome text');
    expect(result.ok).toBe(true);
    expect(result.label).toBe('Durchgehende Top-Level-Nummerierung');
    expect(result.detail).toBe('1 Abschnitte geprüft.');
  });

  test('returns ok=true for contiguous 1..n sequence', () => {
    const text = '## 1. First\n## 2. Second\n## 3. Third\n';
    const result = checkNumbering(text);
    expect(result.ok).toBe(true);
    expect(result.detail).toBe('3 Abschnitte geprüft.');
  });

  test('returns ok=false when sequence starts at 2', () => {
    const text = '## 2. Section\n## 3. Section\n';
    const result = checkNumbering(text);
    expect(result.ok).toBe(false);
    expect(result.detail).toBe('Gefunden: 2, 3');
  });

  test('returns ok=false when there is a gap in the sequence', () => {
    const text = '## 1. First\n## 3. Third\n';
    const result = checkNumbering(text);
    expect(result.ok).toBe(false);
    expect(result.detail).toBe('Gefunden: 1, 3');
  });

  test('returns ok=false when numbers repeat', () => {
    const text = '## 1. First\n## 1. Also First\n## 2. Second\n';
    const result = checkNumbering(text);
    expect(result.ok).toBe(false);
    expect(result.detail).toBe('Gefunden: 1, 1, 2');
  });

  test('ignores headings not matching ## N. pattern', () => {
    const text = '# Main Heading\n### 3. Sub\n## 1. Top\n## 2. Top2\n';
    const result = checkNumbering(text);
    expect(result.ok).toBe(true);
    expect(result.detail).toBe('2 Abschnitte geprüft.');
  });

  test('only matches headings at the start of a line (multiline regex)', () => {
    // Inline "## 1. " within a paragraph should not count
    const text = 'Prefix text ## 1. Not a heading\n## 1. Real heading\n## 2. Second\n';
    const result = checkNumbering(text);
    expect(result.ok).toBe(true);
    expect(result.detail).toBe('2 Abschnitte geprüft.');
  });

  test('handles a long correct sequence (1..20)', () => {
    const lines = Array.from({ length: 20 }, (_, i) => `## ${i + 1}. Section ${i + 1}`).join('\n');
    const result = checkNumbering(lines);
    expect(result.ok).toBe(true);
    expect(result.detail).toBe('20 Abschnitte geprüft.');
  });
});

// ---------------------------------------------------------------------------
// 3. requiredElement (DOM-dependent, tested via module load)
// ---------------------------------------------------------------------------
describe('requiredElement', () => {
  beforeEach(() => {
    buildScaffold();
  });

  test('finds an element that exists', () => {
    const el = document.querySelector('#planOutput');
    expect(el).not.toBeNull();
  });

  test('module load throws when a required element is missing', () => {
    // Remove a required element and try to load the module
    document.getElementById('qaResults').remove();
    expect(() => {
      jest.isolateModules(() => {
        require('../app.js');
      });
    }).toThrow('Required element missing: #qaResults');
  });

  test('module load throws with correct selector name in message', () => {
    document.getElementById('scriptOutput').remove();
    expect(() => {
      jest.isolateModules(() => {
        require('../app.js');
      });
    }).toThrow('Required element missing: #scriptOutput');
  });
});

// ---------------------------------------------------------------------------
// 4. setProfile (via module load with full DOM)
// ---------------------------------------------------------------------------
describe('setProfile', () => {
  beforeEach(() => {
    buildScaffold();
    // Mock fetch so runQa() called at load time doesn't reject
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('## 1. Section\n## 2. Section\n')
    });
    jest.isolateModules(() => {
      require('../app.js');
    });
  });

  test('setProfile minimal populates planOutput with 4 steps', () => {
    const items = document.querySelectorAll('#planOutput li');
    expect(items).toHaveLength(4);
  });

  test('setProfile minimal populates autonomyChecks with 3 checkboxes', () => {
    const labels = document.querySelectorAll('#autonomyChecks label');
    expect(labels).toHaveLength(3);
    labels.forEach((label) => {
      const checkbox = label.querySelector('input[type="checkbox"]');
      expect(checkbox).not.toBeNull();
      expect(checkbox.checked).toBe(true);
    });
  });

  test('setProfile marks the minimal button as active', () => {
    const minimalBtn = document.querySelector('[data-profile="minimal"]');
    const linuxBtn = document.querySelector('[data-profile="linux"]');
    expect(minimalBtn.classList.contains('active')).toBe(true);
    expect(minimalBtn.getAttribute('aria-pressed')).toBe('true');
    expect(linuxBtn.classList.contains('active')).toBe(false);
    expect(linuxBtn.getAttribute('aria-pressed')).toBe('false');
  });

  test('clicking linux profile button updates planOutput', () => {
    const linuxBtn = document.querySelector('[data-profile="linux"]');
    linuxBtn.click();
    const items = document.querySelectorAll('#planOutput li');
    expect(items).toHaveLength(4);
    expect(items[0].textContent).toMatch(/iSH/);
  });

  test('clicking hybrid profile button updates planOutput', () => {
    const hybridBtn = document.querySelector('[data-profile="hybrid"]');
    hybridBtn.click();
    const items = document.querySelectorAll('#planOutput li');
    expect(items).toHaveLength(4);
    expect(items[0].textContent).toMatch(/Editor/);
  });

  test('switching profiles updates aria-pressed on all buttons', () => {
    const linuxBtn = document.querySelector('[data-profile="linux"]');
    linuxBtn.click();
    expect(linuxBtn.getAttribute('aria-pressed')).toBe('true');
    const minimalBtn = document.querySelector('[data-profile="minimal"]');
    expect(minimalBtn.getAttribute('aria-pressed')).toBe('false');
    const hybridBtn = document.querySelector('[data-profile="hybrid"]');
    expect(hybridBtn.getAttribute('aria-pressed')).toBe('false');
  });

  test('unknown profile name falls back to minimal', () => {
    // Simulate an unknown profile button click by overriding dataset
    const btn = document.querySelector('[data-profile="minimal"]');
    // Temporarily change dataset to unknown
    const originalProfile = btn.dataset.profile;
    btn.dataset.profile = 'nonexistent';
    btn.click();
    // Should fall back to minimal steps
    const items = document.querySelectorAll('#planOutput li');
    expect(items).toHaveLength(4);
    expect(items[0].textContent).toMatch(/Working Copy/);
    btn.dataset.profile = originalProfile;
  });
});

// ---------------------------------------------------------------------------
// 5. renderScript (via module load with full DOM)
// ---------------------------------------------------------------------------
describe('renderScript', () => {
  beforeEach(() => {
    buildScaffold();
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('## 1. Section\n## 2. Section\n')
    });
    jest.isolateModules(() => {
      require('../app.js');
    });
  });

  test('scriptOutput is populated after load with minimal profile', () => {
    const output = document.getElementById('scriptOutput').textContent;
    expect(output).toContain('set -eu');
    expect(output).toContain('umask 077');
    expect(output).toContain('PROJECT="iphone-dev-check"');
  });

  test('script contains mkdir for scratch directory', () => {
    const output = document.getElementById('scriptOutput').textContent;
    expect(output).toContain('mkdir -p "$HOME/Developer/scratch/$PROJECT"');
  });

  test('script contains hello.py with expected print', () => {
    const output = document.getElementById('scriptOutput').textContent;
    expect(output).toContain('print("iPhone Direct-Inject OK")');
  });

  test('minimal profile script contains minimal-specific message', () => {
    const output = document.getElementById('scriptOutput').textContent;
    expect(output).toContain('Minimalprofil bereit');
  });

  test('linux profile script contains linux-specific message', () => {
    const linuxBtn = document.querySelector('[data-profile="linux"]');
    linuxBtn.click();
    const output = document.getElementById('scriptOutput').textContent;
    expect(output).toContain('apk update');
  });

  test('hybrid profile script contains remote-checklist content', () => {
    const hybridBtn = document.querySelector('[data-profile="hybrid"]');
    hybridBtn.click();
    const output = document.getElementById('scriptOutput').textContent;
    expect(output).toContain('remote-checklist.txt');
    expect(output).toContain('Hybridprofil bereit');
  });

  test('changing projectName input updates the script', () => {
    const input = document.getElementById('projectName');
    input.value = 'my-test-app';
    input.dispatchEvent(new Event('input'));
    const output = document.getElementById('scriptOutput').textContent;
    expect(output).toContain('PROJECT="my-test-app"');
  });

  test('projectName value is sanitized in the script output', () => {
    const input = document.getElementById('projectName');
    input.value = 'my test app!';
    input.dispatchEvent(new Event('input'));
    const output = document.getElementById('scriptOutput').textContent;
    expect(output).toContain('PROJECT="my-test-app"');
    // The input itself should also be updated to the sanitized value
    expect(input.value).toBe('my-test-app');
  });

  test('empty projectName falls back to iphone-dev-check in script', () => {
    const input = document.getElementById('projectName');
    input.value = '';
    input.dispatchEvent(new Event('input'));
    const output = document.getElementById('scriptOutput').textContent;
    expect(output).toContain('PROJECT="iphone-dev-check"');
  });
});

// ---------------------------------------------------------------------------
// 6. copyScript (via module load with full DOM + clipboard mock)
// ---------------------------------------------------------------------------
describe('copyScript', () => {
  beforeEach(() => {
    buildScaffold();
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('## 1. Section\n')
    });
    jest.isolateModules(() => {
      require('../app.js');
    });
  });

  test('sets copyStatus to success message when clipboard write succeeds', async () => {
    const writeTextMock = jest.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock },
      writable: true,
      configurable: true
    });

    const btn = document.getElementById('copyScript');
    btn.click();

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById('copyStatus').textContent).toBe('Skript wurde kopiert.');
  });

  test('sets copyStatus to failure message when clipboard write fails', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: jest.fn().mockRejectedValue(new Error('denied')) },
      writable: true,
      configurable: true
    });

    const btn = document.getElementById('copyScript');
    btn.click();

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById('copyStatus').textContent).toBe(
      'Kopieren nicht möglich. Bitte Skript manuell markieren.'
    );
  });

  test('clipboard.writeText is called with the current script content', async () => {
    const writeTextMock = jest.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock },
      writable: true,
      configurable: true
    });

    const scriptContent = document.getElementById('scriptOutput').textContent;
    const btn = document.getElementById('copyScript');
    btn.click();

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(writeTextMock).toHaveBeenCalledWith(scriptContent);
  });
});

// ---------------------------------------------------------------------------
// 7. loadGuideText (via module load + fetch mock)
// ---------------------------------------------------------------------------
describe('loadGuideText', () => {
  beforeEach(() => {
    buildScaffold();
  });

  test('returns fetched text when fetch succeeds', async () => {
    const guideContent = '## 1. Section\n## 2. Section\n';
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(guideContent)
    });

    jest.isolateModules(() => {
      require('../app.js');
    });

    // Wait for runQa to complete (it calls loadGuideText internally)
    await new Promise((resolve) => setTimeout(resolve, 10));

    // If fetch succeeded, the qa results should reflect the guide content
    const results = document.querySelectorAll('#qaResults li');
    expect(results.length).toBeGreaterThan(0);
    expect(global.fetch).toHaveBeenCalledWith('docs/iphone-local-dev-setup.md', { cache: 'no-cache' });
  });

  test('falls back to document.body.innerText when fetch fails', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('network error'));

    jest.isolateModules(() => {
      require('../app.js');
    });

    await new Promise((resolve) => setTimeout(resolve, 10));

    // Should still render QA results (using body.innerText as fallback)
    const results = document.querySelectorAll('#qaResults li');
    expect(results.length).toBeGreaterThan(0);
  });

  test('falls back to document.body.innerText when response is not ok', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      text: () => Promise.resolve('')
    });

    jest.isolateModules(() => {
      require('../app.js');
    });

    await new Promise((resolve) => setTimeout(resolve, 10));

    const results = document.querySelectorAll('#qaResults li');
    expect(results.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// 8. checkNumbering (edge cases)
// ---------------------------------------------------------------------------
describe('checkNumbering edge cases', () => {
  test('returns correct label text based on pass/fail', () => {
    const passing = checkNumbering('## 1. A\n## 2. B\n');
    expect(passing.label).toBe('Durchgehende Top-Level-Nummerierung');

    const failing = checkNumbering('## 2. B\n## 3. C\n');
    expect(failing.label).toBe('Durchgehende Top-Level-Nummerierung');

    const empty = checkNumbering('No headings');
    expect(empty.label).toBe('Top-Level-Nummerierung gefunden');
  });

  test('handles empty string input', () => {
    const result = checkNumbering('');
    expect(result.ok).toBe(false);
    expect(result.detail).toBe('Keine nummerierten Abschnitte gefunden.');
  });

  test('treats large non-contiguous numbers as failure', () => {
    const text = '## 1. First\n## 5. Fifth\n## 10. Tenth\n';
    const result = checkNumbering(text);
    expect(result.ok).toBe(false);
    expect(result.detail).toBe('Gefunden: 1, 5, 10');
  });
});

// ---------------------------------------------------------------------------
// 9. resultItem (DOM element creation)
// ---------------------------------------------------------------------------
describe('resultItem', () => {
  // Redefine resultItem locally for isolated testing
  function resultItem({ label, ok, detail, level = 'ok' }) {
    const li = document.createElement('li');
    const dot = document.createElement('span');
    dot.className = `dot ${ok ? 'ok' : level}`;
    li.append(dot, `${label}: ${ok ? 'OK' : 'Prüfen'} — ${detail}`);
    return li;
  }

  test('returns an li element', () => {
    const li = resultItem({ label: 'Test', ok: true, detail: 'All good' });
    expect(li.tagName).toBe('LI');
  });

  test('dot has class "dot ok" when ok=true', () => {
    const li = resultItem({ label: 'Test', ok: true, detail: 'Fine' });
    const dot = li.querySelector('span');
    expect(dot.className).toBe('dot ok');
  });

  test('dot uses level class when ok=false', () => {
    const li = resultItem({ label: 'Test', ok: false, detail: 'Problem', level: 'warn' });
    const dot = li.querySelector('span');
    expect(dot.className).toBe('dot warn');
  });

  test('dot uses "bad" level class when specified', () => {
    const li = resultItem({ label: 'Risky', ok: false, detail: 'Danger', level: 'bad' });
    const dot = li.querySelector('span');
    expect(dot.className).toBe('dot bad');
  });

  test('dot defaults to "ok" level class when level is not provided and ok=false', () => {
    const li = resultItem({ label: 'Test', ok: false, detail: 'Something' });
    const dot = li.querySelector('span');
    expect(dot.className).toBe('dot ok');
  });

  test('text content includes "OK" when ok=true', () => {
    const li = resultItem({ label: 'Check', ok: true, detail: 'Passed' });
    expect(li.textContent).toContain('OK');
    expect(li.textContent).not.toContain('Prüfen');
  });

  test('text content includes "Prüfen" when ok=false', () => {
    const li = resultItem({ label: 'Check', ok: false, detail: 'Failed', level: 'warn' });
    expect(li.textContent).toContain('Prüfen');
    expect(li.textContent).not.toContain(': OK');
  });

  test('text content includes label, status, and detail', () => {
    const li = resultItem({ label: 'My Check', ok: true, detail: 'Everything fine' });
    expect(li.textContent).toContain('My Check');
    expect(li.textContent).toContain('OK');
    expect(li.textContent).toContain('Everything fine');
  });

  test('separator em-dash is included in text content', () => {
    const li = resultItem({ label: 'Check', ok: true, detail: 'Detail text' });
    expect(li.textContent).toContain('—');
  });
});

// ---------------------------------------------------------------------------
// 10. runQa (integration via module load)
// ---------------------------------------------------------------------------
describe('runQa', () => {
  beforeEach(() => {
    buildScaffold();
  });

  test('renders 6 result items (5 risky patterns + numbering check)', async () => {
    const cleanGuide = Array.from({ length: 5 }, (_, i) => `## ${i + 1}. Section ${i + 1}`).join('\n');
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(cleanGuide)
    });

    jest.isolateModules(() => {
      require('../app.js');
    });

    await new Promise((resolve) => setTimeout(resolve, 20));

    const items = document.querySelectorAll('#qaResults li');
    expect(items).toHaveLength(6);
  });

  test('risky pattern match sets Prüfen in result', async () => {
    // 'curl ... | sh' should trigger the bad remote execution pattern
    const riskyText = '## 1. Section\ncurl http://example.com/install.sh | sh\n';
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(riskyText)
    });

    jest.isolateModules(() => {
      require('../app.js');
    });

    await new Promise((resolve) => setTimeout(resolve, 20));

    const items = Array.from(document.querySelectorAll('#qaResults li'));
    const blindRunItem = items.find((li) => li.textContent.includes('Blinde Remote-Ausführung'));
    expect(blindRunItem).toBeDefined();
    expect(blindRunItem.textContent).toContain('Prüfen');
  });

  test('clean guide passes all risky pattern checks', async () => {
    const cleanText = Array.from({ length: 3 }, (_, i) => `## ${i + 1}. Clean Section`).join('\n');
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(cleanText)
    });

    jest.isolateModules(() => {
      require('../app.js');
    });

    await new Promise((resolve) => setTimeout(resolve, 20));

    const items = Array.from(document.querySelectorAll('#qaResults li'));
    // The first 5 results are risky pattern checks; all should say OK
    const riskyItems = items.slice(0, 5);
    riskyItems.forEach((li) => {
      expect(li.textContent).toContain('OK');
    });
  });

  test('TODO in guide text triggers TODO/FIXME pattern check', async () => {
    const textWithTodo = '## 1. Section\nTODO: fix this\n## 2. Section\n';
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(textWithTodo)
    });

    jest.isolateModules(() => {
      require('../app.js');
    });

    await new Promise((resolve) => setTimeout(resolve, 20));

    const items = Array.from(document.querySelectorAll('#qaResults li'));
    const todoItem = items.find((li) => li.textContent.includes('TODO/FIXME'));
    expect(todoItem).toBeDefined();
    expect(todoItem.textContent).toContain('Prüfen');
  });

  test('broken numbering is reflected in the numbering check result', async () => {
    const brokenText = '## 1. First\n## 3. Third\n'; // missing 2
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(brokenText)
    });

    jest.isolateModules(() => {
      require('../app.js');
    });

    await new Promise((resolve) => setTimeout(resolve, 20));

    const items = Array.from(document.querySelectorAll('#qaResults li'));
    const numberingItem = items[items.length - 1]; // last item is numbering check
    expect(numberingItem.textContent).toContain('Prüfen');
    expect(numberingItem.textContent).toContain('Gefunden: 1, 3');
  });
});
