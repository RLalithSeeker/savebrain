// interceptor.js -- runs in the PAGE's main world so it can see the JSON the
// Instagram web app itself receives. We never scrape the DOM (obfuscated class
// names change weekly) and we never call a private API: we read the responses
// the page already asked for, and hand them to the content script.
//
// Strictly read-only. Requests are never modified, nothing is ever posted,
// liked or followed on your behalf.

(function () {
  if (window.__SB_HOOKED__) return;
  window.__SB_HOOKED__ = true;

  function isInteresting(url) {
    if (typeof url !== "string") return false;
    return (
      /\/api\/v1\/feed\/(saved|collection)/.test(url) ||
      /\/api\/v1\/collections\//.test(url) ||
      url.includes("/graphql/query")
    );
  }

  function forward(url, text) {
    let json;
    try {
      json = JSON.parse(text);
    } catch (_) {
      return;
    }
    window.postMessage({ source: "SB", kind: "capture", url: url, body: json }, "*");
  }

  const _fetch = window.fetch;
  window.fetch = function (...args) {
    const p = _fetch.apply(this, args);
    try {
      const url = typeof args[0] === "string" ? args[0] : args[0] && args[0].url;
      if (isInteresting(url)) {
        p.then((res) => {
          try {
            res.clone().text().then((t) => forward(url, t)).catch(() => {});
          } catch (_) {}
        }).catch(() => {});
      }
    } catch (_) {}
    return p;
  };

  const _open = XMLHttpRequest.prototype.open;
  const _send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__sb_url = url;
    return _open.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...a) {
    this.addEventListener("load", function () {
      try {
        if (isInteresting(this.__sb_url) && this.responseType === "") {
          forward(this.__sb_url, this.responseText);
        }
      } catch (_) {}
    });
    return _send.apply(this, a);
  };

  window.postMessage({ source: "SB", kind: "hooked" }, "*");
})();
