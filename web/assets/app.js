(function () {
  var KEY = "makeo-demo-v2";
  var PREV_KEYS = ["makeo-demo-v1"];
  var clips = {};

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
    PREV_KEYS.forEach(function (k) {
      try {
        var old = JSON.parse(localStorage.getItem(k) || "{}");
        mergeUsers(s.users, old.users);
        (old.brands || []).forEach(function (b) {
          if (b && b.id && !s.brands.some(function (x) { return x.id === b.id; })) s.brands.push(b);
        });
      } catch (e) {}
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
    if (!flowKeyOf(brand)) {
      miss.push("your Google Flow key (Brand → Google Flow key). Create one at aistudio.google.com/apikey and paste it — Generate will not run without it.");
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
      ? '<a href="#/how">How it works</a><a href="#/signup">Create account</a><a href="#/login">Sign in</a>'
      : (u
        ? '<a href="#/home">Home</a><span class="who">' + esc(u.email) + "</span><a href=\"#/logout\">Log out</a>"
        : '<a href="#/login">Sign in</a><a href="#/signup">Create account</a>');
    return (
      '<header class="top"><a class="brand" href="#/"><img src="assets/icon.svg" width="28" height="28" alt=""/><span>Makeo</span></a><nav>' +
      nav + "</nav></header><main>" + inner + "</main>" +
      "<footer><p>Live at <a href=\"https://tmai-tech.github.io/Makeo/\">tmai-tech.github.io/Makeo</a></p></footer>"
    );
  }

  function landing() {
    return (
      '<section class="hero">' +
      '<p class="eyebrow">Create account · Add brand · Generate a preview · Approve</p>' +
      "<h1>Your brand. Your prompt.<br/>An 8-second Reel.</h1>" +
      '<p class="lead">Sign up, set up a brand, write a prompt (or a pitch for a topic), then watch an 8-second preview. Approve only after the clip exists. Nothing posts without a click.</p>' +
      '<div class="actions"><a class="btn primary" href="#/signup">Create an account</a>' +
      '<a class="btn ghost" href="#/login">I already have one</a></div></section>' +
      '<ol class="pipe" id="how"><li><strong>1. Account</strong><span>Email + password, this browser only</span></li>' +
      "<li><strong>2. Brand</strong><span>Name, pitch, hook, optional logo</span></li>" +
      "<li><strong>3. Generate</strong><span>Needs your prompt, or a pitch/hook for a topic</span></li>" +
      "<li><strong>4. Approve</strong><span>Only after a preview video is ready</span></li></ol>"
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
            '<div class="row"><a href="#/brands/' + b.id + '/keys">Flow key</a>' +
            ' · <a href="#/brands/' + b.id + '/compose">Generate</a>' +
            ' · <a href="#/brands/' + b.id + '/inbox">Inbox</a>' +
            ' · <a href="#/brands/' + b.id + '/instagram">Instagram</a></div></div>';
        }).join("")
      : '<p class="muted">No brands yet. Create one to start.</p>';
    return (
      '<div class="banner">Before Generate works, open the brand and enter your <strong>Google Flow key</strong>. Without that key, no video is created.</div>' +
      "<h1>Your brands</h1>" + cards +
      '<div class="actions"><a class="btn primary" href="#/brands/new">New brand</a></div>'
    );
  }

  function brandForm(b, err) {
    b = b || {};
    return (
      '<section class="panel"><h1>' + (b.id ? "Edit " + esc(b.name) : "New brand") + "</h1>" +
      '<p class="muted">Name is required. You will be asked for your Google Flow key next — Generate will not run without it.</p>' +
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
      '<div class="row"><button class="btn primary" type="submit">Save and enter Flow key</button></div></form>' +
      (b.id
        ? '<p><a href="#/brands/' + b.id + '/keys">Google Flow key</a> · <a href="#/brands/' + b.id + '/compose">Generate</a> · <a href="#/brands/' + b.id + '/inbox">Inbox</a></p>'
        : "") +
      "</section>"
    );
  }

  function keysForm(b, err, ok) {
    var has = flowKeyOf(b);
    return (
      '<section class="panel"><h1>Enter your Google Flow key</h1>' +
      '<p>Makeo generates video with <strong>your</strong> Google Flow / Gemini key. We do not provide one. Create a key at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">aistudio.google.com/apikey</a>, then paste it here. It stays in this browser only.</p>' +
      (has ? '<p class="ok">A key is saved (…' + esc(has.slice(-4)) + "). Paste a new one to replace it.</p>" : '<p class="error">No Google Flow key on this brand yet. Generate is blocked until you save one.</p>') +
      (err ? '<p class="error">' + esc(err) + "</p>" : "") +
      (ok ? '<p class="ok">' + esc(ok) + "</p>" : "") +
      '<form id="keysForm">' +
      '<label>Google Flow key</label>' +
      '<input name="flowKey" type="password" autocomplete="off" placeholder="Paste your Google Flow key" ' + (has ? "" : "required") + "/>" +
      '<label>Flow project URL (optional)</label>' +
      '<input name="flowProjectUrl" value="' + esc(b.flowProjectUrl || "") + '" placeholder="https://labs.google/fx/tools/flow/project/…"/>' +
      '<div class="row"><button class="btn primary" type="submit">Save Google Flow key</button>' +
      (has ? '<a class="btn ghost" href="#/brands/' + b.id + '/compose">Generate video</a>' : "") +
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
    return (
      '<section class="panel"><h1>Generate for ' + esc(b.name) + "</h1>" +
      '<p class="muted">This calls <strong>Veo 3.1</strong> with the Gemini key saved on the brand. Google Flow’s website is not opened from here. Without a key or a prompt, nothing is generated and the missing items are listed.</p>' +
      (flowKeyOf(b)
        ? '<p class="ok">Google Flow key on file (…' + esc(flowKeyOf(b).slice(-4)) + ').</p>'
        : '<p class="error">No Google Flow key. <a href="#/brands/' + b.id + '/keys">Enter your Google Flow key</a> before generating.</p>') +
      (err ? '<p class="error">' + err + "</p>" : "") +
      '<form id="composeForm"><label>Mode</label><select name="mode" id="mode">' +
      '<option value="custom">My own prompt</option>' +
      '<option value="trend">Topic from this brand’s pitch</option></select>' +
      '<label>Video prompt</label><textarea name="prompt" id="prompt" rows="4" placeholder="Describe the 8-second scene for ' + esc(b.name) + '…"></textarea>' +
      '<label>Caption (optional)</label><input name="caption" placeholder="' + esc(b.name) + '"/>' +
      '<div class="row"><button class="btn primary" type="submit" id="genBtn">Generate video</button>' +
      '<a class="btn ghost" href="#/brands/' + b.id + '/inbox">Inbox</a></div>' +
      '<p class="status" id="composeStatus"></p></form></section>'
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
      var key = form.flowKey.value.trim();
      var s = state();
      var rec = brandBy(s, b.id);
      if (!key && !flowKeyOf(rec)) {
        render(shell(s, keysForm(rec, "Paste your Google Flow key. Generate will not run without it.")));
        bindKeys(rec);
        return;
      }
      if (key) {
        rec.flowKey = key;
        rec.geminiKey = key;
      }
      rec.flowProjectUrl = form.flowProjectUrl.value.trim();
      save(s);
      render(shell(s, keysForm(rec, null, "Google Flow key saved. You can generate a video now.")));
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
    if (!form) return;
    function sync() { prompt.disabled = mode.value !== "custom"; }
    mode.addEventListener("change", sync);
    sync();
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
      status.textContent = "Starting Veo 3.1 with your Gemini key…";
      generateVeo(flowKeyOf(b), line, function (msg) {
        if (status) status.textContent = msg;
      }).then(function (url) {
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
              ? "The browser could not reach Google’s Veo API (blocked or offline). Confirm the Gemini key and that you opened https://tmai-tech.github.io/Makeo/"
              : err.message)
            : "Unknown error.")
        };
        s.jobs.push(job);
        save(s);
        render(shell(s, compose(b, esc(job.error))));
        bindCompose(b);
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
    if (path === "/home") { render(shell(s, home(s))); return; }
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
        if (!flowKeyOf(b)) {
          render(shell(s, keysForm(b, "Enter your Google Flow key before generating a video.")));
          bindKeys(b);
          return;
        }
        render(shell(s, compose(b)));
        bindCompose(b);
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
      return;
    }
    render(shell(s, landing(), { landing: true }));
  }

  window.addEventListener("hashchange", paint);
  paint();
})();
