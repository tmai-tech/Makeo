(function () {
  var KEY = "makeo-demo-v2";
  var PREV_KEYS = ["makeo-demo-v1"];
  var clips = {};
  // Colab pulls this git file. It cannot auto-run cells (Google blocks that).
  var COLAB_NOTEBOOK =
    "https://colab.research.google.com/github/tmai-tech/Makeo/blob/explore-catalog-vton/notebooks/fashn_vton_colab.ipynb";

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY) || "{}"); }
    catch (e) { return {}; }
  }
  function save(s) {
    try { localStorage.setItem(KEY, JSON.stringify(s)); }
    catch (e) { s._saveError = e.message || "storage blocked"; }
  }
  function mergeUsers(into, from) {
    var seen = {};
    into.forEach(function (u) { seen[u.email] = true; });
    (from || []).forEach(function (u) {
      if (u && u.email && !seen[u.email]) {
        into.push(u);
        seen[u.email] = true;
      }
    });
  }
  function state() {
    var s = load();
    s.users = s.users || [];
    s.brands = s.brands || [];
    s.jobs = s.jobs || [];
    s.session = s.session || null;
    s.deletedBrandIds = s.deletedBrandIds || [];
    PREV_KEYS.forEach(function (k) {
      try {
        var old = JSON.parse(localStorage.getItem(k) || "{}");
        mergeUsers(s.users, old.users);
        (old.brands || []).forEach(function (b) {
          if (!b || !b.id) return;
          if (s.deletedBrandIds.indexOf(b.id) >= 0) return;
          if (!s.brands.some(function (x) { return x.id === b.id; })) s.brands.push(b);
        });
      } catch (e) {}
    });
    s.brands = s.brands.filter(function (b) {
      return b && b.id && s.deletedBrandIds.indexOf(b.id) < 0;
    });
    return s;
  }
  function uid() { return Math.random().toString(36).slice(2, 10) + Date.now().toString(36); }
  function hash(str) {
    if (!window.crypto || !crypto.subtle) {
      return Promise.reject(new Error("This page must be opened on https://tmai-tech.github.io/Makeo/ (not a saved file)."));
    }
    return crypto.subtle.digest("SHA-256", new TextEncoder().encode(str)).then(function (buf) {
      return Array.from(new Uint8Array(buf)).map(function (b) {
        return b.toString(16).padStart(2, "0");
      }).join("");
    });
  }
  function route() {
    var h = (location.hash || "#/").replace(/^#/, "");
    if (h.charAt(0) !== "/") h = "/" + h;
    return h;
  }
  function go(path) { location.hash = "#" + path; }
  function user(s) {
    if (!s.session) return null;
    return s.users.filter(function (u) { return u.id === s.session; })[0] || null;
  }
  function mine(s, list) {
    var u = user(s);
    if (!u) return [];
    return list.filter(function (x) { return x.userId === u.id; });
  }
  function brandBy(s, id) {
    return s.brands.filter(function (b) { return b.id === id; })[0];
  }
  function jobBy(s, id) {
    return s.jobs.filter(function (j) { return j.id === id; })[0];
  }
  function ownBrand(s, b) {
    var u = user(s);
    return u && b && b.userId === u.id;
  }
  function flowKeyOf(b) {
    return ((b && (b.flowKey || b.geminiKey)) || "").trim();
  }
  function falKeyOf(b) {
    return ((b && b.falKey) || "").trim();
  }
  function hasVideoKey(b) {
    return !!(falKeyOf(b) || flowKeyOf(b));
  }
  function falModels() {
    return {
      "ltx-fast": {
        id: "fal-ai/ltx-2.3/text-to-video/fast",
        label: "LTX 2.3 Fast (cheap, ~$0.25 for 6s)",
        input: function (prompt) {
          return {
            prompt: prompt,
            duration: 6,
            resolution: "1080p",
            aspect_ratio: "9:16",
            generate_audio: true
          };
        }
      },
      "veo": {
        id: "fal-ai/veo3.1",
        label: "Veo 3.1 on fal (closer to Flow, costs more)",
        input: function (prompt) {
          return {
            prompt: prompt,
            aspect_ratio: "9:16",
            duration: "8s",
            generate_audio: true
          };
        }
      }
    };
  }
  function advanceJobs(s) {
    var now = Date.now();
    s.jobs.forEach(function (j) {
      if (j.status === "publishing" && now >= (j.postedAt || 0)) j.status = "posted";
    });
  }
  function esc(t) {
    return String(t == null ? "" : t).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }
  function fileToData(file, max) {
    max = max || 400000;
    return new Promise(function (resolve, reject) {
      if (!file) return resolve("");
      if (file.size > max) return reject(new Error("Keep images under 400KB for this demo."));
      var r = new FileReader();
      r.onload = function () { resolve(r.result); };
      r.onerror = reject;
      r.readAsDataURL(file);
    });
  }
  function loadImg(src) {
    return new Promise(function (resolve) {
      if (!src) return resolve(null);
      var img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = function () { resolve(null); };
      img.src = src;
    });
  }
  function missingForVideo(brand, mode, prompt) {
    var miss = [];
    if (!brand || !brand.name) miss.push("a brand name");
    if (!hasVideoKey(brand)) {
      miss.push("a fal.ai key or a Google Flow key (Brand → Keys). Generate will not run without one of them.");
    }
    if (mode === "custom") {
      if (!(prompt || "").trim()) miss.push("your own video prompt");
    } else {
      if (!(brand.pitch || "").trim() && !(brand.hook || "").trim()) {
        miss.push("a brand pitch or spoken hook (needed when you use “today’s topic”)");
      }
    }
    return miss;
  }
  function veoError(data, status) {
    var msg = (data && data.error && data.error.message) || (data && data.message) || "";
    if (status === 400 && !msg) msg = "Google rejected the request (400). Check the key and that Veo is enabled on this project.";
    if (status === 403) msg = msg || "This Gemini key is not allowed to generate Veo video.";
    if (status === 429) msg = msg || "Google rate-limited this key. Wait and try again.";
    return msg || ("Google video API failed (HTTP " + status + ").");
  }
  function parseVeoOp(data) {
    var r = data && (data.response || data);
    var samples = (r && r.generateVideoResponse && r.generateVideoResponse.generatedSamples)
      || (r && r.generatedVideos)
      || (r && r.generateVideoResponse && r.generateVideoResponse.generatedVideos)
      || [];
    var vid = samples[0] && (samples[0].video || samples[0]);
    if (!vid) return null;
    return { uri: vid.uri || vid.videoUri, bytes: vid.videoBytes || vid.bytesBase64Encoded };
  }
  function generateVeo(key, prompt, onTick) {
    var base = "https://generativelanguage.googleapis.com/v1beta";
    var model = "veo-3.1-generate-preview";
    var headers = { "Content-Type": "application/json", "x-goog-api-key": key };
    return fetch(base + "/models/" + model + ":predictLongRunning", {
      method: "POST",
      headers: headers,
      body: JSON.stringify({
        instances: [{ prompt: prompt }],
        parameters: { aspectRatio: "9:16", durationSeconds: 8 }
      })
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok || data.error) throw new Error(veoError(data, res.status));
        if (!data.name) throw new Error("Google did not start a video job. " + (data.error && data.error.message || JSON.stringify(data).slice(0, 240)));
        return data.name;
      });
    }).then(function (name) {
      var tries = 0;
      function poll() {
        tries += 1;
        if (onTick) onTick("Waiting on Veo… " + tries * 8 + "s (usually 30–90s)");
        return fetch(base + "/" + name, { headers: headers }).then(function (res) {
          return res.json().then(function (data) {
            if (!res.ok || data.error) throw new Error(veoError(data, res.status));
            if (!data.done) {
              if (tries > 24) throw new Error("Veo did not finish in 3 minutes. Check the key quota in AI Studio and try again.");
              return new Promise(function (r) { setTimeout(r, 8000); }).then(poll);
            }
            if (data.error) throw new Error(data.error.message || "Veo job failed.");
            var got = parseVeoOp(data);
            if (!got) throw new Error("Veo finished but returned no video. " + JSON.stringify(data).slice(0, 300));
            if (got.bytes) {
              var bin = atob(got.bytes);
              var arr = new Uint8Array(bin.length);
              for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
              return URL.createObjectURL(new Blob([arr], { type: "video/mp4" }));
            }
            return fetch(got.uri, { headers: { "x-goog-api-key": key } }).then(function (v) {
              if (!v.ok) throw new Error("Could not download the Veo file (HTTP " + v.status + ").");
              return v.blob();
            }).then(function (blob) {
              return URL.createObjectURL(blob);
            });
          });
        });
      }
      return poll();
    });
  }
  function falError(data, status) {
    var detail = "";
    if (data) {
      if (typeof data.detail === "string") detail = data.detail;
      else if (data.detail && data.detail.msg) detail = data.detail.msg;
      else if (Array.isArray(data.detail) && data.detail[0]) {
        detail = data.detail[0].msg || JSON.stringify(data.detail[0]);
      } else if (data.error) detail = typeof data.error === "string" ? data.error : (data.error.message || "");
      else if (data.message) detail = data.message;
    }
    var locked = /exhausted|locked|top up/i.test(detail);
    if (status === 401) return detail || "fal.ai rejected this key (401). Copy a new key from fal.ai/dashboard/keys.";
    if (locked || status === 402 || status === 403) {
      return "fal.ai has no usable dollars on this account. Creating a new account or a new key does not add credit. Open fal.ai/dashboard/billing, add at least $5, wait until the balance shows a number above $0, then generate again. If it still says locked after a top-up, email support@fal.ai (known fal unlock bug). Or switch Engine to Google Veo 3.1 — that uses your Flow key, not fal.";
    }
    if (status === 429) return detail || "fal.ai rate-limited this key. Wait and try again.";
    return detail || ("fal.ai failed (HTTP " + status + ").");
  }
  function falVideoUrl(data) {
    if (!data) return "";
    if (data.video && data.video.url) return data.video.url;
    if (data.video && typeof data.video === "string") return data.video;
    if (data.video_url) return data.video_url;
    var list = data.videos || data.output || [];
    if (list[0] && list[0].url) return list[0].url;
    return "";
  }
  function generateFal(key, prompt, modelKey, onTick) {
    var models = falModels();
    var spec = models[modelKey] || models["ltx-fast"];
    var headers = { "Content-Type": "application/json", Authorization: "Key " + key };
    var endpoint = spec.id;
    return fetch("https://queue.fal.run/" + endpoint, {
      method: "POST",
      headers: headers,
      body: JSON.stringify(spec.input(prompt))
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(falError(data, res.status));
        if (!data.request_id && !data.status_url) {
          throw new Error("fal.ai did not start a job. " + JSON.stringify(data).slice(0, 240));
        }
        return {
          statusUrl: data.status_url || ("https://queue.fal.run/" + endpoint + "/requests/" + data.request_id + "/status"),
          resultUrl: data.response_url || ("https://queue.fal.run/" + endpoint + "/requests/" + data.request_id)
        };
      });
    }).then(function (urls) {
      var tries = 0;
      function poll() {
        tries += 1;
        if (onTick) onTick("Waiting on fal.ai (" + spec.label + ")… " + tries * 5 + "s");
        return fetch(urls.statusUrl + (urls.statusUrl.indexOf("?") >= 0 ? "&" : "?") + "logs=1", { headers: headers }).then(function (res) {
          return res.json().then(function (data) {
            if (!res.ok) throw new Error(falError(data, res.status));
            var st = data.status || "";
            if (st === "IN_QUEUE" && onTick) onTick("fal.ai queue position " + (data.queue_position == null ? "?" : data.queue_position));
            if (st !== "COMPLETED") {
              if (tries > 48) throw new Error("fal.ai did not finish in 4 minutes. Check credit and try again.");
              return new Promise(function (r) { setTimeout(r, 5000); }).then(poll);
            }
            if (data.error) throw new Error(data.error);
            return fetch(urls.resultUrl, { headers: headers }).then(function (r2) {
              return r2.json().then(function (out) {
                if (!r2.ok) throw new Error(falError(out, r2.status));
                var href = falVideoUrl(out);
                if (!href) throw new Error("fal.ai finished but returned no video. " + JSON.stringify(out).slice(0, 300));
                return fetch(href).then(function (v) {
                  if (!v.ok) throw new Error("Could not download the fal.ai file (HTTP " + v.status + ").");
                  return v.blob();
                }).then(function (blob) {
                  return URL.createObjectURL(blob);
                });
              });
            });
          });
        });
      }
      return poll();
    });
  }
  function sceneText(brand, mode, prompt) {
    if (mode === "custom") return prompt.trim();
    var bits = [brand.name];
    if (brand.pitch) bits.push(brand.pitch);
    if (brand.hook) bits.push(brand.hook);
    return bits.join(" — ");
  }
  function mimeType() {
    var opts = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];
    for (var i = 0; i < opts.length; i++) {
      if (MediaRecorder.isTypeSupported(opts[i])) return opts[i];
    }
    return "";
  }
  function renderClip(brand, line, onTick) {
    var mime = mimeType();
    if (!mime) {
      return Promise.reject(new Error("This browser cannot record a video preview."));
    }
    return Promise.all([loadImg(brand.logo), loadImg(brand.splash)]).then(function (imgs) {
      return new Promise(function (resolve, reject) {
        var w = 360, h = 640, secs = 8;
        var canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        var ctx = canvas.getContext("2d");
        var stream = canvas.captureStream(30);
        var rec;
        try { rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 1200000 }); }
        catch (e) { reject(e); return; }
        var chunks = [];
        rec.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
        rec.onerror = function () { reject(new Error("Video recording failed.")); };
        rec.onstop = function () {
          if (!chunks.length) {
            reject(new Error("Video recording produced no frames."));
            return;
          }
          resolve(URL.createObjectURL(new Blob(chunks, { type: mime })));
        };
        var t0 = performance.now();
        function draw(t) {
          var p = Math.min(1, t / secs);
          ctx.fillStyle = "#0d0d0d";
          ctx.fillRect(0, 0, w, h);
          if (imgs[1] && t > 5.2) {
            ctx.drawImage(imgs[1], 0, 0, w, h);
            ctx.fillStyle = "rgba(0,0,0,0.35)";
            ctx.fillRect(0, 0, w, h);
          } else {
            var g = ctx.createLinearGradient(0, 0, w, h);
            g.addColorStop(0, "#1a1408");
            g.addColorStop(1, "#111");
            ctx.fillStyle = g;
            ctx.fillRect(0, 0, w, h);
            ctx.fillStyle = "#e8b84b";
            ctx.globalAlpha = 0.15 + 0.1 * Math.sin(t * 2);
            ctx.fillRect(0, h * (0.2 + 0.05 * Math.sin(t)), w, 8);
            ctx.globalAlpha = 1;
          }
          if (imgs[0]) {
            var s = 72;
            ctx.drawImage(imgs[0], (w - s) / 2, 48, s, s);
          }
          ctx.fillStyle = "#e8b84b";
          ctx.font = "700 22px system-ui,sans-serif";
          ctx.textAlign = "center";
          ctx.fillText(brand.name || "", w / 2, imgs[0] ? 148 : 80);
          ctx.fillStyle = "#eee";
          ctx.font = "400 16px system-ui,sans-serif";
          wrap(ctx, line, w / 2, 200, w - 48, 22);
          if (brand.hook && t > 4) {
            ctx.fillStyle = "#e8b84b";
            ctx.font = "600 15px system-ui,sans-serif";
            wrap(ctx, brand.hook, w / 2, h - 90, w - 48, 20);
          }
          ctx.fillStyle = "#9a9a9a";
          ctx.font = "12px system-ui,sans-serif";
          ctx.fillText((Math.min(secs, t)).toFixed(1) + "s / 8s", w / 2, h - 24);
          if (onTick) onTick(p);
        }
        function wrap(c, text, x, y, max, lh) {
          var words = String(text || "").split(/\s+/);
          var row = "";
          var yy = y;
          for (var i = 0; i < words.length; i++) {
            var test = row ? row + " " + words[i] : words[i];
            if (c.measureText(test).width > max && row) {
              c.fillText(row, x, yy);
              row = words[i];
              yy += lh;
              if (yy > h - 120) break;
            } else row = test;
          }
          if (row) c.fillText(row, x, yy);
        }
        rec.start(200);
        function tick() {
          var t = (performance.now() - t0) / 1000;
          draw(t);
          if (t >= secs) rec.stop();
          else requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
      });
    });
  }

  function shell(s, inner, opts) {
    opts = opts || {};
    var u = user(s);
    var nav = opts.landing
      ? '<a href="#/help">Easy tutorial</a><a href="#/signup">Create account</a><a href="#/login">Sign in</a>'
      : (u
        ? '<a href="#/home">Home</a><a href="#/help">Tutorial</a><span class="who">' + esc(u.email) + "</span><a href=\"#/logout\">Log out</a>"
        : '<a href="#/help">Tutorial</a><a href="#/login">Sign in</a><a href="#/signup">Create account</a>');
    var preview = location.pathname.indexOf("/preview/fal") >= 0;
    return (
      '<header class="top"><a class="brand" href="#/"><img src="assets/icon.svg" width="28" height="28" alt=""/><span>Makeo</span></a><nav>' +
      nav + "</nav></header>" +
      (preview
        ? '<div class="banner">PREVIEW of the fal.ai branch. This is not the live site. Live stays at <a href="https://tmai-tech.github.io/Makeo/">tmai-tech.github.io/Makeo</a>.</div>'
        : "") +
      "<main>" + inner + "</main>" +
      "<footer><p>" +
      (preview
        ? 'Preview · <a href="https://tmai-tech.github.io/Makeo/preview/fal/">/preview/fal/</a>'
        : 'Live at <a href="https://tmai-tech.github.io/Makeo/">tmai-tech.github.io/Makeo</a>') +
      "</p></footer>"
    );
  }

  function landing() {
    return (
      '<section class="hero">' +
      '<p class="eyebrow">Create account · Add brand · Generate a preview · Approve</p>' +
      "<h1>Your brand. Your prompt.<br/>An 8-second Reel.</h1>" +
      '<p class="lead">Follow the easy tutorial. We show every click — including which Google page gives you a key.</p>' +
      '<div class="actions"><a class="btn primary" href="#/help">Start the easy tutorial</a>' +
      '<a class="btn ghost" href="#/signup">I already know — create account</a></div></section>' +
      '<ol class="pipe" id="how"><li><strong>1. Account</strong><span>Email + password, this browser only</span></li>' +
      "<li><strong>2. Brand</strong><span>Name, pitch, hook, optional logo</span></li>" +
      "<li><strong>3. Generate</strong><span>Needs your prompt, or a pitch/hook for a topic</span></li>" +
      "<li><strong>4. Approve</strong><span>Only after a preview video is ready</span></li></ol>"
    );
  }

  function tutorial() {
    return (
      '<p class="eyebrow">Easy tutorial</p>' +
      "<h1>Do these steps in order</h1>" +
      '<p class="lead">You do not need to be technical. Read the yellow “Click” lines and do only that.</p>' +
      '<div class="how">' +

      '<div class="how-step"><h3><span class="n">1</span> Create your Makeo login</h3>' +
      "<p>This login is only for Makeo in <em>this</em> browser. Invent a password. Do not use your bank password.</p>" +
      '<p class="click">Click <strong>Create my account now</strong> below. Type your email. Type a password (6 or more letters). Click <strong>Create account</strong>.</p>' +
      '<a class="btn primary" href="#/signup">Create my account now</a></div>' +

      '<div class="how-step"><h3><span class="n">2</span> Add your brand name</h3>' +
      "<p>After you are in, you will see “Your brands”.</p>" +
      '<p class="click">Click <strong>New brand</strong>. In <strong>Name</strong> type your shop or brand (example: Makers Nook). You can leave the other boxes empty. Click <strong>Save and enter keys</strong>.</p></div>' +

      '<div class="how-step"><h3><span class="n">3</span> Get a fal.ai key (this branch)</h3>' +
      "<p>fal’s API is prepaid. A new fal login starts at $0. Their free website clips are not usable from this key.</p>" +
      '<p class="click">Open <a href="https://fal.ai/dashboard/billing" target="_blank" rel="noopener"><strong>fal billing</strong></a>, add at least $5, then copy a key from <a href="https://fal.ai/dashboard/keys" target="_blank" rel="noopener">fal keys</a> and paste it on Makeo → Keys.</p>' +
      "<p>Or skip fal and use your Google Flow key in step 3b.</p></div>" +

      '<div class="how-step"><h3><span class="n">3b</span> Get a Google Flow key (optional)</h3>' +
      "<p>Google makes the video. You must bring your own key. Use a <strong>personal Gmail</strong> (not a work/school email if you can). Keep the Makeo tab open.</p>" +
      '<p class="error">If you see <strong>Failed to create project</strong>, do <em>not</em> click “Create API key in new project” again. That Google page is broken for many people. Use Plan B below.</p>' +
      "<p><strong>Plan A — only if Google already shows a project name</strong></p>" +
      '<p><a class="btn primary" href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Open Google AI Studio keys</a></p>' +
      "<ol>" +
      "<li>Sign in with Gmail.</li>" +
      "<li>Click <strong>Create API key</strong>.</li>" +
      "<li>If a list of projects appears, <strong>click an existing project</strong> — do not choose “new project”.</li>" +
      "<li>Click <strong>Create</strong> / <strong>Copy</strong>.</li>" +
      "</ol>" +
      "<p><strong>Plan B — this usually works when Plan A fails</strong></p>" +
      '<p class="click">1. Click <a href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noopener"><strong>Create a Google project here</strong></a>.</p>' +
      "<p>Type any name (example: Makeo). Click <strong>Create</strong>. Wait until the top bar shows that name.</p>" +
      '<p class="click">2. Click <a href="https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com" target="_blank" rel="noopener"><strong>Turn on the Gemini API here</strong></a>. Click <strong>Enable</strong>.</p>' +
      '<p class="click">3. Click <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener"><strong>AI Studio keys again</strong></a>.</p>' +
      "<ol>" +
      "<li>If you see <strong>Import projects</strong> or <strong>Projects</strong>, import the project you just created.</li>" +
      "<li>Click <strong>Create API key</strong>.</li>" +
      "<li>Choose <strong>that existing project</strong> (the one named Makeo). Do not create a new project.</li>" +
      "<li>Click <strong>Copy</strong> on the long secret (often starts with <strong>AIza</strong>).</li>" +
      "</ol>" +
      "<p>If Plan B still fails: turn off VPN, try a personal Gmail in a new Chrome window, and check <a href=\"https://myaccount.google.com/age-verification\" target=\"_blank\" rel=\"noopener\">Google age verification</a>.</p>" +
      "<p>Come back to Makeo. Do not share this key.</p></div>" +

      '<div class="how-step"><h3><span class="n">4</span> Paste the key into Makeo</h3>' +
      "<p>You should be on the page <strong>Video keys</strong>. If not:</p>" +
      '<p class="click">Click <strong>Home</strong> → your brand name → <strong>Keys</strong>.</p>' +
      '<p class="click">Paste the fal.ai key (or the Google key) and click <strong>Save keys</strong>.</p>' +
      "<p>You should see a green line: key saved.</p></div>" +

      '<div class="how-step"><h3><span class="n">5</span> Make a video</h3>' +
      '<p class="click">Click <strong>Generate video</strong>. In <strong>Video prompt</strong> type what you want to see, in plain words. Example: <em>A smiling person in a small shop holding a handmade bag, warm light, 8 seconds, phone video.</em></p>' +
      '<p class="click">Click the yellow <strong>Generate video</strong> button. Wait 1–2 minutes. Do not close the tab.</p>' +
      "<p>If something is missing, the page will list it in red. Fix that, then click Generate again.</p></div>" +

      '<div class="how-step"><h3><span class="n">6</span> Watch, then Approve or Reject</h3>' +
      "<p>When the video is ready you will see a player.</p>" +
      '<p class="click">Press play. If you like it, click <strong>Approve &amp; post</strong>. If not, click <strong>Reject</strong>.</p>' +
      "<p>Approve on this website does <strong>not</strong> put the video on Instagram. It only finishes the practice flow. Posting to Instagram needs the Makeo program on a computer.</p></div>" +

      "</div>" +
      '<div class="actions"><a class="btn primary" href="#/signup">Start at step 1 — create account</a></div>'
    );
  }

  function authForm(kind, err) {
    var title = kind === "signup" ? "Create your Makeo account" : "Sign in";
    var btn = kind === "signup" ? "Create account" : "Sign in";
    var other = kind === "signup"
      ? 'Already have one? <a href="#/login">Sign in</a>'
      : 'New here? <a href="#/signup">Create an account</a>';
    return (
      '<section class="panel"><h1>' + title + "</h1>" +
      '<p class="muted">Use <strong>Create account</strong> first on this same browser. Login only works for accounts created here — not email/password from Instagram or another device.</p>' +
      (err ? '<p class="error">' + esc(err) + "</p>" : "") +
      '<form id="authForm">' +
      '<label>Email</label><input name="email" type="email" required autocomplete="username"/>' +
      '<label>Password</label><input name="password" type="password" required minlength="6" autocomplete="' +
      (kind === "signup" ? "new-password" : "current-password") + '"/>' +
      '<div class="row"><button class="btn primary" type="submit">' + btn + "</button></div>" +
      '<p class="muted">' + other + "</p></form></section>"
    );
  }

  function home(s) {
    var brands = mine(s, s.brands);
    var cards = brands.length
      ? brands.map(function (b) {
          return '<div class="card"><a href="#/brands/' + b.id + '"><strong>' + esc(b.name) +
            "</strong></a><div class=\"muted\">" + esc(b.slug) + "</div>" +
            '<div class="row"><a href="#/brands/' + b.id + '/keys">Keys</a>' +
            ' · <a href="#/brands/' + b.id + '/compose">Generate</a>' +
            ' · <a href="#/brands/' + b.id + '/catalog">Catalog</a>' +
            ' · <a href="#/brands/' + b.id + '/inbox">Inbox</a>' +
            ' · <a href="#/brands/' + b.id + '/instagram">Instagram</a></div>' +
            '<div class="row"><button type="button" class="btn no deleteBrand" data-id="' + b.id +
            '" data-name="' + esc(b.name) + '">Delete brand</button></div></div>';
        }).join("")
      : '<p class="muted">No brands yet. Create one to start.</p>';
    return (
      '<div class="banner">Stuck? Open the <a href="#/help">easy tutorial</a>. Add a <strong>fal.ai key</strong> (this branch) or a Google Flow key before a video can be made.</div>' +
      "<h1>Your brands</h1>" + cards +
      '<div class="actions"><a class="btn primary" href="#/brands/new">New brand</a> <a class="btn ghost" href="#/help">Show me every click</a></div>'
    );
  }

  function brandForm(b, err) {
    b = b || {};
    return (
      '<section class="panel"><h1>' + (b.id ? "Edit " + esc(b.name) : "New brand") + "</h1>" +
      '<p class="muted">Name is required. Next you will add a fal.ai key or a Google Flow key — Generate will not run without one.</p>' +
      (err ? '<p class="error">' + esc(err) + "</p>" : "") +
      '<form id="brandForm">' +
      '<label>Name</label><input name="name" required value="' + esc(b.name || "") + '"/>' +
      '<label>Slug</label><input name="slug" required value="' + esc(b.slug || "") + '" placeholder="my-brand"/>' +
      '<label>Pitch — what you sell</label><textarea name="pitch" rows="3">' + esc(b.pitch || "") + "</textarea>" +
      '<label>Spoken hook</label><textarea name="hook" rows="2">' + esc(b.hook || "") + "</textarea>" +
      '<label>Tone</label><input name="tone" value="' + esc(b.tone || "") + '"/>' +
      '<label>Region</label><input name="region" value="' + esc(b.region || "") + '" placeholder="e.g. US, IN"/>' +
      '<label>Logo (optional)</label><input name="logo" type="file" accept="image/*"/>' +
      (b.logo ? '<p><img class="logo-preview" src="' + b.logo + '" alt="logo"/></p>' : "") +
      '<label>Splash / end-card (optional)</label><input name="splash" type="file" accept="image/*,.gif"/>' +
      '<div class="row"><button class="btn primary" type="submit">Save and enter keys</button></div></form>' +
      (b.id
        ? '<div class="row"><button type="button" class="btn no deleteBrand" data-id="' + b.id +
          '" data-name="' + esc(b.name) + '">Delete this brand</button></div>'
        : "") +
      (b.id
        ? '<p><a href="#/brands/' + b.id + '/keys">Keys</a> · <a href="#/brands/' + b.id + '/compose">Generate</a> · <a href="#/brands/' + b.id + '/catalog">Catalog</a> · <a href="#/brands/' + b.id + '/inbox">Inbox</a></p>'
        : "") +
      "</section>"
    );
  }

  function keysForm(b, err, ok) {
    var hasFal = falKeyOf(b);
    var hasFlow = flowKeyOf(b);
    return (
      '<section class="panel"><h1>Video keys</h1>' +
      '<p>This branch can generate with <strong>fal.ai</strong> (new) or the existing Google Flow / Veo key. Makeo does not give you a key.</p>' +

      '<div class="how-step"><h3><span class="n">1</span> fal.ai key (paid API — a new account is $0)</h3>' +
      '<p class="error">A fresh fal account and a new key do <strong>not</strong> include API credit. The website sandbox (free FLUX clips) is not the same as the API key. Until Billing shows a balance above $0, Generate with fal will say “Exhausted balance / User is locked”.</p>' +
      '<p class="click">1. Open <a href="https://fal.ai/dashboard/billing" target="_blank" rel="noopener"><strong>fal.ai/dashboard/billing</strong></a>. Add a card and top up at least <strong>$5</strong>. Wait until the page shows a positive balance.</p>' +
      '<p class="click">2. Then open <a href="https://fal.ai/dashboard/keys" target="_blank" rel="noopener"><strong>fal.ai/dashboard/keys</strong></a> → Create / Add key → paste it below → Save keys.</p>' +
      (hasFal
        ? '<p class="ok">fal.ai key on file (…' + esc(hasFal.slice(-4)) + ").</p>"
        : '<p class="muted">No fal.ai key yet.</p>') +
      "</div>" +

      '<div class="how-step"><h3><span class="n">2</span> Google Flow key (optional backup)</h3>' +
      '<p>Only needed if you want Veo through Google instead of fal. If Google says <strong>Failed to create project</strong>, use Plan B on the <a href="#/help">tutorial</a>.</p>' +
      (hasFlow
        ? '<p class="ok">Google Flow key on file (…' + esc(hasFlow.slice(-4)) + ").</p>"
        : '<p class="muted">No Google Flow key yet.</p>') +
      "</div>" +

      (!hasVideoKey(b) ? '<p class="error">Save at least one key. Generate is blocked until you do.</p>' : "") +
      (err ? '<p class="error">' + esc(err) + "</p>" : "") +
      (ok ? '<p class="ok">' + esc(ok) + "</p>" : "") +
      '<form id="keysForm">' +
      '<label>fal.ai API key</label>' +
      '<input name="falKey" type="password" autocomplete="off" placeholder="Paste your fal.ai key"/>' +
      '<label>Google Flow key</label>' +
      '<input name="flowKey" type="password" autocomplete="off" placeholder="Paste your Google Flow key (optional)"/>' +
      '<label>Flow project URL (optional)</label>' +
      '<input name="flowProjectUrl" value="' + esc(b.flowProjectUrl || "") + '" placeholder="https://labs.google/fx/tools/flow/project/…"/>' +
      '<div class="row"><button class="btn primary" type="submit">Save keys</button>' +
      (hasVideoKey(b) ? '<a class="btn ghost" href="#/brands/' + b.id + '/compose">Generate video</a>' : "") +
      "</div></form></section>"
    );
  }

  function igForm(b, err, ok) {
    return (
      '<section class="panel"><h1>Instagram · ' + esc(b.name) + "</h1>" +
      (b.igConnected
        ? '<p class="ok">Handle saved as @' + esc(b.igUsername || "brand") + ". This page does not send a token to Instagram.</p>"
        : '<p class="muted">Save a handle so the inbox can label the brand. A real Graph token is only used on your Makeo host.</p>') +
      (err ? '<p class="error">' + esc(err) + "</p>" : "") +
      (ok ? '<p class="ok">' + esc(ok) + "</p>" : "") +
      '<form id="igForm"><label>Instagram username</label>' +
      '<input name="username" required value="' + esc(b.igUsername || "") + '"/>' +
      '<label>Access token (not uploaded)</label><input name="token" type="password" placeholder="optional"/>' +
      '<div class="row"><button class="btn primary" type="submit">Save</button>' +
      '<a class="btn ghost" href="#/brands/' + b.id + '/compose">Generate next</a></div></form></section>'
    );
  }

  function compose(b, err) {
    var hasFal = falKeyOf(b);
    var hasFlow = flowKeyOf(b);
    var engineOpts = "";
    if (hasFlow) engineOpts += '<option value="veo">Google Veo 3.1 (uses your Flow key)</option>';
    if (hasFal) engineOpts += '<option value="fal">fal.ai (needs a paid fal balance)</option>';
    var modelOpts = Object.keys(falModels()).map(function (k) {
      return '<option value="' + k + '">' + esc(falModels()[k].label) + "</option>";
    }).join("");
    return (
      '<section class="panel"><h1>Generate for ' + esc(b.name) + "</h1>" +
      '<p class="muted">This branch can call <strong>fal.ai</strong> or Google Veo. Without a key or a prompt, nothing is generated and the missing items are listed.</p>' +
      (hasFal
        ? '<p class="ok">fal.ai key on file (…' + esc(hasFal.slice(-4)) + ").</p>"
        : '<p class="muted">No fal.ai key. <a href="#/brands/' + b.id + '/keys">Add one</a> after you have a paid fal balance.</p>') +
      (hasFal
        ? '<p class="muted">fal API is prepaid. If Generate says exhausted/locked, top up at <a href="https://fal.ai/dashboard/billing" target="_blank" rel="noopener">fal billing</a> or pick Google Veo below.</p>'
        : "") +
      (hasFlow
        ? '<p class="ok">Google Flow key on file (…' + esc(flowKeyOf(b).slice(-4)) + ").</p>"
        : "") +
      (!hasVideoKey(b)
        ? '<p class="error">No video key. <a href="#/brands/' + b.id + '/keys">Enter a fal.ai or Google Flow key</a> before generating.</p>'
        : "") +
      (err ? '<p class="error">' + err + "</p>" : "") +
      '<form id="composeForm">' +
      (engineOpts
        ? '<label>Engine</label><select name="engine" id="engine">' + engineOpts + "</select>"
        : "") +
      (hasFal
        ? '<label>fal model</label><select name="falModel" id="falModel">' + modelOpts + "</select>"
        : "") +
      '<label>Mode</label><select name="mode" id="mode">' +
      '<option value="custom">My own prompt</option>' +
      '<option value="trend">Topic from this brand’s pitch</option></select>' +
      '<label>Video prompt</label><textarea name="prompt" id="prompt" rows="4" placeholder="Describe the scene for ' + esc(b.name) + '…"></textarea>' +
      '<label>Caption (optional)</label><input name="caption" placeholder="' + esc(b.name) + '"/>' +
      '<div class="row"><button class="btn primary" type="submit" id="genBtn">Generate video</button>' +
      '<a class="btn ghost" href="#/brands/' + b.id + '/inbox">Inbox</a></div>' +
      '<p class="status" id="composeStatus"></p></form></section>' +
      catalogPanel(b)
    );
  }

  function catalogPanel(b) {
    return (
      '<section class="panel" id="catalogPanel" style="margin-top:20px">' +
      "<h2>Catalog try-on · Indian outfits</h2>" +
      '<p class="muted">A dedicated page: upload a model and a garment, send them to the Colab T4 in the background, keep working here.</p>' +
      '<div class="row">' +
      '<a class="btn primary" href="#/brands/' + b.id + '/catalog">Open catalog creator</a>' +
      '<button type="button" class="btn ghost" id="startColab">Start Colab worker</button>' +
      "</div>" +
      '<p class="status" id="colabStatus"></p></section>'
    );
  }

  function reel(b, j) {
    var src = clips[j.id] || j.videoUrl;
    if (src) {
      return '<div class="reel"><video src="' + src + '" controls playsinline></video></div>';
    }
    return "";
  }

  function missingHtml(list) {
    return "Video was not generated. Provide: <ul>" +
      list.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul>";
  }

  function inbox(s, b) {
    var jobs = s.jobs.filter(function (j) { return j.brandId === b.id; }).slice().reverse();
    if (!jobs.length) {
      return "<h1>Inbox · " + esc(b.name) + '</h1><p class="muted">Nothing yet. <a href="#/brands/' + b.id + '/compose">Generate a clip</a>.</p>';
    }
    return (
      "<h1>Inbox · " + esc(b.name) + "</h1>" +
      jobs.map(function (j) {
        var pill = j.status === "posted" ? "posted" : j.status === "rejected" ? "rej" : j.status === "failed" ? "rej" : "wait";
        var body = "";
        if (j.status === "failed") {
          body = '<p class="error">' + (j.error || "Video was not generated.") + "</p>" +
            '<p><a href="#/brands/' + b.id + '/compose">Back to generate</a></p>';
        } else if (j.status === "running") {
          body = '<p class="muted">Rendering the 8-second preview… ' + esc(j.progress || "") + "</p>";
        } else {
          body = reel(b, j);
          if (!clips[j.id] && !j.videoUrl) {
            body += '<p class="error">No video on this job. The preview is only kept until you refresh. Generate again if the player is empty.</p>';
          } else {
            body += "<p><strong>" + esc(j.topic) + "</strong><br/>" + esc(j.caption) + "</p>";
          }
          if (j.status === "awaiting_approval" && (clips[j.id] || j.videoUrl)) {
            body += '<form class="approveForm" data-id="' + j.id + '">' +
              '<label>Caption</label><textarea name="caption" rows="2">' + esc(j.caption) + "</textarea>" +
              '<div class="row"><button class="btn ok" name="act" value="approve" type="submit">Approve &amp; post</button>' +
              '<button class="btn no" name="act" value="reject" type="submit">Reject</button></div></form>';
          } else if (j.status === "awaiting_approval") {
            body += '<p class="error">Approve is locked because there is no video.</p>';
          }
          if (j.status === "publishing") body += '<p class="muted">Marking posted for @' + esc(b.igUsername || b.slug) + " (Instagram API is not called from this page).</p>";
          if (j.status === "posted") body += '<p class="ok">Marked posted for @' + esc(b.igUsername || b.slug) + ". Instagram was not called from this demo page.</p>";
          if (j.status === "rejected") body += "<p>Rejected. Nothing posted.</p>";
        }
        return '<div class="card"><span class="pill ' + pill + '">' + esc(j.status.replace(/_/g, " ")) +
          "</span>" + body + "</div>";
      }).join("")
    );
  }

  function bindAuth(kind) {
    var form = document.getElementById("authForm");
    if (!form) return;
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var email = form.email.value.trim().toLowerCase();
      var pass = form.password.value;
      hash(pass).then(function (h) {
        var s = state();
        if (s._saveError && kind === "signup") {
          render(shell(s, authForm("signup", "Could not save the account in this browser (private/incognito often blocks it). Try a normal window."), { landing: true }));
          bindAuth("signup");
          return;
        }
        if (kind === "signup") {
          if (s.users.some(function (u) { return u.email === email; })) {
            render(shell(s, authForm("signup", "That email already has an account on this browser. Use Sign in."), { landing: true }));
            bindAuth("signup");
            return;
          }
          var u = { id: uid(), email: email, pass: h };
          s.users.push(u);
          s.session = u.id;
          save(s);
          if (s._saveError) {
            render(shell(s, authForm("signup", "Account could not be stored: " + s._saveError), { landing: true }));
            bindAuth("signup");
            return;
          }
          go("/home");
        } else {
          var byEmail = s.users.filter(function (x) { return x.email === email; })[0];
          var found = s.users.filter(function (x) { return x.email === email && x.pass === h; })[0];
          var msg;
          if (!s.users.length) {
            msg = "No account exists in this browser yet. Click Create account (login does not use a server).";
          } else if (!byEmail) {
            msg = "No account for " + email + " in this browser. Create account first, or use the same browser where you signed up.";
          } else if (!found) {
            msg = "Password does not match the account saved in this browser.";
          }
          if (msg) {
            render(shell(s, authForm("login", msg), { landing: true }));
            bindAuth("login");
            return;
          }
          s.session = found.id;
          save(s);
          go("/home");
        }
      }).catch(function (err) {
        var s = state();
        render(shell(s, authForm(kind, err.message || "Login failed."), { landing: true }));
        bindAuth(kind);
      });
    });
  }

  function deleteBrand(id, name) {
    var label = name || "this brand";
    if (!window.confirm("Delete “" + label + "” and all its videos in this browser? This cannot be undone.")) {
      return;
    }
    var s = state();
    var b = brandBy(s, id);
    if (!b) {
      location.hash = "#/home";
      paint();
      return;
    }
    if (!ownBrand(s, b)) return;
    s.deletedBrandIds = s.deletedBrandIds || [];
    if (s.deletedBrandIds.indexOf(id) < 0) s.deletedBrandIds.push(id);
    s.brands = s.brands.filter(function (x) { return x.id !== id; });
    s.jobs = s.jobs.filter(function (j) { return j.brandId !== id; });
    save(s);
    PREV_KEYS.forEach(function (k) {
      try {
        var old = JSON.parse(localStorage.getItem(k) || "{}");
        if (old.brands) {
          old.brands = old.brands.filter(function (x) { return x.id !== id; });
          localStorage.setItem(k, JSON.stringify(old));
        }
      } catch (e) {}
    });
    location.hash = "#/home";
    paint();
  }

  function bindDeletes() {}

  function bindBrand(existing) {
    var form = document.getElementById("brandForm");
    if (!form) return;
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var s = state();
      var u = user(s);
      if (!u) return go("/login");
      Promise.all([
        fileToData(form.logo.files[0]),
        fileToData(form.splash.files[0], 900000)
      ]).then(function (files) {
        var slug = form.slug.value.trim().toLowerCase().replace(/[^a-z0-9-]+/g, "-");
        var rec = existing ? brandBy(s, existing.id) : { id: uid(), userId: u.id };
        rec.name = form.name.value.trim();
        rec.slug = slug;
        rec.pitch = form.pitch.value.trim();
        rec.hook = form.hook.value.trim();
        rec.tone = form.tone.value.trim();
        rec.region = form.region.value.trim();
        if (files[0]) rec.logo = files[0];
        if (files[1]) rec.splash = files[1];
        if (!existing) s.brands.push(rec);
        save(s);
        go("/brands/" + rec.id + "/keys");
      }).catch(function (err) {
        render(shell(s, brandForm(existing, err.message)));
        bindBrand(existing);
      });
    });
  }

  function bindKeys(b) {
    var form = document.getElementById("keysForm");
    if (!form) return;
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var fal = form.falKey.value.trim();
      var key = form.flowKey.value.trim();
      var s = state();
      var rec = brandBy(s, b.id);
      if (fal) rec.falKey = fal;
      if (key) {
        rec.flowKey = key;
        rec.geminiKey = key;
      }
      rec.flowProjectUrl = form.flowProjectUrl.value.trim();
      if (!hasVideoKey(rec)) {
        render(shell(s, keysForm(rec, "Paste a fal.ai key or a Google Flow key. Generate will not run without one.")));
        bindKeys(rec);
        return;
      }
      save(s);
      render(shell(s, keysForm(rec, null, "Key saved. You can generate a video now.")));
      bindKeys(rec);
    });
  }

  function bindIg(b) {
    var form = document.getElementById("igForm");
    if (!form) return;
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var s = state();
      var rec = brandBy(s, b.id);
      rec.igUsername = form.username.value.trim().replace(/^@/, "");
      rec.igConnected = true;
      save(s);
      render(shell(s, igForm(rec, null, "Saved. Next: generate a video.")));
      bindIg(rec);
    });
  }

  function bindCompose(b) {
    var form = document.getElementById("composeForm");
    var mode = document.getElementById("mode");
    var prompt = document.getElementById("prompt");
    var status = document.getElementById("composeStatus");
    var btn = document.getElementById("genBtn");
    if (!form) {
      bindCatalog();
      return;
    }
    function sync() { prompt.disabled = mode.value !== "custom"; }
    mode.addEventListener("change", sync);
    sync();
    var engineSel = document.getElementById("engine");
    var falSel = document.getElementById("falModel");
    if (engineSel && falSel) {
      function syncEngine() { falSel.disabled = engineSel.value !== "fal"; }
      engineSel.addEventListener("change", syncEngine);
      syncEngine();
    }
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var custom = prompt.value.trim();
      var miss = missingForVideo(b, mode.value, custom);
      if (miss.length) {
        render(shell(state(), compose(b, missingHtml(miss))));
        bindCompose(b);
        return;
      }
      btn.disabled = true;
      var line = sceneText(b, mode.value, custom);
      var caption = form.caption.value.trim() || (b.name + (b.hook ? " — " + b.hook : ""));
      var engineEl = document.getElementById("engine");
      var falModelEl = document.getElementById("falModel");
      var engine = engineEl ? engineEl.value : (falKeyOf(b) ? "fal" : "veo");
      var falModel = falModelEl ? falModelEl.value : "ltx-fast";
      var run;
      if (engine === "fal") {
        status.textContent = "Starting fal.ai…";
        run = generateFal(falKeyOf(b), line, falModel, function (msg) {
          if (status) status.textContent = msg;
        });
      } else {
        status.textContent = "Starting Veo 3.1 with your Gemini key…";
        run = generateVeo(flowKeyOf(b), line, function (msg) {
          if (status) status.textContent = msg;
        });
      }
      run.then(function (url) {
        var s = state();
        var u = user(s);
        var job = {
          id: uid(),
          userId: u.id,
          brandId: b.id,
          status: "awaiting_approval",
          source: mode.value,
          topic: mode.value === "custom" ? "Your prompt" : "From " + b.name + " pitch",
          prompt: line,
          caption: caption
        };
        clips[job.id] = url;
        s.jobs.push(job);
        save(s);
        go("/brands/" + b.id + "/inbox");
      }).catch(function (err) {
        var s = state();
        var job = {
          id: uid(),
          userId: user(s).id,
          brandId: b.id,
          status: "failed",
          topic: "Not generated",
          caption: "",
          error: "Video was not generated. " + (err && err.message
            ? (err.message.indexOf("Failed to fetch") >= 0
              ? "The browser could not reach the video API (blocked or offline). Confirm the key and that you opened this page over https."
              : err.message)
            : "Unknown error.")
        };
        s.jobs.push(job);
        save(s);
        render(shell(s, compose(b, esc(job.error))));
        bindCompose(b);
      });
    });
    bindCatalog();
  }

  function bindCatalog() {
    var btn = document.getElementById("startColab");
    var status = document.getElementById("colabStatus");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var tab = window.open(COLAB_NOTEBOOK, "makeo-colab");
      if (status) {
        status.innerHTML = tab
          ? '<span class="ok">Colab is in another tab. This site is still running. In Colab: pick <strong>T4 GPU</strong>, then <strong>Runtime → Run all</strong>. Stay here until it asks for photos.</span>'
          : '<span class="error">The browser blocked the new tab. Allow pop-ups, or <a href="' +
            COLAB_NOTEBOOK +
            '" target="_blank" rel="noopener">open Colab yourself</a>.</span>';
      }
      try { sessionStorage.setItem("makeo-colab-launched", String(Date.now())); } catch (e) {}
    });
  }

  function cleanWorkerUrl(raw) {
    var u = String(raw || "").replace(/[\u200b\u200c\u200d\ufeff]/g, "").trim();
    var colab = u.match(/https:\/\/[a-z0-9.-]+\.colab\.dev/i);
    if (colab) return colab[0].replace(/\/+$/, "");
    var guc = u.match(/https:\/\/[a-z0-9.-]+\.googleusercontent\.com/i);
    if (guc) return guc[0].replace(/\/+$/, "");
    var cf = u.match(/https:\/\/[a-z0-9-]+\.trycloudflare\.com/i);
    if (cf) return cf[0];
    u = u.replace(/^[`'<\[]+|[>`'\]]+$/g, "");
    u = u.replace(/\s+/g, "");
    u = u.replace(/\/health\/?$/i, "");
    u = u.replace(/\/+$/, "");
    return u;
  }

  function workerUrlOf(b) {
    return cleanWorkerUrl(b && b.catalogWorkerUrl);
  }

  function workerUrlError(raw) {
    var u = cleanWorkerUrl(raw);
    if (!u) {
      return "Paste the worker URL that loads JSON in a tab — usually https://….colab.dev";
    }
    var low = u.toLowerCase();
    if (low.indexOf("colab.research.google.com") >= 0 || low.indexOf("colab.google.com") >= 0) {
      return "That is the Colab notebook tab, not the worker. Copy the https://….colab.dev line.";
    }
    if (low.indexOf("github.com") >= 0 || low.indexOf("githubusercontent.com") >= 0) {
      return "That is a GitHub link. Paste the https://….colab.dev worker URL.";
    }
    var okHost = (
      low.indexOf("colab.dev") >= 0 ||
      low.indexOf("googleusercontent.com") >= 0 ||
      low.indexOf("trycloudflare.com") >= 0 ||
      low.indexOf("ngrok") >= 0 ||
      low.indexOf("loca.lt") >= 0 ||
      low.indexOf("gradio.live") >= 0 ||
      low.indexOf("localhost.run") >= 0 ||
      low.indexOf("lhr.life") >= 0
    );
    if (!okHost) {
      return "This does not look like a worker URL. Paste the https://….colab.dev link that shows {\"ok\":true}.";
    }
    if (low.indexOf("http://") === 0) {
      return "Use the https:// worker URL. This site cannot call a plain http worker.";
    }
    return "";
  }

  function catalogPage(b, note) {
    var shots = (b.catalogShots || []).slice().reverse();
    var gallery = shots.length
      ? '<h2>Looks</h2><div class="cat-shots">' + shots.map(function (s) {
          return '<a href="' + s.url + '" download="makeo-catalog-' + esc(s.id) + '.png" title="' +
            esc(s.category || "") + '"><img src="' + s.url + '" alt="catalog look"/></a>';
        }).join("") + "</div>"
      : '<p class="muted">No looks yet. Connect Colab, drop a model and a garment, then create.</p>';
    return (
      '<div class="cat-head">' +
      "<div><h1>Catalog · " + esc(b.name) + "</h1>" +
      '<p class="muted">Put this brand’s real outfit on a model. Colab stays in the other tab and does the GPU work.</p></div>' +
      '<div><span class="worker bad" id="workerPill">Worker offline</span></div></div>' +
      (note ? '<p class="banner">' + note + "</p>" : "") +
      '<section class="panel">' +
      '<label>Colab worker URL</label>' +
      '<div class="row worker-row">' +
      '<input id="workerUrl" placeholder="https://….colab.dev" value="' + esc(b.catalogWorkerUrl || "") + '"/>' +
      '<button type="button" class="btn ghost" id="saveWorker">Save</button>' +
      '<a class="btn ghost" id="openWorker" target="makeo-colab-worker" rel="noopener" href="#">Open worker tab</a>' +
      '<button type="button" class="btn ghost" id="startColab">Start Colab</button>' +
      "</div>" +
      '<p class="muted">Paste the <code>https://….colab.dev</code> URL that shows <code>{"ok":true}</code>. Do not use a trycloudflare link if that tab shows Cloudflare error 1033. Save, then Create look.</p>' +
      '<div class="cat-grid">' +
      '<div><label>Model</label><div class="drop" id="dropPerson"><span class="hint">Indian model · full body or 3/4</span>' +
      '<input type="file" id="filePerson" accept="image/*"/></div></div>' +
      '<div><label>Garment</label><div class="drop" id="dropGarment"><span class="hint">Flat-lay or hanger · show pallu / border</span>' +
      '<input type="file" id="fileGarment" accept="image/*"/></div></div>' +
      '<div><label>Result</label><div class="cat-result" id="catResult"><span class="muted">Waiting</span></div></div>' +
      "</div>" +
      '<label>Outfit type</label><div class="chips" id="catCategory">' +
      '<button type="button" class="chip on" data-v="one-pieces">Saree / anarkali</button>' +
      '<button type="button" class="chip" data-v="tops">Kurti / blouse</button>' +
      '<button type="button" class="chip" data-v="bottoms">Palazzo / salwar</button></div>' +
      '<label>Garment photo</label><div class="chips" id="catPhotoType">' +
      '<button type="button" class="chip on" data-v="flat-lay">Flat-lay / hanger</button>' +
      '<button type="button" class="chip" data-v="model">Already on a person</button></div>' +
      '<div class="row">' +
      '<button type="button" class="btn primary" id="catGo">Create look</button>' +
      '<a class="btn ghost" href="#/brands/' + b.id + '/compose">Back to video</a>' +
      "</div>" +
      '<p class="status" id="catStatus"></p></section>' +
      gallery
    );
  }

  function bindDrop(inputId, dropId) {
    var input = document.getElementById(inputId);
    var drop = document.getElementById(dropId);
    if (!input || !drop) return;
    function show() {
      var f = input.files && input.files[0];
      var old = drop.querySelector("img");
      if (old) old.remove();
      if (!f) { drop.classList.remove("has"); return; }
      var img = document.createElement("img");
      img.alt = "";
      img.src = URL.createObjectURL(f);
      drop.appendChild(img);
      drop.classList.add("has");
    }
    input.addEventListener("change", show);
  }

  function bindChips(id, onChange) {
    var root = document.getElementById(id);
    if (!root) return;
    root.addEventListener("click", function (e) {
      var btn = e.target.closest(".chip");
      if (!btn) return;
      root.querySelectorAll(".chip").forEach(function (c) { c.classList.toggle("on", c === btn); });
      if (onChange) onChange(btn.getAttribute("data-v"));
    });
  }

  function chipValue(id) {
    var on = document.querySelector("#" + id + " .chip.on");
    return on ? on.getAttribute("data-v") : "";
  }

  function pingWorker(url, pill) {
    if (!pill) return;
    if (!url) {
      pill.className = "worker bad";
      pill.textContent = "No worker URL";
      return;
    }
    fetch(url + "/health", { mode: "cors", cache: "no-store", credentials: "omit" }).then(function (r) { return r.json(); }).then(function (d) {
      pill.className = "worker " + (d && d.ok ? "ok" : "bad");
      pill.textContent = d && d.ok ? "Colab worker live" : "Worker not ready";
    }).catch(function () {
      pill.className = "worker bad";
      pill.textContent = "Open worker URL once";
    });
  }

  function workerBlockedHtml(url) {
    return '<span class="error">Colab is running, but this browser has not been allowed through Cloudflare yet. ' +
      'Open <a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(url) + "</a> " +
      "in a new tab, click through the warning until you see JSON like <code>{\"ok\":true}</code>, " +
      "then come back and try Create look again. Do not restart Colab.</span>";
  }

  function tryonViaWorkerUi(base, payload) {
    return new Promise(function (resolve, reject) {
      var origin;
      try { origin = new URL(base).origin; } catch (e) {
        reject(new Error("Worker URL is not valid."));
        return;
      }
      var w = window.open(base + "/ui", "makeo-colab-worker");
      if (!w) {
        reject(new Error("The worker tab was blocked. Allow pop-ups for this site, click Open worker tab, then Create look again."));
        return;
      }
      var done = false;
      var sent = false;
      function finish(err, dataUrl) {
        if (done) return;
        done = true;
        window.removeEventListener("message", onMsg);
        clearInterval(timer);
        clearTimeout(limit);
        if (err) reject(err);
        else resolve(dataUrl);
      }
      function onMsg(e) {
        if (e.origin !== origin) return;
        var d = e.data || {};
        if ((d.type === "worker-ui-ready" || d.type === "pong") && !sent) {
          sent = true;
          w.postMessage({ type: "tryon", payload: payload }, origin);
          return;
        }
        if (d.type === "result") {
          if (d.ok && d.dataUrl) finish(null, d.dataUrl);
          else finish(new Error(d.error || "try-on failed"));
        }
      }
      window.addEventListener("message", onMsg);
      var timer = setInterval(function () {
        try { w.postMessage({ type: "ping" }, origin); } catch (e) {}
      }, 800);
      var limit = setTimeout(function () {
        finish(new Error("Worker tab did not respond. If it shows {\"detail\":\"Not Found\"}, that Colab worker is too old. In Colab stop only the worker cell, run it again, wait for (json-v4), paste the new URL, then try again."));
      }, 4 * 60 * 1000);
    });
  }

  function fileToDataUrl(file, maxEdge) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      var url = URL.createObjectURL(file);
      img.onload = function () {
        var w = img.naturalWidth || 1;
        var h = img.naturalHeight || 1;
        var scale = Math.min(1, (maxEdge || 1280) / Math.max(w, h));
        var canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(w * scale));
        canvas.height = Math.max(1, Math.round(h * scale));
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);
        resolve(canvas.toDataURL("image/jpeg", 0.9));
      };
      img.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error("Could not read " + ((file && file.name) || "image")));
      };
      img.src = url;
    });
  }

  function bindCatalogPage(b) {
    bindCatalog();
    bindDrop("filePerson", "dropPerson");
    bindDrop("fileGarment", "dropGarment");
    bindChips("catCategory");
    bindChips("catPhotoType");
    var pill = document.getElementById("workerPill");
    var urlInput = document.getElementById("workerUrl");
    var status = document.getElementById("catStatus");
    pingWorker(workerUrlOf(b), pill);
    if (window.__catPing) clearInterval(window.__catPing);
    window.__catPing = setInterval(function () { pingWorker(workerUrlOf(b), pill); }, 8000);

    var saveBtn = document.getElementById("saveWorker");
    var openBtn = document.getElementById("openWorker");
    function syncOpen() {
      var u = cleanWorkerUrl(urlInput && urlInput.value);
      if (openBtn) openBtn.href = u ? u + "/ui" : "#";
    }
    if (urlInput) urlInput.addEventListener("input", syncOpen);
    syncOpen();
    if (saveBtn) {
      saveBtn.addEventListener("click", function () {
        var typed = cleanWorkerUrl(urlInput.value);
        if (urlInput) urlInput.value = typed;
        var why = workerUrlError(typed);
        if (why) {
          if (status) status.innerHTML = '<span class="error">' + esc(why) + "</span>";
          return;
        }
        var s = state();
        var rec = brandBy(s, b.id);
        rec.catalogWorkerUrl = typed;
        save(s);
        b = rec;
        syncOpen();
        pingWorker(workerUrlOf(b), pill);
        try { window.open(typed + "/ui", "makeo-colab-worker"); } catch (e) {}
        if (status) {
          var hint = typed.toLowerCase().indexOf("trycloudflare.com") >= 0
            ? '<span class="error">Saved, but trycloudflare often shows error 1033. Paste the <code>colab.dev</code> URL that already loads JSON, then Save again.</span>'
            : '<span class="ok">Saved. The worker tab should say <strong>Waiting for Makeo</strong> (or JSON). Close any Cloudflare 1033 tab. Then Create look.</span>';
          status.innerHTML = hint;
        }
      });
    }

    var go = document.getElementById("catGo");
    if (!go) return;
    go.addEventListener("click", function () {
      var s = state();
      var rec = brandBy(s, b.id);
      var base = workerUrlOf(rec);
      var person = document.getElementById("filePerson").files[0];
      var garment = document.getElementById("fileGarment").files[0];
      var why = workerUrlError(base);
      if (why) {
        status.innerHTML = '<span class="error">' + esc(why) + "</span>";
        return;
      }
      if (!person || !garment) {
        status.innerHTML = '<span class="error">Add a model photo and a garment photo.</span>';
        return;
      }
      go.disabled = true;
      status.textContent = "Sending to Colab through the worker tab… 1–3 minutes. Click through Cloudflare there if it appears.";
      Promise.all([fileToDataUrl(person, 1280), fileToDataUrl(garment, 1280)])
        .then(function (pair) {
          return tryonViaWorkerUi(base, {
            person: pair[0],
            garment: pair[1],
            category: chipValue("catCategory") || "one-pieces",
            garment_photo_type: chipValue("catPhotoType") || "flat-lay",
            steps: 20
          });
        })
        .then(function (dataUrl) {
          var st = state();
          var brand = brandBy(st, b.id);
          brand.catalogShots = brand.catalogShots || [];
          var shot = {
            id: uid(),
            url: dataUrl,
            category: chipValue("catCategory") || "one-pieces",
            createdAt: Date.now()
          };
          brand.catalogShots.push(shot);
          if (brand.catalogShots.length > 12) brand.catalogShots = brand.catalogShots.slice(-12);
          save(st);
          var box = document.getElementById("catResult");
          if (box) box.innerHTML = '<img src="' + dataUrl + '" alt="result"/>';
          status.innerHTML = '<span class="ok">Look ready. Saved to this brand’s catalog.</span>';
          go.disabled = false;
          render(shell(st, catalogPage(brand)));
          bindCatalogPage(brand);
        })
        .catch(function (err) {
          go.disabled = false;
          var msg = (err && err.message) || "Could not reach Colab.";
          if (msg.indexOf("Failed to fetch") >= 0 || msg.indexOf("NetworkError") >= 0 || msg.indexOf("Load failed") >= 0) {
            status.innerHTML = workerBlockedHtml(base);
            return;
          }
          status.innerHTML = '<span class="error">' + esc(msg) + "</span>";
        });
    });
  }

  function bindInbox(b) {
    document.querySelectorAll(".approveForm").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        var act = (e.submitter && e.submitter.value) || "approve";
        var s = state();
        var j = jobBy(s, form.getAttribute("data-id"));
        if (!j) return;
        if (act === "approve" && !clips[j.id] && !j.videoUrl) {
          j.status = "failed";
          j.error = "Video was not generated. Approve is not available.";
          save(s);
          paint();
          return;
        }
        j.caption = form.caption.value.trim() || j.caption;
        if (act === "reject") j.status = "rejected";
        else {
          j.status = "publishing";
          j.postedAt = Date.now() + 1400;
        }
        save(s);
        paint();
      });
    });
  }

  var timer = null;
  function render(html) { document.getElementById("app").innerHTML = html; }

  function paint() {
    var s = state();
    advanceJobs(s);
    save(s);
    var path = route();
    var parts = path.split("/").filter(Boolean);

    if (path === "/logout") { s.session = null; save(s); go("/"); return; }
    if (path === "/" || path === "/how") {
      render(shell(s, landing(), { landing: true }));
      return;
    }
    if (path === "/help") {
      render(shell(s, tutorial(), { landing: !user(s) }));
      return;
    }
    if (path === "/signup") {
      render(shell(s, authForm("signup"), { landing: true }));
      bindAuth("signup");
      return;
    }
    if (path === "/login") {
      render(shell(s, authForm("login"), { landing: true }));
      bindAuth("login");
      return;
    }
    if (!user(s)) { go("/login"); return; }
    if (path === "/home") { render(shell(s, home(s))); bindDeletes(); return; }
    if (path === "/brands/new") {
      render(shell(s, brandForm(null)));
      bindBrand(null);
      return;
    }
    if (parts[0] === "brands" && parts[1]) {
      var b = brandBy(s, parts[1]);
      if (!ownBrand(s, b)) {
        render(shell(s, '<p class="error">Brand not found.</p>'));
        return;
      }
      if (parts[2] === "keys") { render(shell(s, keysForm(b))); bindKeys(b); return; }
      if (parts[2] === "instagram") { render(shell(s, igForm(b))); bindIg(b); return; }
      if (parts[2] === "compose") {
        render(shell(s, compose(b)));
        bindCompose(b);
        return;
      }
      if (parts[2] === "catalog") {
        render(shell(s, catalogPage(b)));
        bindCatalogPage(b);
        return;
      }
      if (parts[2] === "inbox") {
        render(shell(s, inbox(s, b)));
        bindInbox(b);
        var pending = s.jobs.some(function (j) {
          return j.brandId === b.id && j.status === "publishing";
        });
        if (pending) { clearTimeout(timer); timer = setTimeout(paint, 400); }
        return;
      }
      render(shell(s, brandForm(b)));
      bindBrand(b);
      bindDeletes();
      return;
    }
    render(shell(s, landing(), { landing: true }));
  }

  window.addEventListener("hashchange", paint);
  document.addEventListener("click", function (e) {
    var btn = e.target && e.target.closest && e.target.closest(".deleteBrand");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    deleteBrand(btn.getAttribute("data-id"), btn.getAttribute("data-name"));
  });
  paint();
})();
