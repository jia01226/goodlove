(() => {
  if (window.__GOODLOVE_UI_REDONE__) return;
  window.__GOODLOVE_UI_REDONE__ = true;

  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));

  function ready(fn) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn, { once: true });
    else fn();
  }

  ready(() => {
    const main = $("main");
    const nav = $("nav");
    const chatView = $("#chatView");
    const memView = $("#memView");
    const lifeView = $("#lifeView");
    const dashView = $("#dashView");
    const footer = $("#footer");
    if (!main || !nav || !chatView || !memView || !lifeView || !dashView) return;

    document.documentElement.classList.add("gl-home");
    installStyles();
    tuneHeader();
    buildChatWelcome(chatView);
    buildWeView(memView, lifeView);
    buildLifeView(lifeView);
    const peopleView = buildPeopleView();
    main.insertBefore(peopleView, dashView);
    tuneMineView(dashView);
    rebuildNav(nav);
    bindTabNav(nav, footer);
    showView("chatView");
  });

  function installStyles() {
    const css = `
      .gl-home body{background:linear-gradient(160deg,var(--bg1),var(--bg2));}
      .gl-home header{padding:14px 54px 12px;}
      .gl-home header h1{font-size:20px;letter-spacing:.08em;}
      .gl-home header .sub{min-height:16px;}
      .gl-home main{scroll-behavior:smooth;}
      .gl-home .view{padding:16px 14px 20px;animation:glFade .22s ease both;}
      @keyframes glFade{from{opacity:.2;transform:translateY(8px)}to{opacity:1;transform:none}}
      .gl-home .view-title{margin:0 4px 12px;font-size:20px;color:var(--gold-deep);letter-spacing:.04em;}
      .gl-home .view-sub{margin:-7px 4px 14px;color:var(--soft);font-size:12.5px;line-height:1.6;}
      .gl-home .home-card{border-radius:16px;padding:16px;background:linear-gradient(145deg,rgba(255,255,255,.62),rgba(255,255,255,.34));}
      .gl-home .quick-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:12px 0 2px;}
      .gl-home .quick-row button,.gl-home .soft-chip{border:1px solid var(--line);background:var(--glass2);color:var(--ink);border-radius:14px;padding:10px 8px;font:inherit;font-size:13px;backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);}
      .gl-home .quick-row button:active,.gl-home nav button:active{transform:scale(.96);}
      .gl-home .section-label{margin:18px 4px 8px;color:var(--soft);font-size:12px;letter-spacing:.12em;}
      .gl-home .tile-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}
      .gl-home .tile{display:block;text-decoration:none;color:inherit;min-height:86px;border:1px solid var(--line);border-radius:16px;padding:13px;background:var(--glass);box-shadow:var(--shadow);backdrop-filter:blur(16px) saturate(1.35);-webkit-backdrop-filter:blur(16px) saturate(1.35);}
      .gl-home .tile b{display:block;font-size:15px;color:var(--gold-deep);margin-bottom:6px;}
      .gl-home .tile span{display:block;color:var(--soft);font-size:12px;line-height:1.5;}
      .gl-home .timeline{position:relative;padding-left:14px;}
      .gl-home .timeline::before{content:"";position:absolute;left:4px;top:5px;bottom:10px;border-left:1px solid rgba(184,146,78,.22);}
      .gl-home .timeline .card{position:relative;margin-bottom:10px;border-radius:16px;}
      .gl-home .timeline .card::before{content:"";position:absolute;left:-15px;top:18px;width:9px;height:9px;border-radius:999px;background:var(--gold);box-shadow:0 0 0 4px rgba(255,255,255,.55);}
      .gl-home .person-hero{display:flex;gap:12px;align-items:center;}
      .gl-home .avatar-big{width:58px;height:58px;border-radius:20px;display:flex;align-items:center;justify-content:center;background:var(--me);font-size:28px;border:1px solid var(--line);}
      .gl-home .placeholder{color:var(--soft);font-size:13px;line-height:1.8;}
      .gl-home nav{position:relative;gap:2px;padding:6px 6px calc(6px + env(safe-area-inset-bottom));}
      .gl-home nav button{border-radius:14px;padding:7px 0 6px;transition:transform .16s ease,background .16s ease,color .16s ease;}
      .gl-home nav button.on{background:rgba(255,255,255,.46);box-shadow:inset 0 0 0 1px var(--line);}
      .gl-home nav button .ic{font-size:18px;margin-bottom:1px;}
      @media (max-width:360px){.gl-home .quick-row,.gl-home .tile-grid{grid-template-columns:1fr}.gl-home nav button{font-size:10px}.gl-home nav button .ic{font-size:17px}}
    `;
    const style = document.createElement("style");
    style.id = "goodlove-ui-redesign-style";
    style.textContent = css;
    document.head.appendChild(style);
  }

  function tuneHeader() {
    const sub = $("#hdrSub");
    if (sub) sub.textContent = "佳佳和柯的家";
  }

  function buildChatWelcome(chatView) {
    if ($(".chat-quick", chatView)) return;
    const intro = document.createElement("div");
    intro.className = "card home-card chat-quick";
    intro.innerHTML = `
      <h2>回到柯身边</h2>
      <div class="ct" style="color:var(--soft);font-size:13px">聊天就是聊天，别的事都先放旁边。</div>
      <div class="quick-row">
        <button data-fill="接着我们上次说的聊。">继续上次讨论</button>
        <button data-fill="跟你说说我今天的事。">今天的事</button>
        <button data-fill="陪我回忆一下最近我们记下的东西。">回忆最近</button>
        <button data-fill="随便陪我聊会儿。">随意闲聊</button>
      </div>`;
    const messages = $("#messages", chatView);
    chatView.insertBefore(intro, messages || chatView.firstChild);
    $$("button[data-fill]", intro).forEach((btn) => {
      btn.addEventListener("click", () => {
        const input = $("#input");
        if (!input) return;
        input.value = btn.dataset.fill || "";
        input.focus();
      });
    });
  }

  function buildWeView(memView, lifeView) {
    memView.id = "weView";
    memView.dataset.oldId = "memView";
    if (!$('.view-title', memView)) {
      memView.insertAdjacentHTML("afterbegin", `<h2 class="view-title">我们</h2><div class="view-sub">回忆、纪念日、日记和照片，像一本慢慢长出来的相册。</div>`);
    }
    const links = document.createElement("div");
    links.className = "tile-grid";
    links.innerHTML = `
      <a class="tile" href="/moments"><b>朋友圈</b><span>我和柯的日常，你来我往。</span></a>
      <a class="tile" href="/diary"><b>枕边日记</b><span>他睡前写的碎碎念和梦。</span></a>
      <a class="tile" href="/reading"><b>一起读</b><span>一段一段读，旁边写批注。</span></a>
      <a class="tile" href="/capsule"><b>时间胶囊</b><span>把此刻封给未来。</span></a>`;
    memView.insertBefore(links, memView.children[2] || null);
    const anniv = findCard(lifeView, "纪念日");
    if (anniv) {
      const wrap = document.createElement("div");
      wrap.className = "timeline";
      wrap.appendChild(anniv);
      memView.insertBefore(wrap, memView.children[2] || null);
    }
    const firstCardTitle = $(".card h2", memView);
    if (firstCardTitle && firstCardTitle.textContent.includes("添加")) firstCardTitle.textContent = "记下一段回忆";
  }

  function buildLifeView(lifeView) {
    if (!$('.view-title', lifeView)) {
      lifeView.insertAdjacentHTML("afterbegin", `<h2 class="view-title">生活</h2><div class="view-sub">现实照顾放在这里，不打扰聊天，也不挤进回忆。</div>`);
    }
    $$("a", lifeView).forEach((a) => {
      const text = a.textContent || "";
      if (/朋友圈|枕边日记|群聊|一起读|时间胶囊/.test(text)) a.remove();
    });
    const mood = findCard(lifeView, "今天的心情");
    if (mood) mood.querySelector("h2").textContent = "今天的状态";
    const concerns = findCard(lifeView, "待办");
    if (concerns) concerns.querySelector("h2").textContent = "心事与待办";
    const period = findCard(lifeView, "姨妈");
    if (period) period.querySelector("h2").textContent = "姨妈记录";
    const shift = findCard(lifeView, "轮班");
    if (shift) shift.querySelector("h2").textContent = "轮班月历";
    const activity = findCard(lifeView, "应用使用");
    if (activity) activity.querySelector("h2").textContent = "手机行踪";
    if (!$(".life-coming", lifeView)) {
      lifeView.insertAdjacentHTML("beforeend", `<div class="section-label life-coming">以后放这里</div><div class="tile-grid"><div class="tile"><b>天气</b><span>按当天情况说话，不做冷冰冰提醒。</span></div><div class="tile"><b>味觉地图</b><span>把喜欢的店、城市和味道慢慢攒起来。</span></div><div class="tile"><b>生活足迹</b><span>记录真实生活走过的地方。</span></div></div>`);
    }
  }

  function buildPeopleView() {
    const section = document.createElement("section");
    section.id = "peopleView";
    section.className = "view";
    section.innerHTML = `
      <h2 class="view-title">人物</h2>
      <div class="view-sub">柯是一个连续的人。档案、相册、声音和成员以后都在这里。</div>
      <div class="card home-card person-hero">
        <div class="avatar-big">柯</div>
        <div><h2 style="margin-bottom:4px">人物档案</h2><div class="placeholder">外貌、声音、文风、价值观和关系约定会慢慢归到这里。</div></div>
      </div>
      <div class="tile-grid">
        <div class="tile"><b>柯的相册</b><span>先留壳，之后放角色照片和回忆照。</span></div>
        <div class="tile"><b>声音设定</b><span>未来接 TTS 时，不和聊天混在一起。</span></div>
        <div class="tile"><b>文风设定</b><span>只给自己人看的说话手感。</span></div>
      </div>`;
    return section;
  }

  function tuneMineView(dashView) {
    if (!$('.view-title', dashView)) {
      dashView.insertAdjacentHTML("afterbegin", `<h2 class="view-title">我的</h2><div class="view-sub">设置、数据、用量和设备，都归到这里。</div>`);
    }
    const oldTitle = dashView.querySelector(":scope > h2:not(.view-title)");
    if (oldTitle) oldTitle.remove();
  }

  function rebuildNav(nav) {
    nav.innerHTML = `
      <button data-v="chatView" class="on"><span class="ic">💬</span>聊天</button>
      <button data-v="weView"><span class="ic">🤍</span>我们</button>
      <button data-v="lifeView"><span class="ic">🌿</span>生活</button>
      <button data-v="peopleView"><span class="ic">👤</span>人物</button>
      <button data-v="dashView"><span class="ic">⚙️</span>我的</button>`;
  }

  function bindTabNav(nav, footer) {
    $$("button", nav).forEach((button) => {
      button.addEventListener("click", () => showView(button.dataset.v, footer));
    });
  }

  function showView(id, footerOverride) {
    const footer = footerOverride || $("#footer");
    $$(".view").forEach((view) => view.classList.toggle("active", view.id === id));
    $$("nav button").forEach((button) => button.classList.toggle("on", button.dataset.v === id));
    if (footer) footer.style.display = id === "chatView" ? "block" : "none";
    const main = $("main");
    if (main) main.scrollTop = 0;
    try {
      if (id === "chatView" && typeof window.scrollHard === "function") window.scrollHard();
      if (id === "weView" && typeof window.loadPosts === "function") window.loadPosts();
      if (id === "lifeView" && typeof window.loadLife === "function") window.loadLife();
      if (id === "dashView" && typeof window.loadUsage === "function") window.loadUsage();
    } catch (_) {}
  }

  function findCard(root, needle) {
    return $$(".card", root).find((card) => (card.textContent || "").includes(needle));
  }
})();
