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
 *      nav + footer) becomes a "globe + language" dropdown.
 *   3. Right-to-left layout + Arabic fonts when Arabic is active.
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
    en: { name: 'English',  short: 'EN', rtl: false },
    ar: { name: 'العربية',  short: 'AR', rtl: true },
    fr: { name: 'Français', short: 'FR', rtl: false },
    es: { name: 'Español',  short: 'ES', rtl: false },
    it: { name: 'Italiano', short: 'IT', rtl: false },
    ru: { name: 'Русский',  short: 'RU', rtl: false }
  };

  // Banner copy, written in the suggested language (never machine-translated).
  var BANNER = {
    ar: 'هل تودّ اكتشاف الدار باللغة العربية؟',
    fr: 'Souhaitez-vous découvrir la Maison en français ?',
    es: '¿Desea descubrir la Maison en español?',
    it: 'Desidera scoprire la Maison in italiano?',
    ru: 'Хотите открыть для себя Дом на русском языке?'
  };
  var KEEP_ORIGINAL = 'Continue in English';

  // Country → language, via the device time zone (covers each country's main zones).
  // Multilingual countries (Switzerland, Belgium, Canada outside Quebec…) are left out
  // on purpose: there the visitor's browser language decides instead.
  var TZ_LANG = {};
  function map(lang, zones) { zones.split(' ').forEach(function (z) { TZ_LANG[z] = lang; }); }
  map('ar', 'Asia/Amman Asia/Riyadh Asia/Dubai Asia/Kuwait Asia/Qatar Asia/Bahrain Asia/Muscat ' +
            'Asia/Baghdad Asia/Beirut Asia/Damascus Asia/Aden Asia/Gaza Asia/Hebron Africa/Cairo ' +
            'Africa/Casablanca Africa/Algiers Africa/Tunis Africa/Tripoli Africa/Khartoum Africa/Nouakchott');
  map('fr', 'Europe/Paris Europe/Monaco Europe/Luxembourg America/Montreal');
  map('es', 'Europe/Madrid Atlantic/Canary Africa/Ceuta America/Mexico_City America/Cancun ' +
            'America/Monterrey America/Merida America/Chihuahua America/Tijuana America/Bogota ' +
            'America/Lima America/Santiago America/Argentina/Buenos_Aires America/Buenos_Aires ' +
            'America/Argentina/Cordoba America/Caracas America/Montevideo America/Asuncion ' +
            'America/La_Paz America/Guayaquil America/Panama America/Costa_Rica America/Guatemala ' +
            'America/El_Salvador America/Tegucigalpa America/Managua America/Santo_Domingo America/Havana');
  map('it', 'Europe/Rome Europe/Vatican Europe/San_Marino');
  map('ru', 'Europe/Moscow Europe/Kaliningrad Europe/Samara Europe/Volgograd Europe/Kirov ' +
            'Europe/Saratov Europe/Ulyanovsk Europe/Astrakhan Europe/Minsk Asia/Yekaterinburg ' +
            'Asia/Omsk Asia/Novosibirsk Asia/Barnaul Asia/Tomsk Asia/Novokuznetsk Asia/Krasnoyarsk ' +
            'Asia/Irkutsk Asia/Chita Asia/Yakutsk Asia/Vladivostok Asia/Sakhalin Asia/Magadan ' +
            'Asia/Srednekolymsk Asia/Kamchatka Asia/Anadyr');

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

  // Direction + font hooks for the CSS in language.css.
  function applyDirection(lang) {
    var root = document.documentElement;
    var rtl = !!(LANGS[lang] && LANGS[lang].rtl);
    root.setAttribute('dir', rtl ? 'rtl' : 'ltr');
    root.setAttribute('lang', lang);
    if (rtl && !document.getElementById('maisonArabicFonts')) {
      var link = document.createElement('link');
      link.id = 'maisonArabicFonts';
      link.rel = 'stylesheet';
      link.href = 'https://fonts.googleapis.com/css2?family=Amiri:wght@400;700&family=IBM+Plex+Sans+Arabic:wght@300;400;500&display=swap';
      document.head.appendChild(link);
    }
    if (window.ScrollTrigger) { try { window.ScrollTrigger.refresh(); } catch (e) {} }
  }

  function switchTo(lang) {
    if (!weglotReady() || !LANGS[lang]) return;
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
    if (!lang || lang === ORIGINAL || !BANNER[lang] || currentLang() !== ORIGINAL) return;

    var dir = LANGS[lang].rtl ? 'rtl' : 'ltr';
    var el = document.createElement('div');
    el.id = 'langBanner';
    el.className = 'lang-banner';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', 'Language');
    el.setAttribute('data-wg-notranslate', '');   // keep this text exactly as written
    el.innerHTML =
      '<p class="lang-banner__question" lang="' + lang + '" dir="' + dir + '"></p>' +
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
    Object.keys(LANGS).forEach(function (code) {
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
    if (!weglotReady()) { boxes.forEach(function (b) { b.hidden = true; }); return; }
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
})();
