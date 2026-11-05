// Shared by the static generator and the client router so their claims agree.
export const DOCS_SITE = "https://vibetrading.wiki";

export function buildDocMetadata(page, language) {
  const description = page.description || String(page.lead).replace(/<[^>]+>/g, "").trim();
  const canonical = `${DOCS_SITE}/docs/${language.segment}/${page.id}`;
  return {
    title: `${page.title} - ${language.siteTitle}`,
    description,
    canonical,
    structuredData: {
      "@context": "https://schema.org",
      "@type": "TechArticle",
      headline: page.title,
      description,
      inLanguage: language.htmlLang,
      url: canonical,
      mainEntityOfPage: { "@type": "WebPage", "@id": canonical },
      isPartOf: { "@type": "WebSite", name: "Vibe-Trading Wiki", url: `${DOCS_SITE}/home/` },
      publisher: { "@type": "Organization", name: "Vibe-Trading", url: "https://github.com/HKUDS/Vibe-Trading" },
    },
  };
}

export function serializeStructuredData(data) {
  // A literal closing script tag must not end the static JSON-LD element.
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
