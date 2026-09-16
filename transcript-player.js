/*
 * transcript-player.js -- synced media player for Medford Transcripts.
 *
 * PROGRESSIVE ENHANCEMENT, deliberately. Every transcript line keeps its
 * ordinary <a href="...&t=194"> link. Without JS (or for a crawler) the page
 * behaves exactly as it always has. With JS we intercept the click and seek a
 * player embedded on this same page instead of navigating away.
 *
 * Nothing about the document changes: same URL, same canonical, all transcript
 * text still in the DOM, so Ctrl+F, text selection and indexing are untouched.
 *
 * Three backends behind one tiny interface (seek / time / play):
 *   youtube  -- IFrame Player API
 *   audio    -- plain <audio> (Medford Bytes podcast enclosures)
 *   archive  -- archive.org embed
 *
 * Word-level highlighting: the page may ship a compact word-timing array as
 *   <script type="application/json" id="word-times">
 * We do NOT wrap every word in a <span> -- 40k spans bloats the page and
 * breaks Ctrl+F across element boundaries. Instead only the CURRENTLY PLAYING
 * line is split into word spans, on demand, and torn back down when it passes.
 */
(function () {
  "use strict";

  var mount = document.getElementById("mt-player");
  if (!mount) return;

  var KIND = mount.getAttribute("data-kind");      // youtube | audio | archive
  var SRC = mount.getAttribute("data-src");        // id or url
  var lines = Array.prototype.slice.call(
    document.querySelectorAll("p.line[data-t]")
  );
  var starts = lines.map(function (el) {
    return parseFloat(el.getAttribute("data-t")) || 0;
  });

  // Word timings live in a sidecar (<base>.words.json), fetched lazily on
  // first play. Keeping them out of the HTML keeps the page lean for crawlers
  // and Ctrl+F, and costs nothing for visitors who never press play.
  // Format: one array per line, delta-encoded centiseconds. The words are not
  // shipped -- they are already in the DOM.
  var wordTimes = null, wordsTried = false;

  function loadWordTimes() {
    if (wordsTried) return;
    wordsTried = true;
    var src = mount.getAttribute("data-words");
    if (!src) return;
    fetch(src).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (rows) {
        if (!rows) return;
        wordTimes = rows.map(function (row) {          // undo delta encoding
          var abs = [], acc = 0;
          for (var i = 0; i < row.length; i++) { acc += row[i]; abs.push(acc / 100); }
          return abs;
        });
      }).catch(function () { /* stay at line-level */ });
  }

  // ---------------------------------------------------------------- backends
  var backend = null;

  function makeAudio() {
    var el = document.createElement("audio");
    el.controls = true;
    el.preload = "metadata";
    el.src = SRC;
    el.style.width = "100%";
    mount.appendChild(el);
    return {
      el: el,
      seek: function (t) { el.currentTime = t; el.play().catch(function () {}); },
      time: function () { return el.currentTime; },
      rate: function (r) { el.playbackRate = r; },
      on: function (cb) { el.addEventListener("timeupdate", cb); },
      ready: function (cb) {
        if (el.readyState >= 1) cb();
        else el.addEventListener("loadedmetadata", cb, { once: true });
      }
    };
  }

  function makeYouTube() {
    var div = document.createElement("div");
    div.id = "mt-yt";
    div.className = "mt-video";
    mount.appendChild(div);

    var yt = null, poll = null, cbs = [];
    var api = {
      seek: function (t) { if (yt && yt.seekTo) { yt.seekTo(t, true); yt.playVideo(); } },
      time: function () { return yt && yt.getCurrentTime ? yt.getCurrentTime() : 0; },
      rate: function (r) { if (yt && yt.setPlaybackRate) yt.setPlaybackRate(r); },
      on: function (cb) { cbs.push(cb); },
      ready: function (cb) { api._ready = cb; }
    };

    window.onYouTubeIframeAPIReady = function () {
      yt = new YT.Player("mt-yt", {
        videoId: SRC,
        playerVars: { playsinline: 1, rel: 0 },
        events: {
          onReady: function () {
            if (api._ready) api._ready();
            // the IFrame API has no timeupdate; poll while playing
            poll = setInterval(function () {
              for (var i = 0; i < cbs.length; i++) cbs[i]();
            }, 250);
          }
        }
      });
    };

    var tag = document.createElement("script");
    tag.src = "https://www.youtube.com/iframe_api";
    document.head.appendChild(tag);
    return api;
  }

  function makeArchive() {
    // archive.org's embed exposes no seek API, but its src accepts ?start=N,
    // so we can still honour a click by reloading the iframe at that offset.
    // Crude (it restarts the player) but it makes MCM meetings -- the bulk of
    // the archive -- actually clickable instead of merely decorative.
    var f = document.createElement("iframe");
    var base = "https://archive.org/embed/" + encodeURIComponent(SRC);
    f.src = base;
    f.setAttribute("allowfullscreen", "");
    f.setAttribute("frameborder", "0");
    f.className = "mt-video";
    mount.appendChild(f);

    var sought = 0;
    return {
      video: true,
      seek: function (t) {
        sought = t;
        f.src = base + "?start=" + Math.floor(t);
      },
      time: function () { return sought; },
      rate: function () {},                 // not controllable through the embed
      on: function () {},                   // no timeupdate available
      ready: function (cb) { cb(); },
      limited: true                         // no live position -> no auto-follow
    };
  }

  if (KIND === "audio") backend = makeAudio();
  else if (KIND === "youtube") backend = makeYouTube();
  else if (KIND === "archive") backend = makeArchive();
  else return;

  // ------------------------------------------------------------- transport
  var bar = document.createElement("div");
  bar.className = "mt-controls";
  bar.innerHTML =
    '<button type="button" data-skip="-10">&#8592; 10s</button>' +
    '<button type="button" data-skip="10">10s &#8594;</button>' +
    '<label>Speed ' +
    '<select data-rate>' +
    '<option value="0.75">0.75&times;</option>' +
    '<option value="1" selected>1&times;</option>' +
    '<option value="1.25">1.25&times;</option>' +
    '<option value="1.5">1.5&times;</option>' +
    '<option value="2">2&times;</option>' +
    '<option value="3">3&times;</option>' +
    "</select></label>" +
    '<span data-clock>0:00</span>' +
    '<label class="mt-follow"><input type="checkbox" data-follow checked> follow</label>' +
    '<label class="mt-follow"><input type="checkbox" data-hl checked> highlight</label>';
  mount.appendChild(bar);

  bar.addEventListener("click", function (e) {
    var b = e.target.closest("button[data-skip]");
    if (!b) return;
    backend.seek(Math.max(0, backend.time() + parseFloat(b.getAttribute("data-skip"))));
  });
  bar.querySelector("[data-rate]").addEventListener("change", function (e) {
    backend.rate(parseFloat(e.target.value));
  });
  var clock = bar.querySelector("[data-clock]");
  var follow = bar.querySelector("[data-follow]");

  // Highlighting is a matter of taste -- some readers find a moving highlight
  // distracting -- so it is toggleable and the choice persists. Honour
  // prefers-reduced-motion as the default, and never smooth-scroll under it.
  var hl = bar.querySelector("[data-hl]");
  var reduceMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var stored = null;
  try { stored = localStorage.getItem("mt-highlight"); } catch (e) {}
  hl.checked = stored === null ? !reduceMotion : stored === "1";
  hl.addEventListener("change", function () {
    try { localStorage.setItem("mt-highlight", hl.checked ? "1" : "0"); } catch (e) {}
    if (!hl.checked && lines[current]) {
      lines[current].classList.remove("mt-active");
      clearWords(lines[current]);
    }
  });

  if (backend.limited) {
    // archive.org: no position feedback, so speed/clock/follow are meaningless
    bar.querySelector("[data-rate]").parentNode.style.display = "none";
    clock.style.display = "none";
    follow.parentNode.style.display = "none";
  }

  function hhmmss(t) {
    t = Math.max(0, Math.floor(t));
    var h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
  }

  // ------------------------------------------------------- click to seek
  document.addEventListener("click", function (e) {
    var line = e.target.closest("p.line[data-t]");
    if (!line) return;
    // let modified clicks (new tab) behave normally
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    var t = wordTimeAt(line, e);
    if (t === null) t = parseFloat(line.getAttribute("data-t")) || 0;
    backend.seek(t);
  });


  // Time of the word under the pointer, or null.
  //
  // We cannot rely on hit-testing span.w: only the CURRENTLY PLAYING line is
  // wordified, so a click on any other line would find no span and fall back
  // to the line start -- which is why the first click on a new paragraph used
  // to jump to its beginning and only the second click landed on the word.
  //
  // Instead resolve the caret offset at the click point and count words up to
  // it. Works on any line whether or not it has been wordified, and needs no
  // DOM mutation at click time.
  function wordTimeAt(line, e) {
    if (!wordTimes) return null;
    var idx = lines.indexOf(line);
    if (idx < 0) return null;
    var times = wordTimes[idx];
    if (!times || !times.length) return null;

    var node = null, offset = 0;
    if (document.caretRangeFromPoint) {                 // WebKit/Blink
      var r = document.caretRangeFromPoint(e.clientX, e.clientY);
      if (r) { node = r.startContainer; offset = r.startOffset; }
    } else if (document.caretPositionFromPoint) {       // Gecko
      var pos = document.caretPositionFromPoint(e.clientX, e.clientY);
      if (pos) { node = pos.offsetNode; offset = pos.offset; }
    }
    if (!node) return null;

    // characters of the line's text preceding the click
    var before = 0, done = false;
    var walker = document.createTreeWalker(line, NodeFilter.SHOW_TEXT, null);
    while (walker.nextNode()) {
      var n = walker.currentNode;
      if (n === node) { before += Math.min(offset, n.nodeValue.length); done = true; break; }
      before += n.nodeValue.length;
    }
    if (!done) return null;

    var text = line.textContent || "";
    var head = text.slice(0, before);
    // the "[Speaker]: " prefix is not spoken and consumes no timing -- drop it
    // (same rule wordify() applies, so indices stay consistent)
    var m = text.match(/^\s*\[[^\]]*\]:?\s*/);
    if (m) {
      if (before <= m[0].length) return times[0];
      head = head.slice(m[0].length);
    }
    var n_words = (head.match(/\S+/g) || []).length;
    var i = Math.max(0, Math.min(n_words, times.length - 1));
    return times[i];
  }

  // ------------------------------------------------- highlight + autoscroll
  var current = -1;

  function indexFor(t) {
    var lo = 0, hi = starts.length - 1, best = -1;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1;
      if (starts[mid] <= t) { best = mid; lo = mid + 1; } else { hi = mid - 1; }
    }
    return best;
  }

  function clearWords(el) {
    if (el && el.dataset.wordified) {
      el.innerHTML = el.dataset.plain;
      delete el.dataset.wordified;
    }
  }

  // Wrap each word of the line in a span, walking TEXT NODES only so the
  // existing <a> links (timestamps, green resolution links) survive intact.
  // Only ever applied to the line currently playing, then torn back down.
  function wordify(el, idx) {
    if (!wordTimes || !wordTimes[idx] || !wordTimes[idx].length) return;
    if (el.dataset.wordified) return;
    el.dataset.plain = el.innerHTML;

    var times = wordTimes[idx], n = 0;
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    var skippedPrefix = false;
    nodes.forEach(function (node) {
      var text = node.nodeValue;
      if (!text.trim()) return;
      var frag = document.createDocumentFragment();
      // the leading "[Speaker]: " prefix is not spoken -- don't consume a timing
      var parts = text.split(/(\s+)/);
      parts.forEach(function (part) {
        if (!part.trim()) { frag.appendChild(document.createTextNode(part)); return; }
        if (!skippedPrefix && /\]:?$/.test(part)) {
          frag.appendChild(document.createTextNode(part));
          skippedPrefix = true;
          return;
        }
        if (!skippedPrefix && /^\[/.test(part)) {
          frag.appendChild(document.createTextNode(part));
          return;
        }
        var span = document.createElement("span");
        span.className = "w";
        if (n < times.length) span.setAttribute("data-wt", times[n]);
        n++;
        span.textContent = part;
        frag.appendChild(span);
      });
      node.parentNode.replaceChild(frag, node);
    });
    el.dataset.wordified = "1";
  }

  function tick() {
    var t = backend.time();
    clock.textContent = hhmmss(t);
    var i = indexFor(t);
    if (i !== current) {
      if (lines[current]) { lines[current].classList.remove("mt-active"); clearWords(lines[current]); }
      current = i;
      if (lines[current] && hl.checked) {
        lines[current].classList.add("mt-active");
        wordify(lines[current], current);
        if (follow.checked) {
          lines[current].scrollIntoView({
            block: "center",
            behavior: reduceMotion ? "auto" : "smooth"
          });
        }
      }
    }
    if (hl.checked && wordTimes && lines[current] && lines[current].dataset.wordified) {
      var spans = lines[current].querySelectorAll("span.w");
      for (var k = 0; k < spans.length; k++) {
        var wt = parseFloat(spans[k].getAttribute("data-wt"));
        var nxt = spans[k + 1] ? parseFloat(spans[k + 1].getAttribute("data-wt")) : Infinity;
        spans[k].classList.toggle("w-active", t >= wt && t < nxt);
      }
    }
  }
  backend.on(tick);
  loadWordTimes();

  // ------------------------------------------------------ deep link (#t=)
  function fragmentTime() {
    var m = /[#&]t=([0-9.]+)/.exec(location.hash);
    return m ? parseFloat(m[1]) : null;
  }
  backend.ready(function () {
    var t = fragmentTime();
    if (t !== null) backend.seek(t);
  });
  window.addEventListener("hashchange", function () {
    var t = fragmentTime();
    if (t !== null) backend.seek(t);
  });

  // -------------------------------------------------------- keyboard
  document.addEventListener("keydown", function (e) {
    var tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "select" || tag === "textarea") return;
    if (e.key === "j") backend.seek(Math.max(0, backend.time() - 10));
    else if (e.key === "l") backend.seek(backend.time() + 10);
    else if (e.key === "k" || e.key === " ") {
      if (backend.el) {
        e.preventDefault();
        backend.el.paused ? backend.el.play() : backend.el.pause();
      }
    }
  });
})();

/* ---------------------------------------------------------------------------
 * transcript-corrections -- right-click a line to report an error.
 *
 * Static-site friendly: no backend. The menu opens a PRE-FILLED Google Form
 * with the video id, timestamp, speaker and original text already populated,
 * so the contributor only supplies the fix. Configured by
 * corrections-config.json; inert until that file sets enabled: true.
 *
 * Google Form rather than GitHub Issues on purpose -- requiring a GitHub
 * account would exclude most residents, and broad participation is the point.
 *
 * Submissions are a QUEUE, never applied automatically. A public write path
 * into a civic record is an abuse target, and these corrections are meant to
 * become ground truth for evaluation -- unreviewed data would defeat that.
 * ------------------------------------------------------------------------ */
(function () {
  "use strict";

  var mount = document.getElementById("mt-player");
  if (!mount) return;

  var cfg = null, menu = null;

  fetch(mount.getAttribute("data-corrections") || "corrections-config.json")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (c) { if (c && c.enabled) { cfg = c; arm(); } })
    .catch(function () { /* no corrections UI; page is unaffected */ });

  function prefill(kind, line) {
    var f = cfg.fields, q = [];
    function add(key, val) {
      if (f[key] && val != null) q.push(f[key] + "=" + encodeURIComponent(val));
    }
    var text = (line.textContent || "").trim();
    var m = text.match(/^\[([^\]]*)\]:\s*([\s\S]*)$/);
    add("kind", (cfg.kinds && cfg.kinds[kind]) || kind);
    add("video_id", mount.getAttribute("data-video-id") || "");
    add("video_title", document.title);
    add("timestamp", line.getAttribute("data-t"));
    add("speaker", m ? m[1] : "");
    add("original_text", (m ? m[2] : text).slice(0, 900));
    add("page_url", location.origin + location.pathname +
        "#t=" + Math.floor(parseFloat(line.getAttribute("data-t")) || 0));
    return cfg.form_url + "?usp=pp_url&" + q.join("&");
  }

  function close() { if (menu) { menu.remove(); menu = null; } }

  function open(x, y, line) {
    close();
    menu = document.createElement("div");
    menu.className = "mt-menu";
    Object.keys(cfg.kinds).forEach(function (kind) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = cfg.kinds[kind];
      b.addEventListener("click", function () {
        // The anonymization ask carries real consequences; state them plainly
        // and require an explicit acknowledgement BEFORE the form opens.
        if (kind === "anonymize" && cfg.anonymize_notice &&
            !window.confirm(cfg.anonymize_notice + "\n\nContinue?")) {
          close();
          return;
        }
        window.open(prefill(kind, line), "_blank", "noopener");
        close();
      });
      menu.appendChild(b);
    });
    menu.style.left = x + "px";
    menu.style.top = y + "px";
    document.body.appendChild(menu);
  }

  function arm() {
    document.addEventListener("contextmenu", function (e) {
      var line = e.target.closest && e.target.closest("p.line[data-t]");
      if (!line) return;
      e.preventDefault();
      open(e.pageX, e.pageY, line);
    });
    document.addEventListener("click", function (e) {
      if (menu && !menu.contains(e.target)) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });

    var hint = document.createElement("div");
    hint.className = "mt-hint";
    hint.textContent = "Spot an error? Right-click any line to suggest a correction.";
    mount.appendChild(hint);
  }
})();
