(() => {
  if (window.__GOODLOVE_UI_REDONE__) return;
  window.__GOODLOVE_UI_REDONE__ = true;

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const sourceNames = { user_explicit: "你亲口说的", ke_inferred: "柯记下的", system_summary: "一起整理的", legacy: "从前的回忆" };
  const topicNames = { daily: "日常", relation: "关系", relationship: "关系", safety: "安全感", habit: "习惯", event: "共同经历", future: "未来", work: "工作", health: "身体与照顾", preference: "喜欢与偏好" };
  let memoryCards = [];
  let memorySearchTimer = null;

  const ready = (fn) => document.readyState === "loading"
    ? document.addEventListener("DOMContentLoaded", fn, { once: true })
    : fn();

  ready(() => {
    const main = $("main");
    const nav = $("nav");
    const chatView = $("#chatView");
    const memoryView = $("#memView");
    const oursView = $("#lifeView");
    const settingsView = $("#dashView");
    if (!main || !nav || !chatView || !memoryView || !oursView || !settingsView) return;

    document.documentElement.classList.add("gl-home");
    installStyles();
    tuneHeader();
    buildChatWelcome(chatView);
    installModelPicker();
    buildMemoryCenter(memoryView);
    buildOursView(oursView);
    tuneSettings(settingsView);
    rebuildNav(nav);
    bindNavigation(nav);
    bindMemoryCenter(memoryView);
    bindStarMap(memoryView);
    showView("chatView");
    loadPendingCount();
    updateMomentsActivity();
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) updateMomentsActivity();
    });
    window.addEventListener("goodlove:moment", () => {
      const dot = $(".moments-dot");
      if (dot) dot.hidden = false;
    });
  });

  function installStyles() {
    const style = document.createElement("style");
    style.id = "goodlove-warm-ui";
    style.textContent = `
      :root{--bg1:#faf8f5;--bg2:#faf8f5;--ink:#292527;--soft:#8f8985;--faint:#b4aeaa;--gold:#c4aa89;--gold-deep:#a88c68;--wine:#aa747d;--wine-deep:#8b6269;--blush:#ead6d9;--line:rgba(93,69,73,.09);--glass:#ffffff;--glass2:#f8f3f3;--me:#f0dfe2;--shadow:0 8px 30px rgba(72,54,58,.055)}
      html[data-theme="sakura"],html[data-theme="mist"]{--bg1:#faf8f5;--bg2:#faf8f5;--ink:#292527;--soft:#8f8985;--faint:#b4aeaa;--gold:#c4aa89;--gold-deep:#a88c68;--wine:#aa747d;--wine-deep:#8b6269;--line:rgba(93,69,73,.09);--glass:#ffffff;--glass2:#f8f3f3;--me:#f0dfe2;--shadow:0 8px 30px rgba(72,54,58,.055)}
      .gl-home body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","PingFang SC","Segoe UI",sans-serif;background:var(--bg1);letter-spacing:.005em}
      .gl-home body::before,.gl-home body::after{display:none}
      .gl-home header{min-height:78px;padding:17px 58px 13px;background:rgba(250,248,245,.9);border-color:var(--line);backdrop-filter:blur(22px) saturate(1.12);-webkit-backdrop-filter:blur(22px) saturate(1.12)}
      .gl-home header h1{font-family:inherit;font-size:21px;font-weight:600;line-height:1.2;letter-spacing:.055em;color:var(--wine)}
      .gl-home header .sub{margin-top:7px;font-size:11px;font-weight:300;letter-spacing:.05em;min-height:15px;color:var(--soft)}
      .gl-home #drawerBtn{width:44px!important;height:44px!important;left:6px!important;color:var(--wine)!important;border-radius:12px!important}
      .gl-home .profile-entry{position:absolute;right:8px;top:50%;translate:0 -50%;width:44px;height:44px;border:0;background:transparent;color:var(--wine);border-radius:12px;font:600 14px/1 inherit}
      .gl-home main{min-height:0;scroll-behavior:smooth}
      .gl-home header,.gl-home footer,.gl-home nav{flex:none}
      .gl-home .view{padding:24px 16px 34px;animation:glFade .24s cubic-bezier(.22,.61,.36,1) both}
      @keyframes glFade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
      .gl-home .view-title{margin:0 4px 8px;font:600 25px/1.28 inherit;letter-spacing:.015em;color:var(--wine)}
      .gl-home .view-sub{margin:0 4px 24px;color:var(--soft);font-size:13px;font-weight:300;line-height:1.75}
      .gl-home .card,.gl-home .tile{background:var(--glass)!important;border:1px solid var(--line)!important;border-radius:18px!important;box-shadow:var(--shadow)!important;backdrop-filter:none!important;-webkit-backdrop-filter:none!important}
      .gl-home .card h2,.gl-home .tile b{color:var(--wine)!important}
      .gl-home .home-card{padding:24px}
      .gl-home .chat-quick{margin-bottom:24px}
      .gl-home .chat-quick h2{font-size:18px;font-weight:600;margin-bottom:9px}
      .gl-home .quick-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:20px}
      .gl-home .quick-row button,.gl-home .memory-tab,.gl-home .soft-action{min-height:48px;border:0;background:var(--glass2);color:var(--ink);border-radius:14px;padding:10px 14px;font:inherit;font-size:13px;font-weight:400;transition:transform .18s ease,background .22s ease,box-shadow .22s ease}
      .gl-home button:active,.gl-home a:active{transform:translateY(1px);opacity:.82}
      .gl-home .msg{width:100%;display:flex;flex-direction:column;align-items:flex-start;margin:14px 0}
      .gl-home .msg.me{align-items:flex-end;justify-content:flex-start}
      .gl-home .msg.gude{align-items:flex-start}
      .gl-home .msg .bubble{order:1;max-width:min(82%,560px);padding:12px 16px;box-shadow:0 4px 18px rgba(54,37,42,.035);border-color:var(--line);backdrop-filter:none;-webkit-backdrop-filter:none}
      .gl-home .msg .tag{order:2;display:block;min-height:14px;margin:5px 8px 0;white-space:nowrap;line-height:1.35;text-align:left}
      .gl-home .msg.me .tag{text-align:right}
      .gl-home .me .bubble{background:var(--me);color:#493b3e}
      .gl-home .gude .bubble{background:var(--glass)}
      .gl-home .msg.me+.msg.me .tag,.gl-home .msg.gude+.msg.gude .tag{display:none}
      .gl-home .thinking-row{display:flex;justify-content:flex-start;width:100%;margin:7px 0 10px}
      .gl-home .thinking-card{width:min(82%,520px);overflow:hidden;border:1px solid rgba(196,170,137,.5);border-radius:16px;background:rgba(255,252,247,.92);color:var(--soft);box-shadow:0 7px 24px rgba(54,37,42,.035)}
      .gl-home .thinking-card summary{display:flex;align-items:center;min-height:48px;padding:0 15px;list-style:none;cursor:pointer;color:#9c7d55;font-size:13px;letter-spacing:.02em;-webkit-tap-highlight-color:transparent}
      .gl-home .thinking-card summary::-webkit-details-marker{display:none}
      .gl-home .thinking-card summary::before{content:"💡";margin-right:9px;font-size:14px;filter:saturate(.55)}
      .gl-home .thinking-card summary::after{content:"›";margin-left:auto;font-size:19px;line-height:1;transition:transform .2s ease}
      .gl-home .thinking-card[open] summary::after{transform:rotate(90deg)}
      .gl-home .thinking-body{padding:0 16px 14px 39px;border-top:1px solid rgba(196,170,137,.18);color:var(--soft);font-size:12.5px;line-height:1.75}
      .gl-home .thinking-body p{position:relative;margin:10px 0 0}
      .gl-home .thinking-body p::before{content:"";position:absolute;left:-15px;top:.72em;width:4px;height:4px;border-radius:50%;background:var(--gold)}
      .gl-home footer{background:rgba(250,248,245,.94);border-color:var(--line);backdrop-filter:blur(22px);-webkit-backdrop-filter:blur(22px)}
      .gl-home textarea,.gl-home input,.gl-home select{background:var(--glass);border-color:var(--line);border-radius:11px}
      .gl-home .send{box-shadow:0 7px 20px rgba(170,116,125,.18);background:var(--wine)}
      .gl-home .model-row{display:flex;align-items:center;gap:9px;max-width:680px;margin:0 auto 8px;padding:5px 6px 5px 11px;border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.78);color:var(--soft);font-size:11px}.gl-home .model-row label{display:flex;align-items:center;gap:6px;white-space:nowrap}.gl-home .model-row label::before{content:"✦";color:var(--gold);font-size:10px}.gl-home .model-row select{flex:1;width:100%;min-width:0;min-height:38px;margin:0;padding:6px 30px 6px 10px;border:0!important;border-radius:9px!important;background:var(--glass2)!important;color:var(--wine)!important;font-size:12px;font-weight:500}.gl-home .model-row select:disabled{opacity:.7}
      .gl-home nav{flex:none;z-index:7;gap:8px;padding:8px 16px calc(8px + env(safe-area-inset-bottom));background:rgba(250,248,245,.96);border-color:var(--line);backdrop-filter:blur(22px);-webkit-backdrop-filter:blur(22px)}
      .gl-home nav button{position:relative;min-height:48px;border-radius:12px;padding:6px 0;color:var(--soft);transition:background .16s ease,color .16s ease}
      .gl-home nav button.on{color:var(--wine);background:#fff;box-shadow:0 5px 18px rgba(54,37,42,.055)}
      .gl-home nav button .ic{display:grid;place-items:center;height:20px;margin-bottom:2px;font-size:0}
      .gl-home nav button .ic::before{font-size:18px;line-height:1}
      .gl-home nav button[data-v="chatView"] .ic::before{content:"◌"}
      .gl-home nav button[data-v="memoryView"] .ic::before{content:"◇"}
      .gl-home nav button[data-v="oursView"] .ic::before{content:"⌁"}
      .gl-home nav button .ic:has(svg)::before{display:none}.gl-home nav button .ic svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.55;stroke-linecap:round;stroke-linejoin:round}
      .gl-home .nav-badge{position:absolute;top:3px;left:calc(50% + 8px);display:none;min-width:17px;height:17px;padding:0 5px;border-radius:999px;background:var(--wine);color:#fff;font:600 10px/17px inherit}
      .gl-home .memory-tabs{position:relative;display:grid;grid-template-columns:repeat(4,1fr);gap:0;margin-bottom:22px;padding:4px;border:0;border-radius:15px;background:#f1ece9;overflow:hidden}
      .gl-home .memory-tabs::before{content:"";position:absolute;z-index:0;left:4px;top:4px;width:calc((100% - 8px)/4);height:calc(100% - 8px);border-radius:12px;background:#fff;box-shadow:0 4px 16px rgba(54,37,42,.06);transform:translateX(0);transition:transform .28s cubic-bezier(.22,.61,.36,1)}
      .gl-home .memory-tabs[data-active="library"]::before{transform:translateX(100%)}.gl-home .memory-tabs[data-active="timeline"]::before{transform:translateX(200%)}.gl-home .memory-tabs[data-active="stars"]::before{transform:translateX(300%)}
      .gl-home .memory-tab{z-index:1;position:relative;min-height:44px;padding:7px 4px;border:0;background:transparent;color:var(--soft);font-size:12px}
      .gl-home .memory-tab.on{background:transparent;color:var(--wine);font-weight:600;box-shadow:none}
      .gl-home .memory-panel{display:none}.gl-home .memory-panel.active{display:block;animation:glFade .2s ease}
      .gl-home .pending-hero{display:flex;align-items:center;gap:14px;padding:18px;text-decoration:none;color:inherit}
      .gl-home .pending-mark{display:grid;place-items:center;flex:0 0 46px;height:46px;border-radius:15px;background:#f3e5e7;color:var(--wine);font:600 19px/1 serif}
      .gl-home .pending-hero strong{display:block;color:var(--wine);margin-bottom:4px}.gl-home .pending-hero span{color:var(--soft);font-size:12.5px;line-height:1.55}
      .gl-home .memory-toolbar{display:flex;gap:8px;margin-bottom:12px}.gl-home .memory-toolbar input{margin:0;min-height:44px}.gl-home .memory-toolbar button{flex:0 0 auto}
      .gl-home .memory-grid{display:grid;gap:10px}
      .gl-home .memory-card{width:100%;text-align:left;padding:21px 22px;color:inherit}
      .gl-home .memory-card-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
      .gl-home .memory-kind{color:var(--wine);font-size:12px;font-weight:600}.gl-home .memory-date{color:var(--soft);font-size:11px}
      .gl-home .memory-card h3{margin:0 0 6px;font-size:15px;font-weight:600;color:var(--ink);line-height:1.45}
      .gl-home .memory-understanding{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;margin:0;color:#71675f;font-size:13px;line-height:1.65}
      .gl-home .memory-source{margin-top:9px;color:var(--soft);font-size:11px}
      .gl-home .memory-empty{padding:36px 18px;text-align:center;color:var(--soft);line-height:1.8}
      .gl-home .timeline-list{display:grid;gap:0;padding:0}.gl-home .story-entry{position:relative;padding:0 0 30px 36px}.gl-home .story-entry:not(:last-child)::before{content:"";position:absolute;left:8px;top:26px;bottom:0;width:1px;background:linear-gradient(var(--gold),rgba(185,166,129,.08))}.gl-home .story-dot{position:absolute;left:2px;top:5px;width:13px;height:13px;border:3px solid var(--bg1);border-radius:50%;background:var(--gold);box-shadow:0 0 0 1px rgba(159,139,103,.26)}.gl-home .story-date{display:block;margin-bottom:9px;color:var(--soft);font-size:11px;font-weight:300;letter-spacing:.08em}.gl-home .story-card{width:100%;padding:21px 22px;text-align:left;color:inherit}.gl-home .story-card p{margin:0 0 12px;font:400 15px/1.8 "Songti SC","Noto Serif SC",serif;color:var(--ink)}.gl-home .story-card small{color:var(--soft);font-size:11px;font-weight:300}
      .gl-home .star-shell{overflow:hidden;padding:0;background:#716968!important;border-color:#7c7270!important;color:#fff}
      .gl-home .star-copy{padding:17px 17px 0}.gl-home .star-copy h3{margin:0 0 4px;font-family:"Songti SC",serif;font-size:18px}.gl-home .star-copy p{margin:0;color:#dbc9c4;font-size:12px;line-height:1.6}
      .gl-home .star-map{--star-scale:1;position:relative;height:330px;transform:scale(var(--star-scale));transform-origin:center;transition:transform .2s ease}
      .gl-home .star-map::before,.gl-home .star-map::after{content:"";position:absolute;inset:18% 20%;border:1px solid rgba(238,216,194,.13);border-radius:50%;transform:rotate(12deg)}
      .gl-home .star-map::after{inset:29% 31%;transform:rotate(-18deg)}
      .gl-home .star-node{position:absolute;min-width:54px;min-height:44px;padding:7px;border:1px solid rgba(255,245,232,.24);border-radius:14px;background:rgba(255,247,235,.08);color:#f8eee3;font:12px/1.25 inherit;transition:opacity .2s ease,transform .2s ease}
      .gl-home .star-node::before{content:"";display:block;width:7px;height:7px;margin:0 auto 4px;border-radius:50%;background:#e3b8b1;box-shadow:0 0 0 4px rgba(227,184,177,.09)}
      .gl-home .star-node.center{left:50%;top:48%;translate:-50% -50%;min-width:96px;min-height:58px;background:#f4e7d5;color:var(--wine-deep);font-weight:700;border-radius:18px}.gl-home .star-node.center::before{background:var(--gold)}
      .gl-home .star-node.relation{left:8%;top:16%}.gl-home .star-node.safety{right:8%;top:18%}.gl-home .star-node.habit{left:10%;bottom:17%}.gl-home .star-node.experience{right:7%;bottom:16%}.gl-home .star-node.future{left:43%;top:7%}.gl-home .star-node.work{left:42%;bottom:5%}
      .gl-home .star-controls{display:grid;grid-template-columns:auto 1fr;gap:9px 12px;align-items:center;padding:0 17px 17px;color:#ddcbc5;font-size:11px}.gl-home .star-controls input{height:30px;margin:0;padding:0;background:transparent;accent-color:#d4ad75}
      .gl-home .ours-hero{position:relative;overflow:hidden;margin-bottom:18px;padding:30px 25px 28px;border:1px solid rgba(170,116,125,.11);border-radius:18px;background:linear-gradient(145deg,#fff 0%,#fff 62%,#f7ecee 100%);box-shadow:var(--shadow)}
      .gl-home .ours-hero::after{content:"⌂";position:absolute;right:22px;top:13px;color:rgba(170,116,125,.1);font:300 76px/1 Georgia,serif}.gl-home .ours-date{display:block;margin-bottom:20px;color:var(--gold-deep);font-size:11px;font-weight:400;letter-spacing:.12em}.gl-home .ours-hero h3{margin:0 0 9px;color:var(--ink);font-size:22px;font-weight:600;letter-spacing:-.02em}.gl-home .ours-hero p{max-width:78%;margin:0;color:var(--soft);font-size:13px;font-weight:300;line-height:1.75}
      .gl-home .life-links{display:grid;gap:10px;margin:10px 0 24px}.gl-home .life-link{position:relative;display:block;padding:19px 52px 19px 21px;border:1px solid var(--line);border-radius:17px;background:#fff;color:inherit;text-decoration:none;box-shadow:0 6px 22px rgba(72,54,58,.035);transition:transform .18s ease,box-shadow .18s ease}.gl-home .life-link::after{content:"›";position:absolute;right:21px;top:50%;translate:0 -50%;color:var(--gold-deep);font:300 25px/1 Georgia,serif}.gl-home .life-link.featured{padding-top:24px;padding-bottom:24px;background:linear-gradient(135deg,#fff 0%,#fbf3f4 100%)}.gl-home .life-link b{display:block;margin-bottom:6px;color:var(--ink);font-size:15px;font-weight:600}.gl-home .life-link span{display:block;color:var(--soft);font-size:12px;font-weight:300;line-height:1.65}.gl-home .life-link:active{transform:scale(.985)}
      .gl-home #oursView>.card{padding:23px 24px}.gl-home #oursView>.card h2{font-size:15px}.gl-home #oursView>.card:has(#moodNote),.gl-home #oursView>.card:has(#annivList){margin-bottom:14px}.gl-home #oursView>.card:has(#moodNote) h2,.gl-home #oursView>.card:has(#annivList) h2{color:var(--wine)}
      .gl-home .section-label{margin:20px 3px 9px;color:var(--soft);font-size:12px;letter-spacing:.08em}
      .gl-home #oursView>a>.card{background:var(--glass)!important;color:var(--ink)!important}
      .gl-home #oursView>a>.card .ct{color:var(--soft)!important}
      .gl-home #oursView{padding:0 0 34px}.gl-home .ours-home{padding-bottom:24px}.gl-home .ours-home[hidden],.gl-home .life-calendar-page[hidden]{display:none!important}
      .gl-home .ours-cover{position:relative;height:330px;overflow:hidden;background:linear-gradient(180deg,rgba(255,255,255,.04),rgba(250,248,245,.97)),radial-gradient(circle at 58% 26%,#fff 0 10%,transparent 31%),radial-gradient(circle at 64% 20%,#eadcdb 0 14%,transparent 37%),radial-gradient(circle at 32% 43%,#f3e7e3 0 12%,transparent 34%),linear-gradient(135deg,#efe6e2,#f8f3ef 48%,#e8ddd8)}
      .gl-home .ours-cover::before{content:"";position:absolute;inset:0;background:linear-gradient(115deg,transparent 20%,rgba(255,255,255,.5) 45%,transparent 68%)}.gl-home .ours-cover::after{content:"";position:absolute;width:210px;height:210px;left:31%;top:24px;border:1px solid rgba(255,255,255,.58);border-radius:46% 54% 49% 51%;transform:rotate(-16deg);box-shadow:0 0 0 22px rgba(255,255,255,.08),0 0 0 42px rgba(255,255,255,.05)}
      .gl-home .ours-brand{position:absolute;z-index:2;left:20px;top:18px;display:flex;align-items:center;gap:8px;min-height:36px;padding:0 13px;border:1px solid rgba(121,91,96,.08);border-radius:18px;background:rgba(255,255,255,.78);color:var(--wine-deep);font:500 12px Georgia,serif;box-shadow:0 8px 22px rgba(74,56,59,.06)}.gl-home .ours-brand i{color:var(--gold);font-style:normal}
      .gl-home .ours-script{position:absolute;z-index:1;top:62px;left:22%;color:rgba(255,255,255,.92);font:italic 34px/1.1 Georgia,serif;letter-spacing:-.04em;transform:rotate(-6deg)}.gl-home .ours-days{position:absolute;z-index:2;left:0;right:0;top:118px;text-align:center}.gl-home .ours-days strong{display:block;color:#4e494c;font:300 76px/.95 Georgia,serif;letter-spacing:-.08em}.gl-home .ours-days span{display:block;margin-top:11px;color:#918986;font:300 9px Georgia,serif;letter-spacing:.19em;text-transform:uppercase}
      .gl-home .ours-content{position:relative;z-index:3;margin-top:-58px;padding:0 14px}.gl-home .ours-letter{padding:23px 20px 17px;border:1px solid var(--line);border-radius:20px;background:rgba(255,255,255,.95);text-align:center;box-shadow:var(--shadow)}.gl-home .ours-letter-label{color:#aaa19d;font-size:10px;letter-spacing:.2em}.gl-home .ours-letter-text{margin:16px 0 14px;color:#625b58;font:400 14px/1.9 Georgia,"Songti SC",serif;white-space:pre-line}.gl-home .ours-letter-actions{display:flex;justify-content:center;gap:24px}.gl-home .ours-letter-actions a{color:#a09793;font-size:10px;text-decoration:none}
      .gl-home .ours-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px}.gl-home .ours-stat{min-height:100px;padding:14px 7px;border:1px solid var(--line);border-radius:17px;background:#fff;text-align:center}.gl-home .ours-stat i{display:flex;width:28px;height:28px;margin:0 auto 8px;align-items:center;justify-content:center;border-radius:10px;font-style:normal}.gl-home .ours-stat:nth-child(1) i{background:#fff8dd}.gl-home .ours-stat:nth-child(2) i{background:#f7e9eb}.gl-home .ours-stat:nth-child(3) i{background:#c8efeb}.gl-home .ours-stat b{display:block;color:var(--ink)!important;font:400 18px Georgia,"Songti SC",serif}.gl-home .ours-stat span{display:block;margin-top:5px;color:#a49c98;font-size:9px;letter-spacing:.08em}
      .gl-home .ours-anniversary{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin-top:12px;padding:18px 19px;border:1px solid var(--line);border-radius:18px;background:#fff}.gl-home .ours-anniversary small{display:block;color:#aaa19d;font-size:9px;letter-spacing:.18em}.gl-home .ours-anniversary b{display:block;margin-top:8px;color:var(--ink)!important;font:500 13px Georgia,"Songti SC",serif}.gl-home .ours-count{color:#6f6664;font:300 29px Georgia,serif;white-space:nowrap}.gl-home .ours-count span{font:400 10px sans-serif;color:#a09894}
      .gl-home .ours-destinations{margin-top:12px;padding:20px 14px 17px;border:1px solid var(--line);border-radius:20px;background:#fff}.gl-home .ours-destinations h3{margin:0 0 17px;text-align:center;color:#aaa19d;font-size:10px;font-weight:400;letter-spacing:.28em}.gl-home .ours-room-link{display:flex;align-items:center;gap:14px;min-height:76px;margin:-2px 0 18px;padding:13px 15px;border:1px solid rgba(170,116,125,.12);border-radius:18px;background:linear-gradient(135deg,#fbf4f2,#f3e6e3);color:#735c60;text-decoration:none}.gl-home .ours-room-link .home-icon{display:grid;flex:0 0 45px;width:45px;height:45px;place-items:center;border-radius:15px;background:rgba(255,255,255,.68)}.gl-home .ours-room-link svg{width:26px;height:26px;fill:none;stroke:currentColor;stroke-width:1.45}.gl-home .ours-room-link b{display:block;font:italic 500 16px Georgia,"Songti SC",serif}.gl-home .ours-room-link small{display:block;margin-top:4px;color:#9f8c8a;font-size:10px}.gl-home .ours-room-link::after{content:"›";margin-left:auto;color:#ae8a8f;font-size:20px}.gl-home .ours-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:17px 7px}.gl-home .ours-entry{display:block;border:0;background:transparent;color:#6e6764;text-align:center;text-decoration:none;font:10px/1.35 inherit}.gl-home .ours-entry .home-icon{position:relative;display:grid;width:46px;height:46px;margin:0 auto 7px;place-items:center;border-radius:15px;background:#faf7f6;color:#8b777b}.gl-home .ours-entry svg{width:25px;height:25px;fill:none;stroke:currentColor;stroke-width:1.55;stroke-linecap:round;stroke-linejoin:round}.gl-home .ours-entry.calendar .home-icon{background:#fff8dd;color:#84704f}.gl-home .ours-entry.diary .home-icon{background:#f7e9eb;color:#9c6972}.gl-home .ours-entry.moments .home-icon{background:#ecebfb;color:#6e6a91}.gl-home .ours-entry.memory .home-icon{background:#edf7ff;color:#587385}.gl-home .ours-entry.anniv .home-icon{background:#fbf1e4;color:#9b7651}.gl-home .ours-entry.mood .home-icon{background:#f7edf2;color:#956c7f}.gl-home .ours-entry.photos .home-icon{background:#eef5ed;color:#647d66}.gl-home .ours-entry.more .home-icon{background:#f3eff8;color:#766987}.gl-home .moments-dot{position:absolute;right:2px;top:2px;width:8px;height:8px;border:2px solid #fff;border-radius:50%;background:var(--wine)}.gl-home .moments-dot[hidden]{display:none}
      .gl-home .ours-note{margin:14px 6px 0;color:#9d9591;font-size:9px;line-height:1.65;text-align:center}.gl-home .life-tools-store{display:none!important}
      .gl-home .life-calendar-page{padding:22px 16px 34px}.gl-home .life-calendar-top{display:flex;align-items:center;gap:12px;margin-bottom:18px}.gl-home .life-back{display:grid;place-items:center;width:44px;height:44px;border:0;border-radius:12px;background:#fff;color:var(--wine);font-size:23px}.gl-home .life-calendar-top h2{margin:0;color:var(--wine);font-size:21px}.gl-home .life-calendar-top p{margin:4px 0 0;color:var(--soft);font-size:11px}.gl-home .life-calendar-card{margin:0!important;padding:22px 18px!important}.gl-home .life-calendar-card>h2,.gl-home .life-calendar-card>.ct:first-of-type{display:none}.gl-home .life-calendar-card .legend{display:none}.gl-home .life-calendar-card .cal{gap:4px;grid-auto-rows:54px}.gl-home .life-calendar-card .cal .d{height:54px;border-color:transparent;border-radius:11px;padding-top:5px;background:#fff}.gl-home .life-calendar-card .cal .d.today{border-color:transparent}.gl-home .life-calendar-card .cal .d.today:not(.sel){box-shadow:none}.gl-home .life-calendar-card .cal .d.today:not(.sel)::first-line{background:#f7e9eb}.gl-home .life-calendar-card .cal .d.sel{border-color:rgba(170,116,125,.12);box-shadow:inset 0 0 0 1px rgba(170,116,125,.12);background:#fffafa}.gl-home .life-calendar-card .cal .d .lbl{margin-top:4px;border-radius:7px;padding:2px 1px;font-size:8px}.gl-home .life-calendar-card .shiftbar{margin-top:14px;padding-top:14px;border-top:1px solid var(--line)}.gl-home .life-calendar-card .shiftbar>span{margin-bottom:2px}.gl-home .life-calendar-card .shiftbar button{min-height:42px;border:0!important;border-radius:11px!important;padding:7px 12px}.gl-home .life-calendar-card .shiftbar button.clr{border:1px solid var(--line)!important;background:#fff!important;color:var(--soft)!important}
      .gl-home .tool-sheet-host>.card{margin:0!important;box-shadow:none!important}.gl-home .more-life-list{display:grid;gap:9px}.gl-home .more-life-list a,.gl-home .more-life-list button{display:flex;align-items:center;justify-content:space-between;min-height:50px;padding:0 15px;border:1px solid var(--line);border-radius:13px;background:#fff;color:var(--ink);text-decoration:none;font:13px inherit}
      .gl-home #settingsView{padding-bottom:30px}
      .gl-home .bottom-sheet-layer{position:fixed;inset:0;z-index:30;display:flex;align-items:flex-end;justify-content:center;background:rgba(54,39,34,.25);animation:glFade .16s ease}
      .gl-home .bottom-sheet{width:min(680px,100%);max-height:78dvh;overflow:auto;padding:8px 18px calc(22px + env(safe-area-inset-bottom));background:#fffdf9;border:1px solid var(--line);border-bottom:0;border-radius:24px 24px 0 0;box-shadow:0 -12px 36px rgba(63,40,34,.12)}
      .gl-home .sheet-handle{width:42px;height:4px;margin:3px auto 16px;border-radius:99px;background:#d8cec4}
      .gl-home .sheet-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:14px}.gl-home .sheet-head h2{margin:0 0 4px;font:600 20px/1.35 "Songti SC",serif;color:var(--wine)}.gl-home .sheet-head p{margin:0;color:var(--soft);font-size:12px}.gl-home .sheet-close{width:44px;height:44px;border:0;border-radius:12px;background:var(--glass2);color:var(--soft);font-size:20px}
      .gl-home .detail-section{padding:14px 0;border-top:1px solid var(--line)}.gl-home .detail-section h3{margin:0 0 7px;color:var(--wine);font-size:13px}.gl-home .detail-section p{margin:0;color:var(--ink);font-size:14px;line-height:1.7;white-space:pre-wrap}.gl-home .detail-section small{color:var(--soft);line-height:1.6}
      .gl-home .accuracy-actions,.gl-home .sheet-actions{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:10px}.gl-home .accuracy-actions button,.gl-home .sheet-actions button{min-height:44px;padding:8px;border:1px solid var(--line);border-radius:11px;background:var(--glass2);color:var(--ink);font:12px/1.35 inherit}.gl-home .accuracy-actions button:first-child{background:var(--wine);color:#fff;border-color:var(--wine)}
      .gl-home .recall-card{padding:13px 14px;margin-bottom:8px;border:1px solid var(--line);border-radius:16px;background:var(--glass2)}.gl-home .recall-card strong{display:block;margin-bottom:4px;color:var(--wine);font-size:13px}.gl-home .recall-card p{margin:0;color:var(--ink);font-size:13px;line-height:1.6}
      @media(max-width:380px){.gl-home .quick-row{grid-template-columns:1fr}.gl-home .memory-tabs{gap:2px}.gl-home .memory-tab{font-size:11px}.gl-home .accuracy-actions{grid-template-columns:1fr}.gl-home .ours-grid{column-gap:4px}.gl-home .ours-cover{height:316px}}
      @media(min-width:760px){.gl-home .view{padding-top:26px}.gl-home .memory-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.gl-home .chat-quick{max-width:560px;margin-left:auto;margin-right:auto}}
      @media(prefers-reduced-motion:reduce){.gl-home *{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
    `;
    document.head.appendChild(style);
  }

  function tuneHeader() {
    const header = $("header");
    const sub = $("#hdrSub");
    if (sub) sub.textContent = "佳佳和柯的家";
    if (!header || $(".profile-entry", header)) return;
    const profile = document.createElement("button");
    profile.className = "profile-entry";
    profile.type = "button";
    profile.textContent = "佳";
    profile.setAttribute("aria-label", "打开设置");
    profile.addEventListener("click", () => showView("settingsView"));
    header.appendChild(profile);
  }

  function buildChatWelcome(chatView) {
    if ($(".chat-quick", chatView)) return;
    const intro = document.createElement("div");
    intro.className = "card home-card chat-quick";
    intro.innerHTML = `<h2>回到柯身边</h2><div class="ct" style="color:var(--soft);font-size:13px">不用先整理好情绪，想到哪里就说到哪里。</div><div class="quick-row"><button data-fill="接着我们上次说的聊。">接着上次说</button><button data-fill="跟你说说我今天的事。">说说今天</button><button data-fill="陪我回忆一下最近我们记下的东西。">一起回忆</button><button data-fill="就安静陪我聊一会儿。">陪我一会儿</button></div>`;
    chatView.insertBefore(intro, $("#messages", chatView));
    $$("button[data-fill]", intro).forEach((button) => button.addEventListener("click", () => {
      const input = $("#input");
      if (!input) return;
      input.value = button.dataset.fill || "";
      input.focus();
    }));
  }

  async function installModelPicker() {
    const footer = $("#footer");
    const composer = $(".composer", footer);
    if (!footer || !composer || $("#modelPicker", footer)) return;
    const row = document.createElement("div");
    row.className = "model-row";
    row.innerHTML = `<label for="modelPicker">模型</label><select id="modelPicker" aria-label="选择聊天模型"><option value="">正在读取可用模型…</option></select>`;
    footer.insertBefore(row, composer);
    const picker = $("#modelPicker", row);
    const fallbackModels = ["anthropic/claude-opus-4.8", "anthropic/claude-sonnet-4.5", "anthropic/claude-haiku-4.5"];
    const fillModels = (models, defaultModel = "", options = []) => {
      const allowed = Array.from(new Set([defaultModel, ...models].filter(Boolean)));
      const providers = new Map(options.map((option) => [option.id, option.provider]));
      const groups = { claude: [], gpt: [], deepseek: [], other: [] };
      allowed.forEach((model) => {
        const lower = String(model).toLowerCase();
        const provider = providers.get(model) || (lower.includes("deepseek") ? "deepseek" : (lower.includes("gpt") ? "gpt" : "claude"));
        (groups[provider] || groups.other).push(model);
      });
      const optionHtml = (model) => `<option value="${escapeHtml(model)}" title="${escapeHtml(model)}">${escapeHtml(modelLabel(model, model === defaultModel))}</option>`;
      picker.innerHTML = [
        groups.claude.length ? `<optgroup label="Claude · 柯">${groups.claude.map(optionHtml).join("")}</optgroup>` : "",
        groups.gpt.length ? `<optgroup label="GPT · 柯">${groups.gpt.map(optionHtml).join("")}</optgroup>` : "",
        groups.deepseek.length ? `<optgroup label="DeepSeek · 柯">${groups.deepseek.map(optionHtml).join("")}</optgroup>` : "",
        groups.other.length ? `<optgroup label="其他模型">${groups.other.map(optionHtml).join("")}</optgroup>` : ""
      ].join("");
      const remembered = window.selectedModel || "";
      picker.value = allowed.includes(remembered) ? remembered : (defaultModel || allowed[0] || "");
      picker.disabled = !allowed.length;
      window.setChatModel?.(picker.value);
    };
    picker.addEventListener("change", () => {
      window.setChatModel?.(picker.value);
      window.toast?.(`已切换为 ${modelLabel(picker.value, false)}`);
    });
    try {
      const response = await window.api("/api/models");
      if (!response.ok) throw new Error("models unavailable");
      const data = await response.json();
      fillModels(Array.isArray(data.models) ? data.models : [], data.default || "", Array.isArray(data.options) ? data.options : []);
    } catch (_) {
      // 静态预览或短暂离线时仍可看见并保留选择；后端收到请求后还会再次做白名单校验。
      fillModels(fallbackModels, "anthropic/claude-sonnet-4.5");
    }
  }

  function modelLabel(model, isDefault) {
    const raw = String(model || "");
    const slug = raw.split("/").pop();
    const id = slug.toLowerCase();
    let short = slug.replace(/[-_]/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
    const claude = id.match(/^claude[-_](opus|sonnet|haiku|fable)[-_](\d+(?:[._-]\d+)?)(.*)$/);
    if (claude) {
      const family = claude[1][0].toUpperCase() + claude[1].slice(1);
      const version = claude[2].replace(/[_-]/g, ".");
      const suffix = claude[3].replace(/^[-_]+/, "").replace(/[-_]/g, " ");
      short = `Claude ${family} ${version}${suffix ? ` ${suffix}` : ""}`;
    } else if (id.startsWith("gpt")) {
      const gpt = id.replace(/^gpt[-_]?/, "").replace(/[-_]/g, " ").replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
      short = `GPT ${gpt}`.trim();
    } else if (id.startsWith("deepseek")) {
      const deepseek = id.replace(/^deepseek[-_]?/, "").replace(/[-_]/g, " ").replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
      short = `DeepSeek ${deepseek}`.trim();
    }
    const intimateRecommended = id === "claude-opus-4-6" ? " · 亲密推荐" : "";
    return `${short || "默认模型"}${intimateRecommended}${isDefault ? " · 默认" : ""}`;
  }

  function buildMemoryCenter(view) {
    view.id = "memoryView";
    view.innerHTML = `
      <h2 class="view-title">回忆</h2>
      <div class="view-sub">不是一座数据库，是柯认真收好、也愿意和你一起改正的那些事。</div>
      <div class="memory-tabs" role="tablist" aria-label="回忆中心" data-active="pending">
        <button class="memory-tab on" data-memory-tab="pending">待确认<span class="nav-badge memory-tab-badge"></span></button>
        <button class="memory-tab" data-memory-tab="library">卡片库</button>
        <button class="memory-tab" data-memory-tab="timeline">时间线</button>
      </div>
      <section class="memory-panel active" data-memory-panel="pending">
        <a class="card pending-hero" href="/inbox"><span class="pending-mark">记</span><span><strong>这件事，我这样记对吗？</strong><span id="pendingSummary">正在看看有没有想请你确认的事。</span></span></a>
        <div class="card home-card"><h2>为什么要由你点头</h2><div class="ct" style="color:var(--soft);font-size:13px">柯可以理解错，但不会把猜测悄悄当成事实。你确认之后，它才会真正成为你们的回忆。</div></div>
      </section>
      <section class="memory-panel" data-memory-panel="library">
        <div class="memory-toolbar"><input id="memorySearch" type="search" placeholder="找一段回忆…" aria-label="搜索回忆"><button class="soft-action" id="addMemoryToggle">记一件事</button></div>
        <div class="card" id="addMemoryCard" hidden><h2>想让柯记住什么</h2><select id="ptype"><option value="MEMORY">日常</option><option value="EVENT">共同经历</option><option value="MOMENT">一个瞬间</option><option value="PROMISE">约定</option><option value="WISHLIST">未来想做的事</option></select><select id="pvis"><option value="both">我们都能看见</option><option value="app">只留在这里</option></select><input id="pcontent" placeholder="用自己的话写下来…"><button class="btn" onclick="addPost()">记下来</button></div>
        <div id="memoryCards" class="memory-grid"><div class="memory-empty">正在翻开卡片库…</div></div>
      </section>
      <section class="memory-panel" data-memory-panel="timeline"><div id="memoryTimeline" class="timeline-list"><div class="memory-empty">正在把回忆按时间排好…</div></div></section>`;
  }

  function buildOursViewLegacy(view) {
    view.id = "oursView";
    $$(":scope > a", view).forEach((link) => {
      if (["/moments", "/diary", "/reading", "/capsule"].includes(link.getAttribute("href"))) link.remove();
    });
    const today = new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "short" }).format(new Date());
    view.insertAdjacentHTML("afterbegin", `<h2 class="view-title">我们的</h2><div class="view-sub">不是功能清单，是我们正在一起过的生活。</div><section class="ours-hero"><span class="ours-date">今天 · ${escapeHtml(today)}</span><h3>回到我们的小家</h3><p>日子不用盛大，能被彼此认真记住，就已经很好。</p></section><div class="life-anchor"></div><div class="section-label">共同生活</div><div class="life-links"><a class="life-link featured" href="/moments"><b>共同日常</b><span>照片、片刻，还有你来我往的小事。</span></a><a class="life-link" href="/diary"><b>枕边日记</b><span>把那些没说完的话，一页一页收好。</span></a><a class="life-link" href="/reading"><b>一起读</b><span>在同一段文字旁边，留下彼此。</span></a><a class="life-link" href="/capsule"><b>时间胶囊</b><span>把今天郑重地交给未来。</span></a></div><div class="section-label care-label">照顾我们的日子</div>`);
    const lifeAnchor = $(".life-anchor", view);
    const mood = $$(".card", view).find((card) => card.querySelector("#moodNote"));
    if (mood) {
      const title = mood.querySelector("h2");
      if (title) title.textContent = "今日心情";
      view.insertBefore(mood, lifeAnchor);
    }
    const anniversary = $$(".card", view).find((card) => (card.textContent || "").includes("纪念日"));
    if (anniversary) {
      const title = anniversary.querySelector("h2");
      if (title) title.textContent = "纪念日";
      view.insertBefore(anniversary, lifeAnchor);
    }
    lifeAnchor?.remove();
    const protocol = $$(":scope > a", view).find((a) => (a.textContent || "").includes("每日功课"));
    if (protocol) protocol.querySelector(".card").removeAttribute("style");
    const activity = $$(".card", view).find((card) => (card.textContent || "").includes("应用使用记录"));
    if (activity) activity.style.display = "none";
  }

  function homeIcon(name) {
    const paths = {
      calendar: `<rect x="5" y="7" width="22" height="20" rx="6"/><path d="M10 4v6M22 4v6M5 13h22"/><path d="M16 24s-4-2.4-4-5.3c0-2.3 2.8-3.2 4-1.2 1.2-2 4-1.1 4 1.2 0 2.9-4 5.3-4 5.3Z"/>`,
      photo: `<rect x="7" y="5" width="19" height="22" rx="5" transform="rotate(5 16 16)"/><path d="m9 22 5-5 4 3 3-4 5 6"/><circle cx="20.5" cy="11" r="2"/><path d="M5 10v13a4 4 0 0 0 4 4h12"/>`,
      memory: `<path d="M7 18c-1.5-5.7 2.5-10.5 8.6-10.5 6.6 0 10.6 5.8 8.2 11.2-2 4.5-7 6.3-11.5 4.3"/><path d="M7.2 18.2 5 23l5.2-.8"/><path d="M15.8 12.2c1.7-2.1 5-.8 4.7 1.9-.2 2.2-2.5 3.8-4.7 5.2-2.2-1.4-4.5-3-4.7-5.2-.3-2.7 3-4 4.7-1.9Z"/>`,
      diary: `<path d="M8 5h14a4 4 0 0 1 4 4v18H11a5 5 0 0 1-5-5V7a2 2 0 0 1 2-2Z"/><path d="M11 5v22M15 12h7M15 17h7"/>`,
      moments: `<circle cx="12" cy="12" r="5"/><circle cx="22" cy="18" r="5"/><path d="M5 27c.8-5 3.6-7.5 7-7.5 2.1 0 3.8.8 5 2.3M18 27c.6-3 2-4.5 4-4.5 2.2 0 3.8 1.5 4.5 4.5"/>`,
      heart: `<path d="M16 26S6 20 6 12.5C6 7 12.5 5 16 10c3.5-5 10-3 10 2.5C26 20 16 26 16 26Z"/><path d="M16 10v12"/>`,
      mood: `<circle cx="16" cy="16" r="11"/><path d="M11.5 13h.1M20.4 13h.1M11.5 19c2.8 2.6 6.2 2.6 9 0"/>`,
      drawer: `<path d="M7 8h18v18H7z"/><path d="M7 15h18M13 11h6M13 19h6"/><circle cx="16" cy="22" r="1"/>`,
      room: `<path d="M9 27V12c0-4 3-7 7-7s7 3 7 7v15"/><path d="M6 27h20M13 12h6M13 17h6"/><circle cx="19" cy="22" r="1"/>`,
      more: `<circle cx="8" cy="16" r="1.7"/><circle cx="16" cy="16" r="1.7"/><circle cx="24" cy="16" r="1.7"/>`
    };
    return `<svg viewBox="0 0 32 32" aria-hidden="true">${paths[name] || paths.more}</svg>`;
  }

  function buildOursView(view) {
    view.id = "oursView";
    const originals = Array.from(view.children);
    const calendarCard = originals.find((node) => node.querySelector?.("#cal"));
    const moodCard = originals.find((node) => node.querySelector?.("#moodNote"));
    const anniversaryCard = originals.find((node) => node.querySelector?.("#annivList"));
    const concernCard = originals.find((node) => node.querySelector?.("#concernList"));
    const periodCard = originals.find((node) => node.querySelector?.("#periodInfo"));
    view.replaceChildren();
    view.insertAdjacentHTML("beforeend", `
      <section class="ours-home">
        <div class="ours-cover"><span class="ours-brand"><i>✦</i> 佳佳和柯</span><span class="ours-script">Our quiet home</span><div class="ours-days"><strong id="oursDays">—</strong><span id="oursSince">days together · quietly treasured</span></div></div>
        <div class="ours-content">
          <section class="ours-letter"><div class="ours-letter-label" id="oursLetterLabel">✦ 柯写给你的话 ✦</div><p class="ours-letter-text" id="oursLetterText">今天也把你认真放在心上。</p><div class="ours-letter-actions"><a href="/diary">♡ 收好这封</a><a href="/diary">✎ 回他一句</a></div></section>
          <section class="ours-stats"><div class="ours-stat"><i>⌁</i><b id="oursToday">今天</b><span>一起生活</span></div><div class="ours-stat"><i>♡</i><b id="oursMood">未记录</b><span>今日心情</span></div><div class="ours-stat"><i>☾</i><b id="oursShift">未排班</b><span>今日班次</span></div></section>
          <button class="ours-anniversary" id="oursAnniversaryButton" type="button"><span><small>我 们 的 纪 念 日</small><b id="oursAnniversaryName">等你记下第一个日子</b></span><span class="ours-count" id="oursAnniversaryCount">—<span> 天</span></span></button>
          <section class="ours-destinations"><h3>去 哪 里</h3><a class="ours-room-link" href="/room"><span class="home-icon">${homeIcon("room")}</span><span><b>柯的房间</b><small>状态、游戏、功课，还有只有你们知道的暗号</small></span></a><div class="ours-grid">
            <button class="ours-entry calendar" id="openLifeCalendar" type="button"><span class="home-icon">${homeIcon("calendar")}</span>生活日历</button>
            <a class="ours-entry diary" href="/diary"><span class="home-icon">${homeIcon("diary")}</span>日记</a>
            <a class="ours-entry moments" id="momentsEntry" href="/moments"><span class="home-icon">${homeIcon("moments")}<i class="moments-dot" hidden aria-label="朋友圈有新动静"></i></span>朋友圈</a>
            <button class="ours-entry memory" id="openMemoryCenter" type="button"><span class="home-icon">${homeIcon("memory")}</span>回忆</button>
            <button class="ours-entry anniv" id="openAnniversary" type="button"><span class="home-icon">${homeIcon("heart")}</span>纪念日</button>
            <button class="ours-entry mood" id="openMood" type="button"><span class="home-icon">${homeIcon("mood")}</span>心情</button>
            <a class="ours-entry photos" href="/photos"><span class="home-icon">${homeIcon("photo")}</span>照片</a>
            <a class="ours-entry drawer" href="/drawer"><span class="home-icon">${homeIcon("drawer")}</span>柯的抽屉</a>
          </div></section><p class="ours-note">首页负责感受与陪伴，生活日历负责收好每天发生的事。</p>
        </div>
      </section>
      <section class="life-calendar-page" hidden><div class="life-calendar-top"><button class="life-back" type="button" aria-label="返回我们的首页">‹</button><div><h2>生活日历</h2><p>点一天，再为那一天排班。</p></div></div><div class="calendar-card-host"></div></section>
      <div class="life-tools-store" aria-hidden="true"></div>`);
    const store = $(".life-tools-store", view);
    originals.forEach((node) => { if (node !== calendarCard) store.appendChild(node); });
    if (calendarCard) { calendarCard.classList.add("life-calendar-card"); $(".calendar-card-host", view).appendChild(calendarCard); }
    const toggleCalendar = (open) => {
      $(".ours-home", view).hidden = open; $(".life-calendar-page", view).hidden = !open;
      if ($("#hdrTitle")) $("#hdrTitle").textContent = open ? "生活日历" : "我们的";
      if ($("#hdrSub")) $("#hdrSub").textContent = open ? "每一天，都有我们生活过的痕迹" : "一起走过的日子";
      $("main")?.scrollTo?.({ top: 0, behavior: "smooth" }); if (open) window.loadLife?.();
    };
    $("#openLifeCalendar", view)?.addEventListener("click", () => toggleCalendar(true));
    $(".life-back", view)?.addEventListener("click", () => toggleCalendar(false));
    $("#openMemoryCenter", view)?.addEventListener("click", () => showView("memoryView"));
    $("#openMood", view)?.addEventListener("click", () => openStoredLifeCard(moodCard, "今天的心情"));
    $("#openAnniversary", view)?.addEventListener("click", () => openStoredLifeCard(anniversaryCard, "我们的纪念日"));
    $("#oursAnniversaryButton", view)?.addEventListener("click", () => openStoredLifeCard(anniversaryCard, "我们的纪念日"));
    $("#openLifeMore", view)?.addEventListener("click", () => openMoreLife(concernCard, periodCard));
    loadOursLetter();
  }

  async function updateMomentsActivity() {
    const dot = $(".moments-dot");
    if (!dot || !window.api) return;
    try {
      const status = await (await window.api("/api/moments/status")).json();
      const latest = String(status.last_ke_activity_at || "");
      const seen = localStorage.getItem("moments_seen_at") || "";
      if (!seen && latest) {
        localStorage.setItem("moments_seen_at", latest);
        dot.hidden = true;
        return;
      }
      dot.hidden = !latest || latest <= seen;
    } catch (_) {
      dot.hidden = true;
    }
  }

  async function loadOursLetter() {
    try {
      const rows = await (await window.api("/api/diary")).json();
      const entry = rows.find((row) => row.kind !== "dream" && !row.locked);
      if (!entry) return;
      if ($("#oursLetterLabel")) $("#oursLetterLabel").textContent = `✦ ${(entry.author || "柯")}写给今天的话 ✦`;
      if ($("#oursLetterText")) $("#oursLetterText").textContent = String(entry.content || "").slice(0, 88) || "今天也把你认真放在心上。";
    } catch (_) {}
  }

  function openStoredLifeCard(card, title) {
    if (!card) return;
    const store = card.parentElement;
    const layer = makeSheet(`<div class="sheet-head"><div><h2>${escapeHtml(title)}</h2><p>属于今天的事，可以随时回来修改。</p></div><button class="sheet-close" aria-label="关闭">×</button></div><div class="tool-sheet-host"></div>`);
    $(".tool-sheet-host", layer).appendChild(card);
    const close = () => { store.appendChild(card); layer.remove(); };
    $$(".sheet-close", layer).forEach((button) => button.addEventListener("click", close, { once: true }));
    layer.addEventListener("click", (event) => { if (event.target === layer) close(); });
  }

  function openMoreLife(concernCard, periodCard) {
    const layer = makeSheet(`<div class="sheet-head"><div><h2>更多生活记录</h2><p>需要的时候再打开，不让工具打扰日常。</p></div><button class="sheet-close" aria-label="关闭">×</button></div><div class="more-life-list"><a href="/reading">一起读 <span>›</span></a><a href="/capsule">时间胶囊 <span>›</span></a><a href="/protocol">每日功课 <span>›</span></a><button type="button" data-open-tool="concern">待办与提醒 <span>›</span></button><button type="button" data-open-tool="period">身体记录 <span>›</span></button></div>`);
    $("[data-open-tool='concern']", layer)?.addEventListener("click", () => { layer.remove(); openStoredLifeCard(concernCard, "待办与提醒"); });
    $("[data-open-tool='period']", layer)?.addEventListener("click", () => { layer.remove(); openStoredLifeCard(periodCard, "身体记录"); });
  }

  function tuneSettings(view) {
    view.id = "settingsView";
    view.insertAdjacentHTML("afterbegin", `<h2 class="view-title">设置</h2><div class="view-sub">不打扰日常，需要时再来这里。</div>`);
    const oldTitle = view.querySelector(":scope > h2:not(.view-title)");
    if (oldTitle) oldTitle.remove();
  }

  function rebuildNav(nav) {
    nav.innerHTML = `<button data-v="chatView" class="on"><span class="ic">◌</span>柯</button><button data-v="memoryView"><span class="ic">${homeIcon("memory")}</span>回忆<span class="nav-badge" id="memoryNavBadge"></span></button><button data-v="oursView"><span class="ic">⌁</span>我们的</button>`;
  }

  function bindNavigation(nav) {
    $$("button[data-v]", nav).forEach((button) => button.addEventListener("click", () => showView(button.dataset.v)));
  }

  function showView(id) {
    const footer = $("#footer");
    $$(".view").forEach((view) => view.classList.toggle("active", view.id === id));
    $$("nav button").forEach((button) => button.classList.toggle("on", button.dataset.v === id));
    if (footer) footer.style.display = id === "chatView" ? "block" : "none";
    const labels = { chatView: [window.AI_NAME || "柯", "佳佳和柯的家"], memoryView: ["回忆", "被认真珍藏的事"], oursView: ["我们的", "一起走过的日子"], settingsView: ["设置", "需要时再打开"] };
    const label = labels[id] || labels.chatView;
    if ($("#hdrTitle")) $("#hdrTitle").textContent = label[0];
    if ($("#hdrSub")) $("#hdrSub").textContent = label[1];
    const main = $("main");
    if (main) main.scrollTop = 0;
    try {
      if (id === "chatView" && typeof window.scrollHard === "function") window.scrollHard();
      if (id === "oursView" && typeof window.loadLife === "function") window.loadLife();
      if (id === "settingsView" && typeof window.loadUsage === "function") window.loadUsage();
    } catch (_) {}
  }

  function bindMemoryCenter(view) {
    $$(".memory-tab", view).forEach((tab) => tab.addEventListener("click", () => openMemoryPanel(tab.dataset.memoryTab)));
    $("#memorySearch", view)?.addEventListener("input", (event) => {
      clearTimeout(memorySearchTimer);
      memorySearchTimer = setTimeout(() => loadMemoryCards(event.target.value.trim()), 260);
    });
    $("#addMemoryToggle", view)?.addEventListener("click", () => {
      const card = $("#addMemoryCard", view);
      card.hidden = !card.hidden;
      if (!card.hidden) $("#pcontent", card)?.focus();
    });
  }

  function openMemoryPanel(name) {
    const tabs = $(".memory-tabs");
    if (tabs) tabs.dataset.active = name;
    $$(".memory-tab").forEach((tab) => tab.classList.toggle("on", tab.dataset.memoryTab === name));
    $$(".memory-panel").forEach((panel) => panel.classList.toggle("active", panel.dataset.memoryPanel === name));
    if (name === "library" || name === "timeline") loadMemoryCards($("#memorySearch")?.value?.trim() || "");
  }

  async function loadPendingCount() {
    try {
      const rows = await (await window.api("/api/memory/pending")).json();
      const count = Array.isArray(rows) ? rows.length : 0;
      $$("#memoryNavBadge,.memory-tab-badge").forEach((badge) => {
        badge.textContent = count > 9 ? "9+" : String(count);
        badge.style.display = count ? "block" : "none";
      });
      const summary = $("#pendingSummary");
      if (summary) summary.textContent = count ? `有 ${count} 件事想请你看看，你点头以后才会记住。` : "现在没有需要确认的事，安安静静的。";
    } catch (_) {
      const summary = $("#pendingSummary");
      if (summary) summary.textContent = "点开就能看看柯最近想记住什么。";
    }
  }

  async function loadMemoryCards(query = "") {
    const list = $("#memoryCards");
    const timeline = $("#memoryTimeline");
    if (!list || !timeline) return;
    list.innerHTML = `<div class="memory-empty">正在翻开卡片库…</div>`;
    try {
      const suffix = query ? `&q=${encodeURIComponent(query)}` : "";
      const rows = await (await window.api(`/api/memory/cards?store=l2&status=active${suffix}`)).json();
      memoryCards = Array.isArray(rows) ? rows : [];
      renderMemoryCards(list, memoryCards);
      renderTimeline(timeline, memoryCards);
    } catch (_) {
      list.innerHTML = `<div class="card memory-empty">这会儿没能翻开卡片库，过一会儿再试试。</div>`;
      timeline.innerHTML = `<div class="card memory-empty">时间线暂时没有展开。</div>`;
    }
  }

  function renderMemoryCards(list, rows) {
    if (!rows.length) {
      list.innerHTML = `<div class="card memory-empty">还没有找到这段回忆。<br>也许换一个更自然的词试试。</div>`;
      return;
    }
    list.innerHTML = rows.map((card) => {
      const content = escapeHtml(card.content || "一件还没写下标题的事");
      return `<button class="card memory-card" data-memory-id="${Number(card.id)}" data-memory-store="${escapeHtml(card.store || "l2")}"><span class="memory-card-top"><span class="memory-kind">${escapeHtml(categoryName(card))}</span><span class="memory-date">${escapeHtml(formatDate(card.created_at))}</span></span><h3>${content}</h3><p class="memory-understanding">柯的理解：${content}</p><span class="memory-source">${escapeHtml(sourceNames[card.source] || "你们一起留下的")} · ${card.store === "private" ? "只在单聊里" : "来自你们的相处"}</span></button>`;
    }).join("");
    $$("[data-memory-id]", list).forEach((button) => button.addEventListener("click", () => openMemoryDetail(button.dataset.memoryId, button.dataset.memoryStore)));
  }

  function renderTimeline(list, rows) {
    if (!rows.length) {
      list.innerHTML = `<div class="card memory-empty">时间线还空着，新的回忆会慢慢落在这里。</div>`;
      return;
    }
    list.innerHTML = rows.slice().sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))).map((card) => `<article class="story-entry"><span class="story-dot" aria-hidden="true"></span><time class="story-date">${escapeHtml(storyDate(card.created_at))} · ${escapeHtml(categoryName(card))}</time><button class="card story-card" data-memory-id="${Number(card.id)}" data-memory-store="${escapeHtml(card.store || "l2")}"><p>“${escapeHtml(card.content || "一段回忆")}”</p><small>柯记住了 · ${escapeHtml(sourceNames[card.source] || "你们一起留下的")}</small></button></article>`).join("");
    $$("[data-memory-id]", list).forEach((button) => button.addEventListener("click", () => openMemoryDetail(button.dataset.memoryId, button.dataset.memoryStore)));
  }

  async function openMemoryDetail(id, store) {
    const layer = makeSheet(`<div class="sheet-head"><div><h2>这段回忆</h2><p>可以随时一起确认和改正</p></div><button class="sheet-close" aria-label="关闭">×</button></div><div id="memoryDetailBody"><div class="memory-empty">柯正在把它想清楚…</div></div>`);
    try {
      const card = await (await window.api(`/api/memory/card?id=${encodeURIComponent(id)}&store=${encodeURIComponent(store || "l2")}`)).json();
      const used = Array.isArray(card.used) ? card.used : [];
      $("#memoryDetailBody", layer).innerHTML = `<section class="detail-section"><h3>记住了什么</h3><p>${escapeHtml(card.content || "")}</p></section><section class="detail-section"><h3>柯是怎么理解的</h3><p>${escapeHtml(card.content || "柯把它当作一件值得认真放在心上的事。")}</p></section><section class="detail-section"><h3>为什么这样记</h3><p>${escapeHtml(sourceNames[card.source] || "这是你们相处里留下的一段线索。")}</p></section><section class="detail-section"><h3>它现在还准确吗</h3><small>你的感受变了，回忆也可以跟着更新。</small><div class="accuracy-actions"><button data-accuracy="yes">仍然准确</button><button data-accuracy="change">有一点变化</button><button data-accuracy="no">已经不是这样了</button></div><textarea id="memoryEditText" rows="3" hidden>${escapeHtml(card.content || "")}</textarea><button id="memoryEditSave" class="btn" hidden>保存新的理解</button></section><section class="detail-section"><h3>修改历史</h3><p>${used.length ? `最近被想起过 ${used.length} 次。最近一次，是在 ${escapeHtml(formatDate(used[0]?.at))} 的对话里。` : "它还没有在最近的对话里被想起。"}</p></section>`;
      bindDetailActions(layer, card, store || "l2");
    } catch (_) {
      $("#memoryDetailBody", layer).innerHTML = `<div class="memory-empty">这段回忆暂时没有打开，过一会儿再来看看。</div>`;
    }
  }

  function bindDetailActions(layer, card, store) {
    $("[data-accuracy=yes]", layer)?.addEventListener("click", () => { layer.remove(); window.toast?.("好，柯会继续这样记着"); });
    $("[data-accuracy=change]", layer)?.addEventListener("click", () => {
      const text = $("#memoryEditText", layer); const save = $("#memoryEditSave", layer);
      text.hidden = false; save.hidden = false; text.focus();
    });
    $("#memoryEditSave", layer)?.addEventListener("click", async () => {
      const content = $("#memoryEditText", layer).value.trim();
      if (!content) return;
      try { await window.api("/api/memory/card/edit", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ id: Number(card.id), store, content }) }); layer.remove(); loadMemoryCards($("#memorySearch")?.value || ""); window.toast?.("新的理解已经收好了"); } catch (_) { window.toast?.("这次没改好，再试一下"); }
    });
    $("[data-accuracy=no]", layer)?.addEventListener("click", async () => {
      if (!confirm("先把它收进七天冷静期？这七天里随时可以找回来。")) return;
      try { await window.api("/api/memory/card/forget", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ id: Number(card.id), store }) }); layer.remove(); loadMemoryCards(); window.toast?.("先收进冷静期了，七天内随时能找回"); } catch (_) { window.toast?.("这次没收好，再试一下"); }
    });
  }

  function bindStarMap(view) {
    $("#starZoom", view)?.addEventListener("input", (event) => $("#starMap", view).style.setProperty("--star-scale", Number(event.target.value) / 100));
    $("#starTime", view)?.addEventListener("input", (event) => {
      const visible = Math.max(1, Math.ceil((Number(event.target.value) / 100) * 6));
      $$(".star-node:not(.center)", view).forEach((node, index) => { node.style.opacity = index < visible ? "1" : ".18"; });
    });
    $$("[data-star-topic]", view).forEach((node) => node.addEventListener("click", () => {
      const topic = node.dataset.starTopic || "";
      openMemoryPanel("library");
      const input = $("#memorySearch");
      if (input) input.value = topic;
      loadMemoryCards(topic);
    }));
  }

  function makeSheet(content) {
    $(".bottom-sheet-layer")?.remove();
    const layer = document.createElement("div");
    layer.className = "bottom-sheet-layer";
    layer.innerHTML = `<section class="bottom-sheet" role="dialog" aria-modal="true"><div class="sheet-handle"></div>${content}</section>`;
    layer.addEventListener("click", (event) => { if (event.target === layer || event.target.closest(".sheet-close")) layer.remove(); });
    document.body.appendChild(layer);
    return layer;
  }

  function categoryName(card) {
    const topic = String(card.topic || "").toLowerCase();
    if (topicNames[topic]) return topicNames[topic];
    const type = String(card.type || "").toUpperCase();
    return ({ MEMORY: "日常", EVENT: "共同经历", MOMENT: "一个瞬间", PROMISE: "约定", WISHLIST: "未来" })[type] || card.topic || "一段回忆";
  }

  function formatDate(value) {
    const match = String(value || "").match(/(\d{4})-(\d{2})-(\d{2})/);
    return match ? `${Number(match[2])}月${Number(match[3])}日` : "很久以前";
  }

  function storyDate(value) {
    const match = String(value || "").match(/(\d{4})-(\d{2})-(\d{2})/);
    if (!match) return "很久以前";
    const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    const today = new Date();
    const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const days = Math.round((start - date) / 86400000);
    if (days === 0) return "今天";
    if (days === 1) return "昨天";
    return `${Number(match[2])}月${Number(match[3])}日`;
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>\"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '\"': "&quot;" })[char]);
  }

  window.goodloveMakeSheet = makeSheet;
})();
