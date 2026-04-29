const grid = document.getElementById("grid");
const empty = document.getElementById("empty");
const statusChip = document.getElementById("status-chip");
const countChip = document.getElementById("count-chip");
const toast = document.getElementById("toast");

// Theme toggle functionality
(function initTheme() {
  const savedTheme = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);
  
  const toggleBtn = document.getElementById('theme-toggle');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme');
      const next = current === 'light' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      
      // Update theme-color meta tag
      const themeColor = next === 'light' ? '#f5f7fb' : '#0b1020';
      document.querySelector('meta[name="theme-color"]')?.setAttribute('content', themeColor);
    });
  }
})();

// PWA Service Worker registration
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js')
      .then((registration) => {
        console.log('SW registered:', registration.scope);
      })
      .catch((error) => {
        console.log('SW registration failed:', error);
      });
  });
}

function showToast(type, message){
  toast.classList.remove("hidden");
  toast.textContent = message;
  setTimeout(()=>toast.classList.add("hidden"), 3500);
}

function formatDate(s){
  if(!s) return "—";
  const d = new Date(s);
  return d.toLocaleString();
}

let lastImageCount = 0;

// Function to escape HTML to prevent XSS
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function render(images){
  countChip.textContent = `${images.length}`;
  if(!images.length){
    grid.innerHTML = "";
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";
  grid.innerHTML = images.map(img => {
    // Escape all user-provided data to prevent XSS
    const escapedTags = (img.tags||[]).slice(0,6).map(t => `<span class="badge">${escapeHtml(t)}</span>`).join("");
    const link = img.source || img.url;
    // Add cache-busting timestamp to image URLs for automatic refresh
    const imgUrl = img.url + (img.url.includes('?') ? '&' : '?') + 't=' + Date.now();
    return `
      <article class="item">
        <a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">
          <img src="${escapeHtml(imgUrl)}" loading="lazy" alt="Posted image"/>
        </a>
        <div class="meta">
          <div class="muted">${formatDate(img.posted_at)}</div>
          <div class="muted">${img.author ? "Автор: "+escapeHtml(img.author) : ""}</div>
          <div class="tags">${escapedTags}</div>
        </div>
      </article>
    `;
  }).join("");
  lastImageCount = images.length;
}

async function load(){
  const r = await fetch("/api/images?limit=120");
  const j = await r.json();
  render(j.images || []);
}

function connectWS(){
  const ws = new WebSocket((location.protocol==="https:"?"wss":"ws")+"://"+location.host+"/ws");

  ws.onopen = () => { statusChip.textContent = "Live: подключено ✅"; };
  ws.onclose = () => { statusChip.textContent = "Live: отключено (переподключаюсь…)"; setTimeout(connectWS, 1200); };

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if(msg.event === "new_image"){
      load();
    }
    if(msg.event === "status"){
      statusChip.textContent = msg.data.next_run_at ? `Следующий пост: ${formatDate(msg.data.next_run_at)}` : "Ожидание…";
    }
    if(msg.event === "toast"){
      showToast(msg.data.type, msg.data.message);
    }
  };
}

load();
connectWS();
setInterval(load, 60000);
