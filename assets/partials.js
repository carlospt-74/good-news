(function () {
  var ROOT = "/";
  var CATEGORIES = [["Deportes", "deportes"], ["Economía", "economia"], ["Ciencia y Salud", "ciencia-y-salud"], ["Medio Ambiente", "medio-ambiente"], ["Sociedad", "sociedad"], ["Tecnología", "tecnologia"], ["Cultura", "cultura"], ["IA", "ia"]];
  var ICONS = ROOT + "assets/icons.svg#";
  var YEAR = new Date().getFullYear();

  function icon(id) { return '<svg class="i" aria-hidden="true"><use href="' + ICONS + id + '"/></svg>'; }
  var WORDMARK = '<span class="wm"><b>buenas noticias<span class="dot" aria-hidden="true"></span></b><small>Always positive</small></span>';

  function navLinksHtml(activeCategory) {
    return CATEGORIES.map(function (item) {
      var name = item[0], slug = item[1];
      var cur = (name === activeCategory) ? ' aria-current="page"' : '';
      return '<a href="' + ROOT + slug + '/"' + cur + '>' + name + '</a>';
    }).join('');
  }

  function headerInnerHtml(activeCategory) {
    return '<div class="wrap bar">' +
      '<a class="brand" href="' + ROOT + '" aria-label="Buenas Noticias, inicio">' + WORDMARK + '</a>' +
      '<nav id="site-nav" aria-label="Categorías">' + navLinksHtml(activeCategory) + '</nav>' +
      '<div class="actions">' +
        '<button class="iconbtn" id="menu" type="button" aria-label="Abrir menú de categorías" aria-expanded="false" aria-controls="site-nav">' + icon('i-menu') + '</button>' +
        '<button class="iconbtn" id="theme" type="button" aria-label="Cambiar tema claro/oscuro">' + icon('i-moon') + '</button>' +
      '</div></div>';
  }

  function footerInnerHtml() {
    return '<div class="wrap">' +
      '<a class="flogo brand" href="' + ROOT + '" aria-label="Buenas Noticias, inicio">' + WORDMARK + '</a>' +
      '<div class="note">' +
        '<p><strong>Buenas Noticias no aloja el contenido completo de las notas; siempre enlazamos a la fuente original.</strong></p>' +
        '<p>Cada resumen es una redacción original a partir de la nota fuente, nunca una copia. Los avatares muestran las iniciales del medio, no fotos de periodistas. Este portal no tiene reporteros propios, solo selecciona y resume buenas noticias ya publicadas por medios reales.</p>' +
      '</div>' +
      '<div class="legal"><span>© ' + YEAR + ' Buenas Noticias · Always positive</span><span>Fotos: Pexels</span></div>' +
      '</div>';
  }

  var headerMount = document.getElementById('site-header-mount');
  if (headerMount) {
    headerMount.innerHTML = headerInnerHtml(document.body.getAttribute('data-active-category') || '');
  }
  var footerMount = document.getElementById('site-footer-mount');
  if (footerMount) {
    footerMount.innerHTML = footerInnerHtml();
  }

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Tema claro/oscuro: respeta la preferencia del sistema; el botón la
  // sobrescribe y se recuerda por visitante (localStorage puede fallar en
  // modo privado, por eso el try/catch).
  var root = document.documentElement;
  var themeBtn = document.getElementById('theme');
  function isDark() { return root.dataset.theme ? root.dataset.theme === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches; }
  function syncThemeIcon() { if (themeBtn) themeBtn.querySelector('use').setAttribute('href', ICONS + (isDark() ? 'i-sun' : 'i-moon')); }
  try { var saved = localStorage.getItem('bn-theme'); if (saved) root.dataset.theme = saved; } catch (e) {}
  syncThemeIcon();
  if (themeBtn) themeBtn.addEventListener('click', function () {
    root.dataset.theme = isDark() ? 'light' : 'dark';
    try { localStorage.setItem('bn-theme', root.dataset.theme); } catch (e) {}
    syncThemeIcon();
  });

  // Menú de categorías en pantallas angostas.
  var menuBtn = document.getElementById('menu'), nav = document.getElementById('site-nav');
  if (menuBtn && nav) menuBtn.addEventListener('click', function () {
    var open = nav.classList.toggle('open');
    menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  // Brillo que sigue al cursor sobre las tarjetas.
  document.addEventListener('pointermove', function (e) {
    var c = e.target.closest && e.target.closest('.card'); if (!c) return;
    var r = c.getBoundingClientRect();
    c.style.setProperty('--x', (e.clientX - r.left) + 'px');
    c.style.setProperty('--y', (e.clientY - r.top) + 'px');
  });

  // Palabra que rota en el titular del home.
  var words = document.querySelectorAll('.rot span');
  if (words.length && !reduce) {
    var w = 0;
    setInterval(function () { words[w].classList.remove('on'); w = (w + 1) % words.length; words[w].classList.add('on'); }, 2600);
  }

  // Contadores del home.
  document.querySelectorAll('[data-count]').forEach(function (el) {
    var to = +el.getAttribute('data-count');
    if (reduce) { el.textContent = to; return; }
    var t0 = performance.now();
    (function tick(t) {
      var p = Math.min((t - t0) / 1200, 1);
      el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(tick);
    })(t0);
  });

  // Pestañas de "Explora por tema": "Todas" muestra las más recientes; cada
  // categoría muestra sus notas más recientes y un enlace a su página.
  var tabs = document.getElementById('tabs'), grid = document.getElementById('grid'), catMore = document.getElementById('cat-more');
  if (tabs && grid) tabs.addEventListener('click', function (e) {
    var b = e.target.closest('button'); if (!b) return;
    var k = b.getAttribute('data-k');
    tabs.querySelectorAll('button').forEach(function (x) { x.setAttribute('aria-selected', x === b ? 'true' : 'false'); });
    grid.querySelectorAll('.card').forEach(function (c) {
      c.hidden = k === 'all' ? !c.hasAttribute('data-all') : !(c.getAttribute('data-cat') === k && c.hasAttribute('data-top'));
    });
    if (catMore) {
      catMore.hidden = k === 'all';
      if (k !== 'all') { catMore.href = ROOT + k + '/'; catMore.querySelector('span').textContent = 'Ver todas las de ' + b.textContent.trim(); }
    }
  });

  // Copiar enlace en la página de nota.
  var copyBtn = document.getElementById('copy');
  if (copyBtn) copyBtn.addEventListener('click', function () {
    var label = copyBtn.querySelector('span');
    if (!navigator.clipboard) { label.textContent = ' No se pudo copiar'; return; }
    navigator.clipboard.writeText(location.href).then(
      function () { label.textContent = ' ¡Enlace copiado!'; },
      function () { label.textContent = ' No se pudo copiar'; });
  });
})();
