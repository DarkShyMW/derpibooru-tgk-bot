const intervalEl = document.getElementById("interval");
const filterEl = document.getElementById("filterId");
const tagsEl = document.getElementById("tags");
const nextChip = document.getElementById("next-run-chip");
const toast = document.getElementById("toast");

document.getElementById("save").addEventListener("click", save);
document.getElementById("reload").addEventListener("click", load);
document.getElementById("post-now").addEventListener("click", postNow);

function showToast(msg){
  toast.classList.remove("hidden");
  toast.textContent = msg;
  setTimeout(()=>toast.classList.add("hidden"), 3000);
}
function formatDate(s){
  if(!s) return "—";
  return new Date(s).toLocaleString();
}
function tagsToText(tags){
  return (tags||[]).map(g => (g||[]).join(", ")).join("\n");
}

async function load(){
  const r = await fetch("/api/settings");
  if(r.status === 401){ location.href="/login"; return; }
  const j = await r.json();
  const s = j.settings;
  intervalEl.value = s.post_interval_minutes || 60;
  filterEl.value = (s.filter_id ?? "");
  tagsEl.value = tagsToText(s.tags);
  nextChip.textContent = "Следующий пост: " + formatDate(s.next_run_at);
}

async function save(){
  const payload = {
    post_interval_minutes: Number(intervalEl.value),
    filter_id: filterEl.value ? Number(filterEl.value) : null,
    tags_raw: tagsEl.value || ""
  };
  const r = await fetch("/api/settings", {
    method:"POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(payload)
  });
  if(r.status === 401){ location.href="/login"; return; }
  showToast("Сохранено ✅");
  load();
}

async function postNow(){
  const r = await fetch("/api/post-now", {method:"POST"});
  if(r.status === 401){ location.href="/login"; return; }
  showToast("Команда отправки принята ☕");
}

function connectWS(){
  const ws = new WebSocket((location.protocol==="https:"?"wss":"ws")+"://"+location.host+"/ws");
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if(msg.event === "status"){
      nextChip.textContent = "Следующий пост: " + formatDate(msg.data.next_run_at);
    }
    if(msg.event === "toast"){
      showToast(msg.data.message);
    }
  };
}

load();
connectWS();
