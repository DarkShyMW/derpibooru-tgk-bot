const grid = document.getElementById("grid");
const empty = document.getElementById("empty");
const statusChip = document.getElementById("status-chip");
const countChip = document.getElementById("count-chip");
const toast = document.getElementById("toast");

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

function render(images){
  countChip.textContent = `${images.length}`;
  if(!images.length){
    grid.innerHTML = "";
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";
  grid.innerHTML = images.map(img => {
    const tags = (img.tags||[]).slice(0,6).map(t => `<span class="badge">${t}</span>`).join("");
    const link = img.source || img.url;
    return `
      <article class="item">
        <a href="${link}" target="_blank" rel="noopener">
          <img src="${img.url}" loading="lazy"/>
        </a>
        <div class="meta">
          <div class="muted">${formatDate(img.posted_at)}</div>
          <div class="muted">${img.author ? "Автор: "+img.author : ""}</div>
          <div class="tags">${tags}</div>
        </div>
      </article>
    `;
  }).join("");
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
