// content.js -- the collector.
//
//   1. injects interceptor.js into the page
//   2. normalizes each saved post the interceptor captures
//   3. streams it to the local bridge, deduped
//   4. scrolls the saved feed at a human cadence so the page paginates naturally
//   5. draws a small HUD and answers the popup
//
// It stops by itself: at the end of the feed, at your max, or as soon as it
// scrolls back into posts you already have.

(function () {
  if (window.__SB_CONTENT__) return;
  window.__SB_CONTENT__ = true;

  const DEFAULTS = {
    port: 8799,
    maxPosts: 400,
    scrollMin: 2200,      // per-scroll dwell, ms
    scrollMax: 5200,
    breakEvery: 8,        // take a longer break every N scrolls
    breakMin: 18000,
    breakMax: 55000,
    idleStop: 6,          // stop after N scrolls with nothing new
    caughtUpStop: 5,      // stop after N already-known posts in a row (0 = never)
  };

  let settings = { ...DEFAULTS };
  let running = false;
  let total = 0;
  const seen = new Set();
  let knownSet = new Set();
  let firstRun = true;
  let consecutiveKnown = 0;
  let bridgeOk = null;
  let autoMode = false;

  function injectInterceptor() {
    if (document.getElementById("sb-interceptor")) return;
    const s = document.createElement("script");
    s.id = "sb-interceptor";
    s.src = chrome.runtime.getURL("interceptor.js");
    (document.head || document.documentElement).appendChild(s);
    s.onload = () => s.remove();
  }

  // ---------- normalize one media object ----------
  function bestImage(media) {
    const c = media.image_versions2 && media.image_versions2.candidates;
    return c && c.length ? c[0].url : null;   // candidates[0] = highest resolution
  }

  function parseMedia(media) {
    if (!media || !media.code) return null;
    const type = media.media_type;             // 1 image, 2 video, 8 carousel
    const isVideo = type === 2;
    const isCarousel = type === 8;

    const imageUrls = [];
    let videoUrl = null;

    if (isCarousel && Array.isArray(media.carousel_media)) {
      for (const child of media.carousel_media) {
        if (child.media_type === 1) {          // still slides only; video children are skipped
          const u = bestImage(child);
          if (u) imageUrls.push(u);
        }
      }
    } else if (isVideo) {
      if (media.video_versions && media.video_versions.length) {
        videoUrl = media.video_versions[0].url;
      }
    } else {
      const u = bestImage(media);
      if (u) imageUrls.push(u);
    }

    return {
      shortcode: media.code,
      url: "https://www.instagram.com/p/" + media.code + "/",
      author: (media.user && media.user.username) || "",
      date: media.taken_at ? new Date(media.taken_at * 1000).toISOString() : "",
      is_video: !!isVideo,
      is_carousel: !!isCarousel,
      caption: (media.caption && media.caption.text) || "",
      image_urls: imageUrls,
      video_url: videoUrl,
      collection: collectionName(),
    };
  }

  function collectionName() {
    const m = location.pathname.match(/\/saved\/([^/]+)/);
    if (!m || m[1] === "all-posts") return "main";
    return decodeURIComponent(m[1]);
  }

  // Walk any captured JSON for media objects, so a change in Instagram's
  // response shape does not break collection.
  function findMedia(node, out, depth) {
    if (!node || depth > 6) return;
    if (Array.isArray(node)) {
      for (const v of node) findMedia(v, out, depth + 1);
      return;
    }
    if (typeof node === "object") {
      if (node.code && (node.image_versions2 || node.carousel_media || node.video_versions || node.caption !== undefined)) {
        out.push(node);
      }
      for (const k in node) {
        const v = node[k];
        if (v && typeof v === "object") findMedia(v, out, depth + 1);
      }
    }
  }

  async function streamPost(post) {
    try {
      const res = await fetch("http://127.0.0.1:" + settings.port + "/post", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(post),
      });
      bridgeOk = res.ok;
      return res.ok;
    } catch (e) {
      bridgeOk = false;
      return false;
    }
  }

  async function reportDone(extra) {
    try {
      await fetch("http://127.0.0.1:" + settings.port + "/done", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ total, ...extra }),
      });
    } catch (_) {}
  }

  async function fetchKnown() {
    try {
      const r = await fetch("http://127.0.0.1:" + settings.port + "/known");
      const j = await r.json();
      bridgeOk = true;
      return new Set(j.shortcodes || []);
    } catch (_) {
      bridgeOk = false;
      return new Set();
    }
  }

  function handleCapture(json) {
    const found = [];
    findMedia(json, found, 0);
    for (const media of found) {
      const post = parseMedia(media);
      if (!post || seen.has(post.shortcode)) continue;
      seen.add(post.shortcode);

      if (!firstRun && knownSet.has(post.shortcode)) {
        consecutiveKnown++;
        if (settings.caughtUpStop > 0 && consecutiveKnown >= settings.caughtUpStop) {
          running = false;
          hud("caught up (" + consecutiveKnown + " known in a row)");
        }
        continue;
      }

      consecutiveKnown = 0;
      total++;
      streamPost(post);
      hud();
    }
  }

  window.addEventListener("message", (ev) => {
    if (ev.source !== window) return;
    const d = ev.data;
    if (!d || d.source !== "SB") return;
    if (d.kind === "capture") handleCapture(d.body);
  });

  // ---------- HUD ----------
  let hudEl = null;
  function hud(note) {
    if (!hudEl) {
      hudEl = document.createElement("div");
      hudEl.id = "sb-hud";
      Object.assign(hudEl.style, {
        position: "fixed", zIndex: 999999, bottom: "16px", right: "16px",
        background: "rgba(17,17,20,0.92)", color: "#e6e6e6", font: "12px/1.4 monospace",
        padding: "10px 12px", borderRadius: "10px", border: "1px solid #333",
        boxShadow: "0 6px 24px rgba(0,0,0,.4)", maxWidth: "250px", pointerEvents: "none",
      });
      document.body.appendChild(hudEl);
    }
    const dot = bridgeOk === null ? "..." : bridgeOk ? "connected" : "OFFLINE";
    hudEl.innerHTML =
      "<b>SaveBrain</b> " + (running ? "collecting" : "idle") + "<br>" +
      "posts: <b>" + total + "</b> &nbsp; bridge: " + dot + "<br>" +
      (note ? '<span style="color:#9aa">' + note + "</span>" : "");
  }

  // ---------- humanoid scroll loop ----------
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const rand = (a, b) => a + Math.random() * (b - a);

  async function run() {
    running = true;
    consecutiveKnown = 0;

    if (/\/accounts\/login/.test(location.pathname)) {
      running = false;
      hud("not logged in -- log in and try again");
      await reportDone({ caught_up: false, logged_out: true });
      chrome.runtime.sendMessage({ type: "SB_DONE", total: 0, auto: autoMode }).catch(() => {});
      return;
    }

    injectInterceptor();
    hud("checking what you already have...");
    knownSet = await fetchKnown();
    firstRun = knownSet.size === 0;
    hud(firstRun ? "first run -- full collection"
                 : knownSet.size + " already saved; will stop on overlap");
    await sleep(rand(1500, 3500));

    let idle = 0, scrolls = 0, last = -1;
    while (running && idle < settings.idleStop && total < settings.maxPosts) {
      const vh = window.innerHeight;
      window.scrollBy(0, vh * rand(0.6, 0.95));
      scrolls++;
      await sleep(rand(settings.scrollMin, settings.scrollMax));

      if (Math.random() < 0.15) {                       // occasional re-read
        window.scrollBy(0, -vh * rand(0.1, 0.3));
        hud("re-reading...");
        await sleep(rand(900, 2400));
      }

      if (settings.breakEvery > 0 && scrolls % settings.breakEvery === 0) {
        hud("break");
        await sleep(rand(settings.breakMin, settings.breakMax));
      }

      if (total === last) idle++;
      else { idle = 0; last = total; }
      hud(idle > 0 ? "idle " + idle + "/" + settings.idleStop : "");
    }

    const caughtUp = !firstRun && settings.caughtUpStop > 0 &&
                     consecutiveKnown >= settings.caughtUpStop;
    running = false;
    hud(caughtUp ? "caught up -- " + total + " new"
                 : (total >= settings.maxPosts ? "hit max -- " + total + " new"
                                               : "reached the end -- " + total + " new"));
    await reportDone({ caught_up: caughtUp, logged_out: false });
    chrome.runtime.sendMessage({ type: "SB_DONE", total, auto: autoMode }).catch(() => {});
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === "SB_START") {
      settings = { ...DEFAULTS, ...(msg.settings || {}) };
      if (!running) run();
      sendResponse({ ok: true });
    } else if (msg.type === "SB_STOP") {
      running = false;
      hud("stopped");
      sendResponse({ ok: true });
    } else if (msg.type === "SB_STATUS") {
      sendResponse({ running, total, bridgeOk });
    }
    return true;
  });

  chrome.storage.local.get("sb_settings").then((r) => {
    if (r && r.sb_settings) settings = { ...DEFAULTS, ...r.sb_settings };
    maybeAutoStart();
  });

  // Unattended entry point: a scheduled run opens the saved page with #sb-auto.
  // Instagram's SPA can strip the fragment after this script injects, so we
  // re-check for ~20s and on hashchange instead of testing once.
  let autoAttempts = 0;

  function tryAutoStart() {
    if (running || autoMode) return true;
    if (!(location.hash.includes("sb-auto") || location.href.includes("sb-auto"))) return false;
    autoMode = true;
    fetch("http://127.0.0.1:" + settings.port + "/started", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto: true }),
    }).catch(() => {});
    setTimeout(run, 2500);
    return true;
  }

  function maybeAutoStart() {
    if (autoMode || running) return;
    if (tryAutoStart()) return;
    if (autoAttempts >= 8) return;
    autoAttempts++;
    setTimeout(maybeAutoStart, 2500);
  }
  window.addEventListener("hashchange", maybeAutoStart);
  window.addEventListener("pageshow", maybeAutoStart);
})();
