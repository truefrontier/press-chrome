/**
 * Press Chrome — content script (readability extract).
 * Patterns copied from Walkie Reader; Jev optional later (not required for v1).
 */

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "ping") {
    sendResponse({ ok: true });
    return false;
  }
  if (message?.type === "extract") {
    try {
      const text = readabilityExtract(document);
      sendResponse({
        ok: Boolean(text.trim()),
        text: text.trim(),
        method: text.trim() ? "readability" : "none",
      });
    } catch (err) {
      sendResponse({ ok: false, error: String(err?.message || err) });
    }
    return false;
  }
  return false;
});

function readabilityExtract(doc) {
  const prefer =
    doc.querySelector("article") ||
    doc.querySelector("main") ||
    doc.querySelector("[role='main']");
  if (prefer) {
    const clone = prefer.cloneNode(true);
    stripChrome(clone);
    const t = plaintext(clone);
    if (t.length >= 80) return t;
  }

  let best = null;
  let bestLen = 0;
  for (const el of doc.querySelectorAll("article, main, section, div")) {
    if (el.closest("nav,header,footer,aside,[role='navigation']")) continue;
    const clone = el.cloneNode(true);
    stripChrome(clone);
    const t = plaintext(clone);
    if (t.length > bestLen) {
      bestLen = t.length;
      best = el;
    }
  }
  if (best && bestLen >= 80) {
    const clone = best.cloneNode(true);
    stripChrome(clone);
    return plaintext(clone);
  }
  const body = doc.body?.cloneNode(true);
  if (!body) return "";
  stripChrome(body);
  body.querySelectorAll("nav,header,footer,aside").forEach((n) => n.remove());
  return plaintext(body);
}

function stripChrome(root) {
  root
    .querySelectorAll(
      "script,style,noscript,svg,iframe,nav,header,footer,aside,form,button,[role='navigation'],[role='banner'],[role='contentinfo']",
    )
    .forEach((n) => n.remove());
}

function plaintext(el) {
  return (el.textContent || "").replace(/\s+/g, " ").trim();
}
