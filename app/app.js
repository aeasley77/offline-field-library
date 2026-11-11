const nav = document.querySelector('#nav');
const cards = document.querySelector('#cards');
const rail = document.querySelector('.rail');
const searchResults = document.querySelector('#search-results');
let categories = [];

const closeNav = () => rail.classList.remove('open');
const fmt = n => n >= 1e12 ? (n / 1e12).toFixed(2) + ' TB' : n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : n >= 1e6 ? (n / 1e6).toFixed(0) + ' MB' : (n / 1e3).toFixed(0) + ' KB';
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const contentHref = path => '/content/' + path.split('/').map(encodeURIComponent).join('/');

function renderResults(box, data, query, scopeLabel = '') {
  if (data.error) {
    box.innerHTML = `<p>${esc(data.error)} Search will work as the index becomes available.</p>`;
    return;
  }
  const matches = data.results || [];
  box.innerHTML = `<h3>${matches.length} result${matches.length === 1 ? '' : 's'} for “${esc(query)}”${scopeLabel ? ` · ${esc(scopeLabel)}` : ''}</h3>` +
    (matches.length ? matches.map(r => {
      const location = r.path.split('/').slice(1, -1).join(' / ');
      const snippet = esc(r.snippet || '').replace(/&lt;mark&gt;/g, '<mark>').replace(/&lt;\/mark&gt;/g, '</mark>');
      return `<div class="result"><a href="${contentHref(r.path)}">${esc(r.title)}</a><p>${location ? `${esc(location)} · ` : ''}${snippet}</p></div>`;
    }).join('') : '<p>No indexed matches. Newly added documents may still be indexing.</p>');
  box.scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function search(query, options = {}) {
  const params = new URLSearchParams({q: query, ...options});
  const response = await fetch('/api/search?' + params.toString());
  return response.json();
}

function showCategory(slug) {
  const category = categories.find(item => item.slug === slug);
  if (!category) return;
  searchResults.hidden = false;
  const header = `<h3>${esc(category.title)}</h3><p>${esc(category.description)}</p>`;

  if (slug === 'military') {
    searchResults.innerHTML = header +
      `<p>${category.item_count.toLocaleString()} local PDF manuals. Search this collection by title or text, then narrow by collection and branch. General search excludes these manuals unless you enable its military toggle. <a href="https://www.trex-arms.com/field-manual-vault" target="_blank" rel="noopener">Open the Vault catalog ↗</a></p>` +
      `<form id="military-search-form" class="military-search"><input id="military-query" type="search" placeholder="Search military manuals…" minlength="2" required>` +
      `<select id="military-collection" aria-label="Collection"><option value="">All collections</option><option>Current Doctrine</option><option>Recent Archive</option><option>Lessons Learned</option><option>Historic</option></select>` +
      `<select id="military-branch" aria-label="Branch"><option value="">All branches</option><option>Army</option><option>Navy</option><option>Air Force</option><option>Marine Corps</option><option>Joint</option></select>` +
      `<button>SEARCH MANUALS <span>↗</span></button></form><div id="military-results" class="military-results"></div>` +
      `<p class="collection-note">The folder layout remains on the SSD as collection / branch / publication series. PDF results link to the local copies. EPUB copies remain available in the same folders.</p>`;
    searchResults.scrollIntoView({behavior: 'smooth', block: 'start'});
    document.querySelector('#military-search-form').addEventListener('submit', async event => {
      event.preventDefault();
      const query = document.querySelector('#military-query').value.trim();
      const target = document.querySelector('#military-results');
      target.innerHTML = '<h3>Searching military manuals…</h3>';
      try {
        const result = await search(query, {
          category: 'military',
          collection: document.querySelector('#military-collection').value,
          branch: document.querySelector('#military-branch').value
        });
        renderResults(target, result, query, 'Military Field Manuals');
      } catch {
        target.innerHTML = '<p>Search is unavailable while the local index initializes. Try again in a moment.</p>';
      }
    });
    return;
  }

  const local = category.items.map(item => {
    const href = item.ext === '.zim' ? 'http://127.0.0.1:8081' : item.ext === '.pmtiles' ? '/map.html' : contentHref(item.path);
    const label = item.ext === '.pmtiles' ? 'OPEN INTERACTIVE MAP ↗' : `${esc(item.ext.slice(1).toUpperCase())} · ${fmt(item.size)}`;
    return `<div class="result"><a href="${href}">${esc(item.name)}</a><p>${label}</p></div>`;
  }).join('');
  searchResults.innerHTML = header + (local || '<p>This category is ready for content. Copy trusted reference files into its matching folder inside <code>content/</code>, then restart the library. New files are added to search automatically.</p>');
  searchResults.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function updateIndexLabel(index) {
  const label = document.querySelector('#index-status');
  if (!label || !index) return;
  if (index.state === 'ready') label.textContent = `Search index ready · ${Number(index.indexed || 0).toLocaleString()} documents`;
  else if (index.state === 'indexing' || index.state === 'scanning') {
    const done = Number(index.indexed || 0).toLocaleString();
    const total = Number(index.total || 0).toLocaleString();
    label.textContent = index.state === 'scanning' ? 'Checking for new or changed files…' : `Updating search index · ${done} of ${total} documents`;
  } else if (index.state === 'error') label.textContent = 'Search index update needs attention';
  else label.textContent = 'Search index starting…';
}

async function refreshIndexStatus() {
  try {
    const index = await (await fetch('/api/index-status')).json();
    updateIndexLabel(index);
    return index;
  } catch { return null; }
}

async function load() {
  try {
    const [categoryResponse, statusResponse] = await Promise.all([fetch('/api/categories'), fetch('/api/status')]);
    categories = await categoryResponse.json();
    const status = await statusResponse.json();
    nav.innerHTML = categories.map(category => `<a href="#cat-${category.slug}" data-open="${category.slug}"><span>${category.icon}</span>${esc(category.title)}</a>`).join('');
    cards.innerHTML = categories.map(category => {
      const count = category.slug === 'military' ? `${Number(category.item_count || 0).toLocaleString()} LOCAL PDFS` : category.items.length ? `${category.items.length} LOCAL FILE${category.items.length === 1 ? '' : 'S'}` : 'READY FOR CONTENT';
      return `<a class="card" id="cat-${category.slug}" href="#cat-${category.slug}" data-open="${category.slug}"><div class="card-top"><span class="card-icon">${category.icon}</span><span class="card-arrow">↗</span></div><h3>${esc(category.title)}</h3><p>${esc(category.description)}</p><span class="card-count">${count}</span></a>`;
    }).join('');
    document.querySelectorAll('[data-open]').forEach(link => link.addEventListener('click', event => {
      event.preventDefault();
      showCategory(link.dataset.open);
    }));
    document.querySelector('#item-count').textContent = `${categories.length} CATEGORIES · ${status.files} LOCAL FILES`;
    document.querySelector('#capacity').textContent = fmt(status.total);
    document.querySelector('#free').textContent = fmt(status.free);
    document.querySelector('#files').textContent = status.files;
    document.querySelector('#drive-label').textContent = status.volume.split('/').pop() || 'External volume';
    document.querySelector('#kiwix').innerHTML = status.kiwix ? '<a href="http://127.0.0.1:8081">AVAILABLE ↗</a>' : 'NOT CONFIGURED';
    document.querySelector('#kiwix-sub').textContent = status.kiwix ? 'Open Kiwix at port 8081' : 'Install Kiwix Server to serve ZIM archives';
    updateIndexLabel(status.index);
  } catch {
    document.querySelector('#item-count').textContent = 'SERVER UNAVAILABLE';
  }
}

document.querySelector('#search-form').addEventListener('submit', async event => {
  event.preventDefault();
  const query = document.querySelector('#query').value.trim();
  if (query.length < 2) return;
  searchResults.hidden = false;
  searchResults.innerHTML = '<h3>Searching local references…</h3>';
  try {
    const includeMilitary = document.querySelector('#include-military').checked;
    const result = await search(query, {include_military: includeMilitary ? '1' : '0'});
    renderResults(searchResults, result, query, includeMilitary ? 'Military manuals included' : 'Military manuals excluded');
  } catch {
    searchResults.innerHTML = '<p>Search is temporarily unavailable while the local index initializes. Try again in a moment.</p>';
  }
});

document.querySelector('#menu').addEventListener('click', () => rail.classList.toggle('open'));
document.querySelector('#close-menu').addEventListener('click', closeNav);
document.querySelector('.main').addEventListener('click', event => {
  if (rail.classList.contains('open') && !event.target.closest('#menu')) closeNav();
});
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeNav(); });
nav.addEventListener('click', event => { if (event.target.closest('a')) closeNav(); });

load();
refreshIndexStatus().then(index => {
  if (index && index.state !== 'ready') {
    const timer = setInterval(async () => {
      const next = await refreshIndexStatus();
      if (next && (next.state === 'ready' || next.state === 'error')) clearInterval(timer);
    }, 3000);
  }
});
