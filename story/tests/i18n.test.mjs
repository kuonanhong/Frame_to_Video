import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {languages, selectLanguage, t, translationCoverage, translationKeys} from '../i18n.mjs';
import {VISUAL_STRINGS} from '../visual-tools.mjs';
import {advancedKeys, advancedMessages, advancedText} from '../advanced-i18n.mjs';

test('30 locales contain explicit translations for every authored UI key', () => {
  assert.equal(languages.length, 30);
  assert.equal(new Set(languages.map(item => item.code)).size, 30);
  assert.equal(translationKeys.length, 256);
  for (const report of translationCoverage()) {
    assert.equal(report.present, report.expected, report.code);
    assert.deepEqual(report.missing, [], report.code);
    for (const key of translationKeys) assert.ok(t(key, report.code).trim(), `${report.code}: ${key}`);
  }
});

test('all 30 locales explicitly translate the advanced model controls', () => {
  assert.equal(advancedKeys.length, 10);
  assert.equal(new Set(advancedKeys).size, advancedKeys.length);
  assert.deepEqual(Object.keys(advancedMessages).sort(), languages.map(item => item.code).sort());
  for (const {code} of languages) {
    const values = advancedMessages[code];
    assert.equal(values.length, advancedKeys.length, code);
    advancedKeys.forEach((key, index) => {
      assert.equal(typeof values[index], 'string', `${code}: ${key}`);
      assert.ok(values[index].trim(), `${code}: ${key}`);
      assert.equal(advancedText(key, code), values[index], `${code}: ${key}`);
    });
  }
});

test('Romanian and Hungarian use authored editor and visual-tool translations', () => {
  assert.equal(t('saveProject', 'ro-RO'), 'Salvează proiectul');
  assert.equal(t('saveProject', 'hu-HU'), 'Projekt mentése');
  assert.equal(t('vWater', 'ro-RO'), 'Ondulații pe apă');
  assert.equal(t('vWater', 'hu-HU'), 'Vízfodrok');
});

test('static editor labels and all visual-tool labels belong to the catalog', () => {
  const known = new Set(translationKeys);
  const html = fs.readFileSync(new URL('../../index.html', import.meta.url), 'utf8');
  for (const [, key] of html.matchAll(/data-i18n(?:-placeholder|-title|-aria-label)?=["']([^"']+)["']/g)) {
    assert.ok(known.has(key), `Unknown HTML translation key: ${key}`);
  }
  for (const key of Object.keys(VISUAL_STRINGS)) assert.ok(known.has(key), `Unknown visual-tool translation key: ${key}`);
});

test('browser region tags, script tags, aliases, and preference order', () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', {configurable:true, value:{getItem:()=>null}});
  try {
    const samples = {
      'zh-CN':'zh-Hans','zh-SG':'zh-Hans','zh-TW':'zh-Hant','zh-HK':'zh-Hant',
      'zh-MO':'zh-Hant','zh_Hans_TW':'zh-Hans','zh-Hant-CN':'zh-Hant',
      'pt-BR':'pt','en-US':'en','nb-NO':'no','no-NO':'no','tl-PH':'fil',
      'nl-BE':'nl','da-DK':'da','el-GR':'el','uk-UA':'uk','hi-IN':'hi','tr-TR':'tr','ro-RO':'ro','hu-HU':'hu'
    };
    for (const [tag, expected] of Object.entries(samples)) assert.equal(selectLanguage(tag), expected, tag);
    assert.equal(selectLanguage(['zz-ZZ', 'fr-CA', 'en-US']), 'fr');
    assert.equal(selectLanguage(['xx-YY']), 'en');
    assert.equal(languages.find(item=>item.code==='ar').dir, 'rtl');
  } finally { if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor); else delete globalThis.localStorage; }
});

test('saved manual choice wins, and unavailable storage never blocks selection', () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  try {
    Object.defineProperty(globalThis, 'localStorage', {configurable:true,value:{getItem:key=>key==='frame-story-language'?'uk':null}});
    assert.equal(selectLanguage(['en-US']), 'uk');
    Object.defineProperty(globalThis, 'localStorage', {configurable:true,get(){throw new Error('Storage denied');}});
    assert.equal(selectLanguage(['de-AT']), 'de');
    assert.equal(t('saveProject', 'zh-TW'), '儲存專案');
    assert.equal(t('brand', 'unknown'), 'FRAME Story Studio');
  } finally { if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor); else delete globalThis.localStorage; }
});
