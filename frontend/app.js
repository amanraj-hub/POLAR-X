const state = {
  token: localStorage.getItem("px_token"),
  user: JSON.parse(localStorage.getItem("px_user") || "null"),
  page: "dashboard",
  assets: [],
  expeditions: [],
  pending: JSON.parse(localStorage.getItem("px_pending") || "[]"),
  gps: null,
  users: []
};

const $ = id => document.getElementById(id);
const api = async (path, options={}) => {
  const isLogin = path === "/api/auth/login";
  const headers = {"Content-Type":"application/json", ...(options.headers||{})};
  // Never attach an old/stale JWT to the login request.
  if(state.token && !isLogin) headers.Authorization = `Bearer ${state.token}`;
  const method=(options.method||"GET").toUpperCase();
  let res;
  try {
    res = await fetch(path, {...options, headers});
  } catch(err) {
    if(["POST","PUT","DELETE"].includes(method) && !path.includes("/auth/")) {
      state.pending.push({path, options:{...options, headers:{"Content-Type":"application/json", ...(state.token?{Authorization:`Bearer ${state.token}`}:{})}}, queuedAt:new Date().toISOString()});
      localStorage.setItem("px_pending", JSON.stringify(state.pending));
      updateNetwork(false);
      toast("Network unavailable: change queued for sync.");
      return {queued:true};
    }
    throw new Error("Cannot connect to POLAR-X server. Make sure python app.py is running.");
  }
  const data = await res.json().catch(()=>({}));
  if(res.status === 401 && state.token && !isLogin) {
    // The browser may still hold a JWT from an older/restarted server or database.
    // Clear it immediately so protected API calls never leave the app stuck on
    // "Authentication required".
    state.token = null;
    state.user = null;
    localStorage.removeItem("px_token");
    localStorage.removeItem("px_user");
    showLogin();
    throw new Error("Your session expired or is no longer valid. Please sign in again.");
  }
  if(!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
};

function toast(msg){const el=document.createElement("div");el.className="toast";el.textContent=msg;$("toast").appendChild(el);setTimeout(()=>el.remove(),3000)}
function updateNetwork(ok){$("networkStatus").className=`status-pill ${ok?"online":"offline"}`;$("networkStatus").textContent=ok?"● Online":"● Offline"}
async function syncQueue(){
  if(!navigator.onLine || !state.pending.length) return;
  const queue=[...state.pending]; state.pending=[];
  for(const item of queue){try{await fetch(item.path,item.options)}catch{state.pending.push(item)}}
  localStorage.setItem("px_pending",JSON.stringify(state.pending));
  if(!state.pending.length){updateNetwork(true);toast("Offline changes synchronized.");}
}
window.addEventListener("online",()=>{updateNetwork(true);syncQueue()});
window.addEventListener("offline",()=>updateNetwork(false));



async function runSelfTest(){
  if(String(state.user.role||"").toUpperCase()!=="ADMIN"){toast("Self-Test is available only to an ADMIN account.");return}
  const btn=$("selfTestBtn");
  btn.disabled=true; btn.textContent="Running Self-Test…";
  try{
    const r=await api("/api/self-test",{method:"POST",body:JSON.stringify({})});
    const passed=r.checks.filter(x=>x.passed).length;
    openModal("POLAR-X Self-Test Results",`
      <div class="forecast-note"><b>${r.ok?"✓ Self-test passed":"⚠ Self-test completed with failures"}</b><br>${r.message}</div>
      <div class="credential-card">
        <h3>Demo login created</h3>
        <div class="credential"><span>Email</span><b>${r.test_user.email}</b></div>
        <div class="credential"><span>Role</span><b>${r.test_user.role}</b></div>
        <div class="credential"><span>Temporary password</span><b>${r.test_user.temporary_password}</b></div>
        <div class="credential"><span>Expedition</span><b>${r.expedition.name}</b></div>
        <div class="credential"><span>Assets</span><b>${r.assets_created}</b></div>
        <div class="credential"><span>Telemetry readings</span><b>${r.telemetry_created}</b></div>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Check</th><th>Result</th><th>Details</th></tr></thead><tbody>
      ${r.checks.map(x=>`<tr><td>${x.name}</td><td><span class="badge ${x.passed?"available":"lost"}">${x.passed?"PASS":"FAIL"}</span></td><td>${x.details}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="muted">${passed}/${r.checks.length} checks passed. The generated demo data is intentionally retained so you can inspect it in Expeditions, Assets, Telemetry, Users and Audit Log.</p>
    `);
    await loadDashboard();
    await loadAssets();
    await loadExpeditions();
  }catch(err){toast(err.message)}
  finally{btn.disabled=false;btn.textContent="Run Self-Test / Demo"}
}

async function openForecast(){
  const rows=await api("/api/analytics/forecast");
  openModal("AI-Assisted Stock Forecast",`<div class="forecast-note">Transparent demo model: estimates use current quantity, minimum stock and operational status. Replace this endpoint with a trained model when historical consumption data is available.</div>
  <div class="table-wrap"><table><thead><tr><th>Asset</th><th>Stock</th><th>Days left</th><th>Restock</th><th>Risk</th></tr></thead><tbody>
  ${rows.map(x=>`<tr><td>${x.asset}</td><td>${x.quantity}</td><td>${x.estimated_days_remaining}</td><td>${x.recommended_restock}</td><td><span class="badge ${x.risk.toLowerCase()}">${x.risk}</span></td></tr>`).join("")}</tbody></table></div>`);
}
async function loadTelemetry(){
  const rows=await api("/api/telemetry");
  $("telemetryRows").innerHTML=rows.length?rows.slice(0,20).map(r=>`<div class="alert"><i class="dot"></i><div><b>${r.sensor_type}: ${r.value} ${r.unit}</b><div class="muted">${new Date(r.recorded_at).toLocaleString()}</div></div></div>`).join(""):`<div class="muted">No telemetry yet. Simulate the first reading.</div>`;
  if(rows[0]) $("telemetryValue").textContent=`${rows[0].value} ${rows[0].unit}`;
  $("telemetryExpedition").innerHTML=state.expeditions.map(e=>`<option value="${e.id}">${e.name}</option>`).join("");
}
async function simulateTelemetry(){
  const r=await api("/api/telemetry/simulate",{method:"POST",body:JSON.stringify({expedition_id:$("telemetryExpedition").value,sensor_type:$("sensorType").value})});
  if(!r.queued){await loadTelemetry();toast("Telemetry reading received.");}
}
async function downloadReport(kind){
  if(!state.token){ toast("Please sign in again before downloading a report."); showLogin(); return; }
  try{
    const res=await fetch(`/api/reports/${kind}.csv`,{
      method:"GET",
      headers:{Authorization:`Bearer ${state.token}`}
    });
    if(res.status===401){
      state.token=null; state.user=null;
      localStorage.removeItem("px_token"); localStorage.removeItem("px_user");
      showLogin();
      throw new Error("Your session expired. Please sign in again.");
    }
    if(!res.ok){
      const data=await res.json().catch(()=>({}));
      throw new Error(data.error || `Report download failed (${res.status})`);
    }
    const blob=await res.blob();
    const url=URL.createObjectURL(blob);
    const link=document.createElement("a");
    link.href=url;
    link.download=`polar-x-${kind}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    toast("CSV downloaded successfully.");
  }catch(err){toast(err.message)}
}

async function boot(){
  if(!state.token){showLogin();return}
  try{
    state.user=await api("/api/me");
    showApp();
    await loadAll();
  }catch(err){
    // api() already clears invalid sessions. Keep this as a safe fallback for
    // network/startup failures so a broken old session never traps the user.
    if(state.token) logout(false);
  }
}
function showLogin(){
  $("loginView").classList.remove("hidden");
  $("appView").classList.add("hidden");
  $("email").focus();
}
function showApp(){
  $("loginView").classList.add("hidden");
  $("appView").classList.remove("hidden");
  $("userBadge").innerHTML=`<div class="user"><b>${state.user.name}</b><small>${state.user.role}</small></div>`;
  applyPermissions();
  if(state.user.must_change_password) setTimeout(forcePasswordChange,150);
}
function logout(notify=true){
  state.token=null;
  state.user=null;
  localStorage.removeItem("px_token");
  localStorage.removeItem("px_user");
  // Do not keep protected requests around after the user signs out.
  state.pending=[];
  localStorage.removeItem("px_pending");
  showLogin();
  $("password").value="";
  if(notify) toast("Signed out successfully");
}
function applyPermissions(){
  const role=String(state.user.role||"").toUpperCase();
  const canManage=["ADMIN","MANAGER","EXPEDITIONER"].includes(role);
  $("selfTestBtn").style.display=role==="ADMIN"?"":"none";
  $("addAssetBtn").style.display=canManage?"":"none";
  $("addExpeditionBtn").style.display=["ADMIN","MANAGER"].includes(role)?"":"none";
  document.querySelector('[data-page="audit"]').style.display=["ADMIN","MANAGER"].includes(role)?"":"none";
  document.querySelector('[data-page="users"]').style.display=(String(state.user.role||"").toUpperCase()==="ADMIN")?"":"none";
  $("addUserBtn").style.display=(String(state.user.role||"").toUpperCase()==="ADMIN")?"":"none";
}

function navigate(page){
  state.page=page;
  document.querySelectorAll(".page").forEach(x=>x.classList.add("hidden"));
  $("page-"+page).classList.remove("hidden");
  document.querySelectorAll(".nav").forEach(x=>x.classList.toggle("active",x.dataset.page===page));
  const titles={dashboard:"Mission Dashboard",assets:"Asset Registry",expeditions:"Expedition Control",map:"Live Location",telemetry:"IoT Telemetry",reports:"Mission Reports",audit:"Audit Log",users:"User Management"};
  $("pageTitle").textContent=titles[page];
  if(page==="dashboard")loadDashboard(); if(page==="assets")loadAssets(); if(page==="expeditions")loadExpeditions(); if(page==="map")loadExpeditions(); if(page==="telemetry"){loadExpeditions();loadTelemetry();} if(page==="reports"){} if(page==="audit")loadAudit(); if(page==="users")loadUsers();
}
async function loadAll(){await loadDashboard();await loadAssets();await loadExpeditions();syncQueue()}

async function loadDashboard(){
  const d=await api("/api/dashboard"); updateNetwork(true);
  $("stats").innerHTML=[
    ["Total Assets",d.stats.total_assets],["Available",d.stats.available],["In Use",d.stats.in_use],
    ["Maintenance",d.stats.maintenance],["Lost",d.stats.lost],["Active Missions",d.stats.active_expeditions]
  ].map(x=>`<div class="stat"><small>${x[0]}</small><strong>${x[1]}</strong></div>`).join("");
  $("alerts").innerHTML=d.alerts.length?d.alerts.map(a=>`<div class="alert"><i class="dot ${a.severity.toLowerCase()}"></i><div><b>${a.type.replace("_"," ")}</b><div class="muted">${a.message}</div></div></div>`).join(""):`<div class="muted">No active alerts.</div>`;
  $("recentExpeditions").innerHTML=d.recent_expeditions.map(e=>`<div class="exp-row"><div><b>${e.name}</b><div class="muted">${e.region}</div></div><span class="badge ${e.status.toLowerCase()}">${e.status}</span></div>`).join("");
}

async function loadAssets(){
  const q=$("assetSearch").value, status=$("assetStatus").value, category=$("assetCategory").value;
  state.assets=await api(`/api/assets?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}&category=${encodeURIComponent(category)}`);
  const cats=[...new Set(state.assets.map(a=>a.category))].sort();
  const old=category; $("assetCategory").innerHTML='<option value="">All categories</option>'+cats.map(c=>`<option>${c}</option>`).join(""); $("assetCategory").value=old;
  $("assetRows").innerHTML=state.assets.map(a=>`<tr>
    <td><b>${a.asset_code}</b></td><td>${a.name}</td><td>${a.category}</td><td>${a.quantity} / min ${a.min_quantity}</td>
    <td><span class="badge ${a.status.toLowerCase()}">${a.status.replace("_"," ")}</span></td><td>${a.location}</td>
    <td><div class="actions"><button class="mini" onclick="editAsset(${a.id})">Edit</button>${["ADMIN","MANAGER"].includes(state.user.role)?`<button class="mini" onclick="removeAsset(${a.id})">Delete</button>`:""}</div></td>
  </tr>`).join("") || `<tr><td colspan="7" class="muted">No assets found.</td></tr>`;
}
function openModal(title, body){$("modalTitle").textContent=title;$("modalBody").innerHTML=body;$("modal").classList.remove("hidden")}
function closeModal(){$("modal").classList.add("hidden")}
function assetForm(a={}){
 return `<form id="assetForm"><div class="form-grid">
 <input name="asset_code" placeholder="Asset code" value="${a.asset_code||""}" required>
 <input name="name" placeholder="Asset name" value="${a.name||""}" required>
 <input name="category" placeholder="Category" value="${a.category||""}" required>
 <input name="quantity" type="number" min="0" placeholder="Quantity" value="${a.quantity??1}" required>
 <input name="min_quantity" type="number" min="0" placeholder="Minimum quantity" value="${a.min_quantity??1}" required>
 <select name="status">${["AVAILABLE","IN_USE","MAINTENANCE","LOST"].map(s=>`<option ${a.status===s?"selected":""}>${s}</option>`).join("")}</select>
 <input name="location" placeholder="Location" value="${a.location||"Base Camp"}">
 <input name="last_service" type="date" value="${a.last_service||""}">
 <textarea class="full" name="notes" placeholder="Notes">${a.notes||""}</textarea></div>
 <div class="modal-actions"><button type="button" class="ghost" onclick="closeModal()">Cancel</button><button class="primary">Save Asset</button></div></form>`;
}
function addAsset(){openModal("Add Asset",assetForm());$("assetForm").onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.currentTarget));d.quantity=+d.quantity;d.min_quantity=+d.min_quantity;const r=await api("/api/assets",{method:"POST",body:JSON.stringify(d)});if(!r.queued){closeModal();await loadAssets();await loadDashboard();toast("Asset added.")}}}
function editAsset(id){const a=state.assets.find(x=>x.id===id);openModal("Edit Asset",assetForm(a));$("assetForm").onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.currentTarget));d.quantity=+d.quantity;d.min_quantity=+d.min_quantity;const r=await api(`/api/assets/${id}`,{method:"PUT",body:JSON.stringify(d)});if(!r.queued){closeModal();await loadAssets();await loadDashboard();toast("Asset updated.")}}}
async function removeAsset(id){if(!confirm("Delete this asset?"))return;const r=await api(`/api/assets/${id}`,{method:"DELETE"});if(!r.queued){await loadAssets();await loadDashboard();toast("Asset deleted.")}}

async function loadExpeditions(){
 state.expeditions=await api("/api/expeditions");
 renderExpeditions();
 $("locationExpedition").innerHTML=state.expeditions.map(e=>`<option value="${e.id}">${e.name}</option>`).join("");
}
function renderExpeditions(){
 const q=(($("expeditionSearch")||{}).value||"").toLowerCase().trim();
 const status=(($("expeditionStatus")||{}).value||"");
 const canEdit=["ADMIN","MANAGER"].includes(String(state.user?.role||"").toUpperCase());
 const canStatus=["ADMIN","MANAGER","EXPEDITIONER"].includes(String(state.user?.role||"").toUpperCase());
 const rows=state.expeditions.filter(e=>(!q||[e.name,e.region,e.leader].some(v=>String(v||"").toLowerCase().includes(q)))&&(!status||e.status===status));
 $("expeditionCards").innerHTML=rows.map(e=>`<article class="exp-card"><span class="badge ${e.status.toLowerCase()}">${e.status}</span><h3>${e.name}</h3><p>📍 ${e.region}<br>👤 ${e.leader}<br>📅 ${e.start_date||"Not scheduled"} → ${e.end_date||"Open"}</p>${e.notes?`<p class="mission-notes">${e.notes}</p>`:""}<div class="exp-actions">${canEdit?`<button class="mini" onclick="editExpedition(${e.id})">Edit</button>`:""}${canStatus?`<button class="mini" onclick="changeExpedition(${e.id})">Status</button>`:""}<button class="mini" onclick="selectMap(${e.id})">Track GPS</button>${canEdit?`<button class="mini danger-btn" onclick="removeExpedition(${e.id})">Delete</button>`:""}</div></article>`).join("") || `<div class="panel muted">No expeditions match the current filters.</div>`;
}
function expeditionForm(e={},editing=false){
 return `<form id="expForm"><div class="form-grid"><input name="name" placeholder="Expedition name" value="${e.name||""}" required><input name="region" placeholder="Region / zone" value="${e.region||""}" required><input name="leader" placeholder="Expedition leader" value="${e.leader||""}" required><select name="status">${["PLANNED","ACTIVE","COMPLETED","CANCELLED"].map(s=>`<option ${e.status===s?"selected":""}>${s}</option>`).join("")}</select><input name="start_date" type="date" value="${e.start_date||""}"><input name="end_date" type="date" value="${e.end_date||""}"><textarea class="full" name="notes" placeholder="Mission notes">${e.notes||""}</textarea></div><div class="modal-actions"><button type="button" class="ghost" onclick="closeModal()">Cancel</button><button class="primary">${editing?"Save Changes":"Create Expedition"}</button></div></form>`;
}
function addExpedition(){openModal("New Expedition",expeditionForm());$("expForm").onsubmit=async e=>{e.preventDefault();try{const r=await api("/api/expeditions",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(e.currentTarget)))});if(!r.queued){closeModal();await loadExpeditions();await loadDashboard();toast("Expedition created successfully.")}}catch(err){toast(err.message)}}}
function editExpedition(id){const item=state.expeditions.find(x=>x.id===id);if(!item)return;openModal("Edit Expedition",expeditionForm(item,true));$("expForm").onsubmit=async ev=>{ev.preventDefault();try{const d=Object.fromEntries(new FormData(ev.currentTarget));const r=await api(`/api/expeditions/${id}`,{method:"PUT",body:JSON.stringify(d)});if(!r.queued){closeModal();await loadExpeditions();await loadDashboard();toast("Expedition updated successfully.")}}catch(err){toast(err.message)}}}
function changeExpedition(id){const item=state.expeditions.find(x=>x.id===id);openModal("Update Mission Status",`<select id="newExpStatus">${["PLANNED","ACTIVE","COMPLETED","CANCELLED"].map(s=>`<option ${item?.status===s?"selected":""}>${s}</option>`).join("")}</select><div class="modal-actions"><button type="button" class="ghost" onclick="closeModal()">Cancel</button><button class="primary" onclick="saveExpStatus(${id})">Save Status</button></div>`)}
async function saveExpStatus(id){const r=await api(`/api/expeditions/${id}`,{method:"PUT",body:JSON.stringify({status:$("newExpStatus").value})});if(!r.queued){closeModal();await loadExpeditions();await loadDashboard();toast("Mission status updated.")}}
async function removeExpedition(id){const item=state.expeditions.find(x=>x.id===id);if(!item||!confirm(`Delete expedition "${item.name}"? Its telemetry and asset assignment records will also be removed.`))return;try{const r=await api(`/api/expeditions/${id}`,{method:"DELETE"});if(!r.queued){await loadExpeditions();await loadDashboard();toast("Expedition deleted.")}}catch(err){toast(err.message)}}
function selectMap(id){navigate("map");$("locationExpedition").value=id}
function captureGPS(){
 if(!navigator.geolocation){toast("Geolocation is not supported.");return}
 navigator.geolocation.getCurrentPosition(p=>{state.gps={latitude:p.coords.latitude,longitude:p.coords.longitude};$("coords").innerHTML=`<b>GPS captured</b><br>Latitude: ${state.gps.latitude.toFixed(6)}<br>Longitude: ${state.gps.longitude.toFixed(6)}`;toast("GPS position captured.")},()=>toast("GPS permission denied or unavailable."));
}
async function saveLocation(){if(!state.gps){toast("Capture GPS first.");return}const id=$("locationExpedition").value;if(!id){toast("Select an expedition.");return}const r=await api(`/api/expeditions/${id}/location`,{method:"POST",body:JSON.stringify(state.gps)});if(!r.queued){loadExpeditions();toast("Location synchronized.")}}
function userForm(){
 return `<form id="userForm"><div class="form-grid">
 <input name="name" placeholder="Full name" required>
 <input name="email" type="email" placeholder="Email address" required>
 <select name="role"><option>MANAGER</option><option>EXPEDITIONER</option><option>VIEWER</option><option>ADMIN</option></select>
 <input name="password" type="password" minlength="8" placeholder="Password (leave blank to generate)">
 <div class="full muted">If password is blank, POLAR-X generates a temporary password. The new user must change it on first login.</div>
 </div><div class="modal-actions"><button type="button" class="ghost" onclick="closeModal()">Cancel</button><button class="primary">Create User</button></div></form>`;
}
function credentialsCard(result){
 return `<div class="credential-card"><h3>User created successfully</h3><p class="muted">Share these credentials securely with the new team member. The temporary password will not be shown again.</p><div class="credential"><span>Name</span><b>${result.user.name}</b></div><div class="credential"><span>Email</span><b>${result.user.email}</b></div><div class="credential"><span>Role</span><b>${result.user.role}</b></div><div class="credential"><span>Temporary password</span><b id="newTempPassword">${result.temporary_password}</b></div><div class="modal-actions"><button class="ghost" onclick="copyCredentials('${result.user.email}','${result.temporary_password}')">Copy credentials</button><button class="primary" onclick="closeModal()">Done</button></div></div>`;
}
async function copyCredentials(email,password){await navigator.clipboard.writeText(`POLAR-X login\nEmail: ${email}\nTemporary password: ${password}`);toast("Credentials copied.")}
function addUser(){openModal("Create User",userForm());$("userForm").onsubmit=async e=>{e.preventDefault();try{const d=Object.fromEntries(new FormData(e.currentTarget));const r=await api("/api/users",{method:"POST",body:JSON.stringify(d)});if(!r.queued){await loadUsers();openModal("User Credentials",credentialsCard(r));toast("User account created successfully.")}}catch(err){toast(err.message)}}}
async function loadUsers(){state.users=await api("/api/users");$("userRows").innerHTML=state.users.map(u=>`<tr><td><b>${u.name}</b></td><td>${u.email}</td><td><span class="badge ${u.role.toLowerCase()}">${u.role}</span></td><td>${u.must_change_password?'<span class="badge maintenance">PASSWORD CHANGE REQUIRED</span>':'<span class="badge available">ACTIVE</span>'}</td><td>${new Date(u.created_at).toLocaleDateString()}</td><td><button class="mini" onclick="resetUserPassword(${u.id})">Reset password</button></td></tr>`).join("") || `<tr><td colspan="6" class="muted">No users found.</td></tr>`}
async function resetUserPassword(id){if(!confirm("Generate a new temporary password for this user?"))return;const r=await api(`/api/users/${id}/reset-password`,{method:"POST"});if(!r.queued){await loadUsers();openModal("New User Credentials",credentialsCard(r));}}
function changeMyPassword(){openModal("Change Password",`<form id="changePasswordForm"><div class="form-grid"><input name="current_password" type="password" placeholder="Current password" required><input name="new_password" type="password" minlength="8" placeholder="New password (8+ characters)" required><input class="full" name="confirm_password" type="password" minlength="8" placeholder="Confirm new password" required></div><div class="modal-actions"><button type="button" class="ghost" onclick="closeModal()">Cancel</button><button class="primary">Save Password</button></div></form>`);$("changePasswordForm").onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.currentTarget));if(d.new_password!==d.confirm_password){toast("Passwords do not match.");return}try{const r=await api("/api/auth/change-password",{method:"POST",body:JSON.stringify({current_password:d.current_password,new_password:d.new_password})});state.user=r.user;localStorage.setItem("px_user",JSON.stringify(r.user));closeModal();toast("Password changed successfully.")}catch(err){toast(err.message)}}}
function forcePasswordChange(){openModal("Change Temporary Password",`<p class="muted">Your administrator created this account with a temporary password. Set a new password before continuing.</p><form id="changePasswordForm"><div class="form-grid"><input name="current_password" type="password" placeholder="Temporary/current password" required><input name="new_password" type="password" minlength="8" placeholder="New password (8+ characters)" required><input class="full" name="confirm_password" type="password" minlength="8" placeholder="Confirm new password" required></div><div class="modal-actions"><button class="primary">Change Password</button></div></form>`);$("changePasswordForm").onsubmit=async e=>{e.preventDefault();const d=Object.fromEntries(new FormData(e.currentTarget));if(d.new_password!==d.confirm_password){toast("Passwords do not match.");return}try{const r=await api("/api/auth/change-password",{method:"POST",body:JSON.stringify({current_password:d.current_password,new_password:d.new_password})});state.user=r.user;localStorage.setItem("px_user",JSON.stringify(r.user));closeModal();toast("Password changed successfully.")}catch(err){toast(err.message)}}}

async function loadAudit(){const rows=await api("/api/audit");$("auditRows").innerHTML=rows.map(x=>`<tr><td>${new Date(x.created_at).toLocaleString()}</td><td>${x.user_email}</td><td>${x.action}</td><td>${x.entity} #${x.entity_id||""}</td><td>${x.details||""}</td></tr>`).join("")||`<tr><td colspan="5">No audit entries.</td></tr>`}

$("loginForm").onsubmit=async e=>{e.preventDefault();
  // A login attempt starts a fresh authentication flow. Ignore any stale token.
  state.token=null; state.user=null; localStorage.removeItem("px_token"); localStorage.removeItem("px_user");
  try{const d=await api("/api/auth/login",{method:"POST",body:JSON.stringify({email:$("email").value,password:$("password").value})});state.token=d.token;state.user=d.user;localStorage.setItem("px_token",d.token);localStorage.setItem("px_user",JSON.stringify(d.user));showApp();await loadAll()}catch(err){toast(err.message)}};
$("logout").onclick=()=>logout();$("passwordBtn").onclick=changeMyPassword;$("closeModal").onclick=closeModal;$("modal").onclick=e=>{if(e.target.id==="modal")closeModal()};
document.querySelectorAll(".nav").forEach(b=>b.onclick=()=>navigate(b.dataset.page));
$("addUserBtn").onclick=addUser;
$("selfTestBtn").onclick=runSelfTest;
$("addAssetBtn").onclick=addAsset;$("addExpeditionBtn").onclick=addExpedition;$("refreshBtn").onclick=()=>navigate(state.page);
$("locateBtn").onclick=captureGPS;$("saveLocationBtn").onclick=saveLocation;$("simulateBtn").onclick=simulateTelemetry;
["assetSearch","assetStatus","assetCategory"].forEach(id=>$(id).addEventListener("input",loadAssets));
["expeditionSearch","expeditionStatus"].forEach(id=>$(id).addEventListener("input",renderExpeditions));
$("themeBtn").onclick=()=>{document.body.classList.toggle("light");toast("Theme toggled.")};
boot();
