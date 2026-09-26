(function () {
  var ROOT = "/good-news/";
  var CATEGORIES = [["Deportes", "deportes"], ["Economía", "economia"], ["Ciencia y Salud", "ciencia-y-salud"], ["Medio Ambiente", "medio-ambiente"], ["Sociedad", "sociedad"], ["Tecnología", "tecnologia"], ["Cultura", "cultura"], ["IA", "ia"]];

  function navLinksHtml(activeCategory) {
    return CATEGORIES.map(function (item) {
      var name = item[0], slug = item[1];
      var cls = (name === activeCategory) ? ' class="active"' : '';
      return '<a href="' + ROOT + slug + '/"' + cls + '>' + name + '</a>';
    }).join('');
  }

  function headerInnerHtml(activeCategory) {
    return '<div class="header-inner">' +
      '<a href="' + ROOT + '" class="logo"><img src="' + ROOT + 'assets/logo.png" alt="Buenas Noticias" class="logo-img"></a>' +
      '<button class="menu-toggle" onclick="document.querySelector(\'nav.categories\').classList.toggle(\'open\')">Categorías &darr;</button>' +
      '<nav class="categories">' + navLinksHtml(activeCategory) + '</nav>' +
      '</div>';
  }

  function footerInnerHtml() {
    return '<div class="foot-inner">' +
      '<a href="' + ROOT + '" class="logo"><img src="' + ROOT + 'assets/logo.png" alt="Buenas Noticias" class="logo-img"></a>' +
      '<div class="foot-links">' + navLinksHtml(null) + '</div>' +
      '<p class="legal">Buenas Noticias no aloja el contenido completo de las notas; siempre enlazamos a la fuente original.</p>' +
      '<p class="disclaimer">Cada resumen es una redacción original a partir de la nota fuente, nunca una copia. Los avatares muestran las iniciales del medio, no fotos de periodistas -- este portal no tiene reporteros propios, solo selecciona y resume buenas noticias ya publicadas por medios reales.</p>' +
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
})();
