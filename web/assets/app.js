(function () {
  var KEY = "makeo-demo-v1";
  var TRENDS = [
    { topic: "Side hustle payday", why: "Gen Z wants cash from the same reels they already post", caption: "Same reels. Real payout. {name} 💸" },
    { topic: "Creator coins going live", why: "Gifts-to-bank is the hook", caption: "Gifts hit UPI. Only on {name} ✨" },
    { topic: "Weekend drop culture", why: "Short vertical, FOMO, brand native", caption: "Drop it. Earn it. {name} 🔥" }
  ];

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY) || "{}"); }
    catch (e) { return {}; }
  }
  function save(s) { localStorage.setItem(KEY, JSON.stringify(s)); }
  function state() {
    var s = load();
    s.users = s.users || [];
    s.brands = s.brands || [];
    s.jobs = s.jobs || [];
    s.session = s.session || null;
    return s;
  }
  function uid() { return Math.random().toString(36).slice(2, 10) + Date.now().toString(36); }
  function hash(str) {
    return crypto.subtle.digest("SHA-256", new TextEncoder().encode(str)).then(function (buf) {
      return Array.from(new Uint8Array(buf)).map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
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
  function advanceJobs(s) {
    var now = Date.now();
    s.jobs.forEach(function (j) {
      if (j.status === "queued" || j.status === "running") {
        if (now >= (j.readyAt || 0)) j.status = "awaiting_approval";
        else j.status = "running";
      }
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

  function shell(s, inner, opts) {
    opts = opts || {};
    var u = user(s);
    var nav = opts.landing
      ? '<a href="#/how">How it works</a><a href="#/signup">Create account</a><a href="#/login">Sign in</a>'
      : (u
        ? '<a href="#/home">Home</a><span class="who">' + esc(u.email) + '</span><a href="#/logout">Log out</a>'
        : '<a href="#/login">Sign in</a><a href="#/signup">Create account</a>');
    return (
      '<header class="top"><a class="brand" href="#/"><img src="assets/icon.svg" width="28" height="28" alt=""/><span>Makeo</span></a><nav>' +
      nav + "</nav></header><main>" + inner + "</main>" +
      '<footer><p>Live at <a href="https://tmai-tech.github.io/Makeo/">tmai-tech.github.io/Makeo</a></p></footer>'
    );
  }

  function landing() {
    return (
      '<section class="hero">' +
      '<p class="eyebrow">Create account · Add brand · Approve before anything posts</p>' +
      "<h1>Your brand. Your prompt.<br/>An 8-second Reel.</h1>" +
      '<p class="lead">Walk the full Makeo flow in this demo: sign up, set up a brand, generate, then approve. Nothing posts without a click.</p>' +
      '<div class="actions"><a class="btn primary" href="#/signup">Create an account</a>' +
      '<a class="btn ghost" href="#/login">I already have one</a></div></section>' +
      '<ol class="pipe" id="how"><li><strong>1. Account</strong><span>Email + password, stored only in this browser</span></li>' +
      "<li><strong>2. Brand</strong><span>Pitch, hook, assets, Instagram</span></li>" +
      "<li><strong>3. Compose</strong><span>Your prompt or today’s trend</span></li>" +
      "<li><strong>4. Approve</strong><span>Watch the preview. Post or reject</span></li></ol>"
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
      '<p class="muted">This public demo keeps the account in your browser. A host worker is still required for real Veo + Instagram.</p>' +
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
            '<div class="row"><a href="#/brands/' + b.id + '/compose">Generate</a>' +
            ' · <a href="#/brands/' + b.id + '/inbox">Inbox</a>' +
            ' · <a href="#/brands/' + b.id + '/instagram">Instagram</a></div></div>';
        }).join("")
      : '<p class="muted">No brands yet. Create one to start the demo.</p>';
    return (
      '<div class="banner">Demo session on this device. Create a brand, generate a clip, then approve it in the inbox.</div>' +
      "<h1>Your brands</h1>" + cards +
      '<div class="actions"><a class="btn primary" href="#/brands/new">New brand</a></div>'
    );
  }

  function brandForm(b, err) {
    b = b || {};
    return (
      '<section class="panel"><h1>' + (b.id ? "Edit " + esc(b.name) : "New brand") + "</h1>" +
      (err ? '<p class="error">' + esc(err) + "</p>" : "") +
      '<form id="brandForm">' +
      '<label>Name</label><input name="name" required value="' + esc(b.name || "") + '"/>' +
      '<label>Slug</label><input name="slug" required value="' + esc(b.slug || "") + '" placeholder="makersnook"/>' +
      '<label>Pitch — what you sell</label><textarea name="pitch" rows="3">' + esc(b.pitch || "") + "</textarea>" +
      '<label>Spoken hook</label><textarea name="hook" rows="2">' + esc(b.hook || "") + "</textarea>" +
      '<label>Tone</label><input name="tone" value="' + esc(b.tone || "") + '" placeholder="Gen Z Hinglish"/>' +
      '<label>Region</label><input name="region" value="' + esc(b.region || "IN") + '"/>' +
      '<label>Logo</label><input name="logo" type="file" accept="image/*"/>' +
      (b.logo ? '<p><img class="logo-preview" src="' + b.logo + '" alt="logo"/></p>' : "") +
      '<label>Splash / end-card</label><input name="splash" type="file" accept="image/*,.gif"/>' +
      '<div class="row"><button class="btn primary" type="submit">Save brand</button></div></form>' +
      (b.id
        ? '<p><a href="#/brands/' + b.id + '/compose">Generate</a> · <a href="#/brands/' + b.id + '/inbox">Inbox</a> · <a href="#/brands/' + b.id + '/instagram">Instagram</a></p>'
        : "") +
      "</section>"
    );
  }

  function igForm(b, err, ok) {
    return (
      '<section class="panel"><h1>Instagram · ' + esc(b.name) + "</h1>" +
      (b.igConnected
        ? '<p class="ok">Connected as @' + esc(b.igUsername || "brand") + ". Token is not sent anywhere — demo only stores the handle.</p>"
        : '<p class="muted">Paste a handle for the demo. A real Graph token is only used on your Makeo worker host.</p>') +
      (err ? '<p class="error">' + esc(err) + "</p>" : "") +
      (ok ? '<p class="ok">' + esc(ok) + "</p>" : "") +
      '<form id="igForm"><label>Instagram username</label>' +
      '<input name="username" required value="' + esc(b.igUsername || "") + '" placeholder="makersnook"/>' +
      '<label>Access token (optional in demo)</label><input name="token" type="password" placeholder="not uploaded"/>' +
      '<div class="row"><button class="btn primary" type="submit">Save</button>' +
      '<a class="btn ghost" href="#/brands/' + b.id + '/compose">Generate next</a></div></form></section>'
    );
  }

  function compose(b) {
    return (
      '<section class="panel"><h1>Generate for ' + esc(b.name) + "</h1>" +
      '<p class="muted">Trend picks a sample topic. Custom uses your Veo line. This demo renders a branded preview — the host worker is what calls Flow for a real mp4.</p>' +
      '<form id="composeForm"><label>Mode</label><select name="mode" id="mode">' +
      '<option value="trend">Today’s trending topic</option>' +
      '<option value="custom">My own Veo prompt</option></select>' +
      '<label>Custom prompt</label><textarea name="prompt" id="prompt" rows="4" placeholder="8-second vertical…"></textarea>' +
      '<label>Caption (optional)</label><input name="caption" placeholder="Mention ' + esc(b.name) + '"/>' +
      '<div class="row"><button class="btn primary" type="submit">Generate</button>' +
      '<a class="btn ghost" href="#/brands/' + b.id + '/inbox">Inbox</a></div>' +
      '<p class="status" id="composeStatus"></p></form></section>'
    );
  }

  function reel(b, j) {
    var media = b.splash
      ? (b.splash.indexOf("image/") > -1 || b.splash.indexOf("data:image") === 0
        ? '<img src="' + b.splash + '" alt=""/>'
        : '<video src="' + b.splash + '" muted autoplay loop playsinline></video>')
      : "";
    return (
      '<div class="reel">' + media +
      '<div class="end"><div class="name">' + esc(b.name) + "</div>" +
      "<div>" + esc(j.caption || b.hook || "Approve to post.") + "</div></div></div>"
    );
  }

  function inbox(s, b) {
    var jobs = s.jobs.filter(function (j) { return j.brandId === b.id; }).slice().reverse();
    if (!jobs.length) {
      return "<h1>Inbox · " + esc(b.name) + '</h1><p class="muted">Nothing yet. <a href="#/brands/' + b.id + '/compose">Generate a clip</a>.</p>';
    }
    return (
      "<h1>Inbox · " + esc(b.name) + "</h1>" +
      jobs.map(function (j) {
        var pill = j.status === "posted" ? "posted" : j.status === "rejected" ? "rej" : "wait";
        var body = "";
        if (j.status === "running" || j.status === "queued") {
          body = '<ol class="steps">' +
            '<li class="' + (j.status ? "on" : "") + '">Picking prompt</li>' +
            '<li class="' + (Date.now() > (j.brandAt || 0) ? "on" : "") + '">Generating 8s vertical</li>' +
            '<li class="' + (Date.now() > (j.readyAt || 0) - 800 ? "on" : "") + '">Adding ' + esc(b.name) + " end-card</li>" +
            "</ol><p class=\"muted\">Stay on this page or come back — it will land in awaiting approval.</p>";
        } else {
          body = reel(b, j) +
            "<p><strong>" + esc(j.topic || "Custom prompt") + "</strong><br/>" + esc(j.caption) + "</p>";
          if (j.status === "awaiting_approval") {
            body += '<form class="approveForm" data-id="' + j.id + '">' +
              '<label>Caption</label><textarea name="caption" rows="2">' + esc(j.caption) + "</textarea>" +
              '<div class="row"><button class="btn ok" name="act" value="approve" type="submit">Approve &amp; post</button>' +
              '<button class="btn no" name="act" value="reject" type="submit">Reject</button></div></form>';
          }
          if (j.status === "publishing") body += '<p class="muted">Publishing to @' + esc(b.igUsername || b.slug) + "…</p>";
          if (j.status === "posted") body += '<p class="ok">Posted to @' + esc(b.igUsername || b.slug) + " (demo — Instagram was not called).</p>";
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
        if (kind === "signup") {
          if (s.users.some(function (u) { return u.email === email; })) {
            render(authForm("signup", "That email already has an account. Sign in."));
            bindAuth("signup");
            return;
          }
          var u = { id: uid(), email: email, pass: h };
          s.users.push(u);
          s.session = u.id;
          save(s);
          go("/home");
        } else {
          var found = s.users.filter(function (u) { return u.email === email && u.pass === h; })[0];
          if (!found) {
            render(authForm("login", "Unknown email or password."));
            bindAuth("login");
            return;
          }
          s.session = found.id;
          save(s);
          go("/home");
        }
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
        rec.region = form.region.value.trim() || "IN";
        if (files[0]) rec.logo = files[0];
        if (files[1]) rec.splash = files[1];
        if (!existing) s.brands.push(rec);
        save(s);
        go("/brands/" + rec.id + "/instagram");
      }).catch(function (err) {
        render(shell(s, brandForm(existing, err.message)));
        bindBrand(existing);
      });
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
      render(shell(s, igForm(rec, null, "Saved. Next: generate a clip.")));
      bindIg(rec);
    });
  }

  function bindCompose(b) {
    var form = document.getElementById("composeForm");
    var mode = document.getElementById("mode");
    var prompt = document.getElementById("prompt");
    if (!form) return;
    function sync() { prompt.disabled = mode.value !== "custom"; }
    mode.addEventListener("change", sync);
    sync();
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var custom = prompt.value.trim();
      if (mode.value === "custom" && !custom) {
        document.getElementById("composeStatus").textContent = "Add a Veo prompt, or switch to today’s trend.";
        return;
      }
      var s = state();
      var u = user(s);
      var pick = TRENDS[Math.floor(Math.random() * TRENDS.length)];
      var now = Date.now();
      var job = {
        id: uid(),
        userId: u.id,
        brandId: b.id,
        status: "queued",
        source: mode.value === "custom" ? "custom" : "trend",
        topic: mode.value === "custom" ? "Custom prompt" : pick.topic,
        prompt: mode.value === "custom" ? custom : pick.why,
        caption: (form.caption.value.trim() || pick.caption.replace("{name}", b.name)),
        createdAt: now,
        brandAt: now + 2200,
        readyAt: now + 4800
      };
      s.jobs.push(job);
      save(s);
      go("/brands/" + b.id + "/inbox");
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
  function render(html) {
    document.getElementById("app").innerHTML = html;
  }

  function paint() {
    var s = state();
    advanceJobs(s);
    save(s);
    var path = route();
    var parts = path.split("/").filter(Boolean);

    if (path === "/logout") {
      s.session = null;
      save(s);
      go("/");
      return;
    }
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
    if (!user(s)) {
      go("/login");
      return;
    }
    if (path === "/home") {
      render(shell(s, home(s)));
      return;
    }
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
      if (parts[2] === "instagram") {
        render(shell(s, igForm(b)));
        bindIg(b);
        return;
      }
      if (parts[2] === "compose") {
        render(shell(s, compose(b)));
        bindCompose(b);
        return;
      }
      if (parts[2] === "inbox") {
        render(shell(s, inbox(s, b)));
        bindInbox(b);
        var pending = s.jobs.some(function (j) {
          return j.brandId === b.id && (j.status === "queued" || j.status === "running" || j.status === "publishing");
        });
        if (pending) {
          clearTimeout(timer);
          timer = setTimeout(paint, 400);
        }
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
