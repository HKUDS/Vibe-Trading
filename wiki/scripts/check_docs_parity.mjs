// Fails when the English and Chinese docs drift apart: every group, page and
// section id must exist in both languages, in the same order, with no empty
// titles or bodies. Run: node wiki/scripts/check_docs_parity.mjs
import { DOCS_STRUCTURE as en } from "../docs/content.en.js";
import { DOCS_STRUCTURE as zh } from "../docs/content.zh.js";

const outline = (structure) =>
  structure.flatMap((group) => [
    `group ${group.id}`,
    ...group.pages.flatMap((page) => [
      `page ${page.id}`,
      ...page.sections.map((section) => `section ${page.id}#${section.id}`)
    ])
  ]);

const problems = [];
const [left, right] = [outline(en), outline(zh)];
for (let i = 0; i < Math.max(left.length, right.length); i += 1) {
  if (left[i] !== right[i]) problems.push(`position ${i}: en has "${left[i]}", zh has "${right[i]}"`);
}

for (const [lang, structure] of [["en", en], ["zh", zh]]) {
  for (const group of structure) {
    if (!group.label?.trim()) problems.push(`${lang}: group ${group.id} has no label`);
    for (const page of group.pages) {
      for (const field of ["title", "description", "lead"]) {
        if (!page[field]?.trim()) problems.push(`${lang}: ${page.id} has no ${field}`);
      }
      const ids = new Set();
      for (const section of page.sections) {
        if (ids.has(section.id)) problems.push(`${lang}: ${page.id} repeats section ${section.id}`);
        ids.add(section.id);
        if (!section.title?.trim() || !section.body?.trim()) {
          problems.push(`${lang}: ${page.id}#${section.id} is empty`);
        }
      }
      for (const [, target] of JSON.stringify(page).matchAll(/data-doc-link=\\"([^"\\]+)\\"/g)) {
        if (!left.includes(`page ${target}`)) problems.push(`${lang}: ${page.id} links to missing page ${target}`);
      }
    }
  }
}

if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log(`docs parity ok: ${left.filter((line) => line.startsWith("page ")).length} pages, ${left.length} entries in both languages`);
