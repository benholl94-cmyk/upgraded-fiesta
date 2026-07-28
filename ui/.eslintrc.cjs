// ui/.eslintrc.cjs — ESLint-Konfiguration.
//
// HINWEIS: ESLint laeuft nur, wenn `@typescript-eslint/parser` und
// `@typescript-eslint/eslint-plugin` installiert sind. Wer den Lint
// erzwingen will, fuehrt vorher einmalig aus:
//   cd ui && npm install --save-dev eslint @typescript-eslint/parser @typescript-eslint/eslint-plugin
//
// CI laeuft ESLint NUR, wenn `npm ls @typescript-eslint/parser` exit 0.
// Andernfalls wird uebersprungen (graceful degradation), damit das
// Build-System nicht durch eine optionale Toolchain blockiert wird.

module.exports = {
  root: true,
  parser: "@typescript-eslint/parser",
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: "module",
    project: "./tsconfig.json",
  },
  plugins: ["@typescript-eslint"],
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
  ],
  rules: {
    // Konservative Defaults; jeder Override hier ist eine bewusste Wahl.
    "@typescript-eslint/no-unused-vars": ["warn", {
      argsIgnorePattern: "^_",
      varsIgnorePattern: "^_",
    }],
    "@typescript-eslint/no-explicit-any": "warn",
  },
  ignorePatterns: [
    "dist/",
    "node_modules/",
    "*.cjs",
  ],
};