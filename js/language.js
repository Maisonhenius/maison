/*
 * Maison Henius — visitor language suggestion + language dropdown menus.
 *
 * The translation itself is done by Weglot (loaded in layout.html only when the
 * WEGLOT_API_KEY env var is set). This file adds the brand-styled parts:
 *   1. A one-time banner that suggests the visitor's local language, based on
 *      their country (read from the device time zone — no tracking, no IP
 *      lookup) and falling back to their browser language. The visitor can
 *      accept or keep English; the choice is remembered on that device.
 *   2. Language dropdown menus: every element with [data-lang-menu] (header
 *      nav, mobile menu, footer) becomes a "globe + language" dropdown.
 *
 * Languages: English (original) + French. To offer another language later, add
 * it in the Weglot dashboard AND to LANGS / BANNER / TZ_LANG below.
 *
 * Without Weglot on the page, everything here stays dormant (menus stay
 * hidden, no banner), so deploying this file alone changes nothing visible.
 */
(function () {
  if (window._maisonLangBound) return;
  window._maisonLangBound = true;

  var ORIGINAL = 'en';
  var STORE_KEY = 'maison_lang_choice';

  // Languages offered on the site, in menu order. Must match the languages enabled in Weglot.
  var LANGS = {
    en: { name: 'English',  short: 'EN' },
    fr: { name: 'Français', short: 'FR' }
  };

  // Banner copy, written in the suggested language (never machine-translated).
  var BANNER = {
    fr: 'Souhaitez-vous découvrir la Maison en français\u202F?'
  };
  var KEEP_ORIGINAL = 'Continue in English';

  // Country → language, via the device time zone. Multilingual countries (Belgium,
  // Switzerland, Canada outside Quebec…) are left out on purpose: there the visitor's
  // browser language decides instead.
  var TZ_LANG = {};
  function map(lang, zones) { zones.split(' ').forEach(function (z) { TZ_LANG[z] = lang; }); }
  map('fr', 'Europe/Paris Europe/Monaco Europe/Luxembourg America/Montreal ' +
            'Indian/Reunion America/Martinique America/Guadeloupe America/Cayenne ' +
            'Indian/Mayotte Pacific/Tahiti Pacific/Noumea');

  var GLOBE = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>' +
    '<path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z"/></svg>';
  var CARET = '<svg class="lang-menu__caret" width="9" height="9" viewBox="0 0 10 10" aria-hidden="true">' +
    '<path d="M1.5 3.5L5 7l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>';

  function store(key, value) {
    try { localStorage.setItem(key, value); } catch (e) {}
  }
  function read(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  function weglotReady() {
    return !!(window.Weglot && window.Weglot.initialized);
  }
  function currentLang() {
    var l = weglotReady() ? window.Weglot.getCurrentLang() : ORIGINAL;
    return LANGS[l] ? l : ORIGINAL;
  }

  // Only offer languages that are switched on in the Weglot project (plan limits,
  // languages added later): the menu and banner never show an option that does nothing.
  function enabledLangs() {
    var avail = null;
    try { avail = weglotReady() && window.Weglot.getAvailableLanguages ? window.Weglot.getAvailableLanguages() : null; } catch (e) {}
    return Object.keys(LANGS).filter(function (code) {
      return code === ORIGINAL || !avail || avail.indexOf(code) !== -1;
    });
  }
  function isEnabled(lang) { return enabledLangs().indexOf(lang) !== -1; }

  function suggestedLang() {
    var tz = '';
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) {}
    if (TZ_LANG[tz]) return TZ_LANG[tz];
    var prefs = navigator.languages || [navigator.language || ''];
    for (var i = 0; i < prefs.length; i++) {
      var code = String(prefs[i]).slice(0, 2).toLowerCase();
      if (code === ORIGINAL) return null;          // they already prefer the original
      if (LANGS[code]) return code;
    }
    return null;
  }

  // Keep <html lang> in sync (screen readers, browser hyphenation) and re-measure
  // scroll animations, since translated text can change section heights.
  function applyDirection(lang) {
    document.documentElement.setAttribute('lang', lang);
    if (window.ScrollTrigger) { try { window.ScrollTrigger.refresh(); } catch (e) {} }
  }

  function switchTo(lang) {
    if (!weglotReady() || !LANGS[lang] || !isEnabled(lang)) return;
    store(STORE_KEY, lang);
    if (lang !== currentLang()) window.Weglot.switchTo(lang);
    applyDirection(lang);
    renderMenus();
  }

  /* ---------- Suggestion banner ---------- */

  function removeBanner() {
    var el = document.getElementById('langBanner');
    if (!el) return;
    el.classList.remove('is-visible');
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 450);
  }

  function showBannerIfNeeded() {
    if (!weglotReady() || read(STORE_KEY) || document.getElementById('langBanner')) return;
    var lang = suggestedLang();
    if (!lang || lang === ORIGINAL || !BANNER[lang] || !isEnabled(lang) || currentLang() !== ORIGINAL) return;

    var el = document.createElement('div');
    el.id = 'langBanner';
    el.className = 'lang-banner';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', 'Language');
    el.setAttribute('data-wg-notranslate', '');   // keep this text exactly as written
    el.innerHTML =
      '<p class="lang-banner__question" lang="' + lang + '"></p>' +
      '<div class="lang-banner__actions">' +
      '<button type="button" class="lang-banner__yes" lang="' + lang + '"></button>' +
      '<button type="button" class="lang-banner__no" lang="en"></button>' +
      '</div>';
    el.querySelector('.lang-banner__question').textContent = BANNER[lang];
    el.querySelector('.lang-banner__yes').textContent = LANGS[lang].name;
    el.querySelector('.lang-banner__no').textContent = KEEP_ORIGINAL;
    el.querySelector('.lang-banner__yes').addEventListener('click', function () { switchTo(lang); removeBanner(); });
    el.querySelector('.lang-banner__no').addEventListener('click', function () { store(STORE_KEY, ORIGINAL); removeBanner(); });
    document.body.appendChild(el);
    requestAnimationFrame(function () { requestAnimationFrame(function () { el.classList.add('is-visible'); }); });
  }

  /* ---------- Dropdown menus ([data-lang-menu]) ---------- */

  function closeMenus(except) {
    document.querySelectorAll('.lang-menu.is-open').forEach(function (m) {
      if (m === except) return;
      m.classList.remove('is-open');
      var t = m.querySelector('.lang-menu__toggle');
      if (t) t.setAttribute('aria-expanded', 'false');
    });
  }

  function buildMenu(box, active) {
    var compact = box.getAttribute('data-lang-menu') === 'compact';   // header: "EN"; footer: "English"
    box.innerHTML = '';
    box.setAttribute('data-wg-notranslate', '');

    var wrap = document.createElement('div');
    wrap.className = 'lang-menu' + (box.hasAttribute('data-lang-menu-up') ? ' lang-menu--up' : '');

    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'lang-menu__toggle';
    toggle.setAttribute('aria-haspopup', 'listbox');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Language: ' + LANGS[active].name);
    toggle.innerHTML = GLOBE + '<span class="lang-menu__current"></span>' + CARET;
    var current = toggle.querySelector('.lang-menu__current');
    current.textContent = compact ? LANGS[active].short : LANGS[active].name;
    if (!compact) current.setAttribute('lang', active);

    var list = document.createElement('ul');
    list.className = 'lang-menu__list';
    list.setAttribute('role', 'listbox');
    enabledLangs().forEach(function (code) {
      var li = document.createElement('li');
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'lang-menu__option' + (code === active ? ' is-active' : '');
      b.setAttribute('role', 'option');
      b.setAttribute('aria-selected', code === active ? 'true' : 'false');
      b.setAttribute('lang', code);
      b.textContent = LANGS[code].name;
      b.addEventListener('click', function () { closeMenus(); switchTo(code); removeBanner(); });
      li.appendChild(b);
      list.appendChild(li);
    });

    toggle.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = !wrap.classList.contains('is-open');
      closeMenus(wrap);
      wrap.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) { var a = list.querySelector('.is-active'); if (a) a.focus(); }
    });

    wrap.appendChild(toggle);
    wrap.appendChild(list);
    box.appendChild(wrap);
    box.hidden = false;
  }

  function renderMenus() {
    var boxes = document.querySelectorAll('[data-lang-menu]');
    // Hide the menus when Weglot is off or only the original language is enabled.
    if (!weglotReady() || enabledLangs().length < 2) { boxes.forEach(function (b) { b.hidden = true; }); return; }
    var active = currentLang();
    boxes.forEach(function (box) { buildMenu(box, active); });
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest || !e.target.closest('.lang-menu')) closeMenus();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeMenus();
  });

  /* ---------- Lifecycle ---------- */

  function onPage() {
    if (!weglotReady()) return;
    // A visitor who picked a language the site no longer offers (e.g. Arabic,
    // removed later) goes back to the original instead of staying stuck in it.
    var wg = window.Weglot.getCurrentLang();
    if (wg !== ORIGINAL && !LANGS[wg]) { window.Weglot.switchTo(ORIGINAL); store(STORE_KEY, ORIGINAL); }
    applyDirection(currentLang());
    renderMenus();
    showBannerIfNeeded();
  }

  function boot() {
    if (!window.Weglot) return;
    if (window.Weglot.initialized) onPage();
    else window.Weglot.on('initialized', onPage);
    window.Weglot.on('languageChanged', function (lang) { applyDirection(lang); renderMenus(); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
  // Turbo swaps the <body> on every navigation — re-apply the menus, direction and banner.
  document.addEventListener('turbo:load', onPage);

  // Weglot only translates a page on a full load: it does not follow Turbo's in-place
  // <body> swap (tested: neither addNodes nor re-switching re-translates the new body).
  // So while a translated language is active, links do a full page load instead of a
  // Turbo visit. English visitors keep Turbo's instant navigation.
  document.addEventListener('turbo:before-visit', function (e) {
    if (currentLang() === ORIGINAL) return;
    e.preventDefault();
    window.location.href = e.detail.url;
  });
})();
