// Supported note languages — frontend mirror of backend/core/languages.py.
// Keep these in sync. "en" is the default and must stay first.

export const DEFAULT_LANGUAGE = 'en';

export const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'English', nativeLabel: 'English' },
  { code: 'es', label: 'Spanish', nativeLabel: 'Español' },
  { code: 'fr', label: 'French', nativeLabel: 'Français' },
  { code: 'de', label: 'German', nativeLabel: 'Deutsch' },
  { code: 'pt', label: 'Portuguese', nativeLabel: 'Português' },
  { code: 'it', label: 'Italian', nativeLabel: 'Italiano' },
  { code: 'nl', label: 'Dutch', nativeLabel: 'Nederlands' },
  { code: 'pl', label: 'Polish', nativeLabel: 'Polski' },
  { code: 'ro', label: 'Romanian', nativeLabel: 'Română' },
  { code: 'sv', label: 'Swedish', nativeLabel: 'Svenska' },
  { code: 'tr', label: 'Turkish', nativeLabel: 'Türkçe' },
  { code: 'id', label: 'Indonesian', nativeLabel: 'Bahasa Indonesia' },
  { code: 'hi', label: 'Hindi', nativeLabel: 'हिन्दी' },
];

const BY_CODE = Object.fromEntries(SUPPORTED_LANGUAGES.map((l) => [l.code, l]));

export function normalizeLanguage(code) {
  const raw = (code || '').trim().toLowerCase();
  if (!raw) return DEFAULT_LANGUAGE;
  if (BY_CODE[raw]) return raw;
  const base = raw.split('-')[0];
  return BY_CODE[base] ? base : DEFAULT_LANGUAGE;
}

export function languageChoices() {
  return SUPPORTED_LANGUAGES;
}
