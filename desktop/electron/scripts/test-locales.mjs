import assert from "node:assert/strict";

import {
  getDesktopMessages,
  getRendererLocale,
  resolveDesktopLocale,
  supportedDesktopLocales,
} from "../dist/locales.js";

const english = getDesktopMessages("en");
const expectedKeys = Object.keys(english).sort();

assert.deepEqual(supportedDesktopLocales, ["en", "zh-CN", "ja", "ko", "ar"]);
for (const locale of supportedDesktopLocales) {
  const localeMessages = getDesktopMessages(locale);
  assert.deepEqual(Object.keys(localeMessages).sort(), expectedKeys, `${locale} message keys differ`);
  for (const key of expectedKeys) {
    assert.equal(typeof localeMessages[key], "string", `${locale}.${key} is not a string`);
    assert.notEqual(localeMessages[key].trim(), "", `${locale}.${key} is empty`);
    assert.deepEqual(
      placeholders(localeMessages[key]),
      placeholders(english[key]),
      `${locale}.${key} placeholders differ from English`,
    );
  }
}

assert.equal(resolveDesktopLocale(undefined), "en");
assert.equal(resolveDesktopLocale("fr-FR"), "en");
assert.equal(resolveDesktopLocale("zh-Hans-CN"), "zh-CN");
assert.equal(resolveDesktopLocale("ja-JP"), "ja");
assert.equal(resolveDesktopLocale("ko_KR"), "ko");
assert.equal(resolveDesktopLocale("ar-SA"), "ar");
assert.equal(getRendererLocale("en").direction, "ltr");
assert.equal(getRendererLocale("ar").direction, "rtl");

console.log(JSON.stringify({
  locales: supportedDesktopLocales,
  messageKeys: expectedKeys.length,
  rtlLocale: "ar",
  parityVerified: true,
}, null, 2));

function placeholders(value) {
  return [...value.matchAll(/\{([a-zA-Z0-9_]+)\}/gu)].map((match) => match[1]).sort();
}
