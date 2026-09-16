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

  var wordTimes = null;
  var wtEl = document.getElementById("word-times");
  if (wtEl) {
    try { wordTimes = JSON.parse(wtEl.textContent); } catch (e) { wordTimes = null; }
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
    // archive.org's embed exposes no seek API we can rely on, so the player is
    // informational and line clicks fall back to opening archive.org at the
    // timestamp (the <a href> the line already carries).
    var f = document.createElement("iframe");
    f.src = "https://archive.org/embed/" + encodeURIComponent(SRC);
    f.width = "100%";
    f.height = "60";
    f.frameBorder = "0";
    f.setAttribute("allowfullscreen", "");
    mount.appendChild(f);
    return null; // signals "no in-page seeking"
  }

  if (KIND === "audio") backend = makeAudio();
  else if (KIND === "youtube") backend = makeYouTube();
  else if (KIND === "archive") { makeArchive(); return; }
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
    '<label class="mt-follow"><input type="checkbox" data-follow checked> follow</label>';
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
    backend.seek(parseFloat(line.getAttribute("data-t")) || 0);
  });

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

  function wordify(el, idx) {
    if (!wordTimes || !wordTimes[idx] || el.dataset.wordified) return;
    el.dataset.plain = el.innerHTML;
    var words = wordTimes[idx];           // [[t, "word"], ...]
    var html = "";
    for (var i = 0; i < words.length; i++) {
      html += '<span class="w" data-wt="' + words[i][0] + '">' +
        words[i][1] + "</span> ";
    }
    // keep the speaker prefix, replace only the spoken text
    var m = el.dataset.plain.match(/^(\s*\[[^\]]*\]:\s*)/);
    el.innerHTML = (m ? m[1] : "") + html;
    el.dataset.wordified = "1";
  }

  function tick() {
    var t = backend.time();
    clock.textContent = hhmmss(t);
    var i = indexFor(t);
    if (i !== current) {
      if (lines[current]) { lines[current].classList.remove("mt-active"); clearWords(lines[current]); }
      current = i;
      if (lines[current]) {
        lines[current].classList.add("mt-active");
        wordify(lines[current], current);
        if (follow.checked) {
          lines[current].scrollIntoView({ block: "center", behavior: "smooth" });
        }
      }
    }
    if (wordTimes && lines[current] && lines[current].dataset.wordified) {
      var spans = lines[current].querySelectorAll("span.w");
      for (var k = 0; k < spans.length; k++) {
        var wt = parseFloat(spans[k].getAttribute("data-wt"));
        var nxt = spans[k + 1] ? parseFloat(spans[k + 1].getAttribute("data-wt")) : Infinity;
        spans[k].classList.toggle("w-active", t >= wt && t < nxt);
      }
    }
  }
  backend.on(tick);

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
