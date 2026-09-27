"use strict";

// 던전 크롤러 웹 클라이언트. 모든 요청은 /api/* → (nginx) → Gateway 로만 보낸다.

const $ = (id) => document.getElementById(id);

const QUEST_TYPE_LABEL = {
  kill_monster: "처치",
  collect_item: "수집",
  win_dungeon: "던전 승리",
  reach_level: "레벨 도달",
};
const SKILL_MP_COST = 10;
const SYNC_TIMEOUT_MS = 8000;
const NOTIFICATION_POLL_MS = 8000;

// ---------- 로컬 저장 (편의 기능이라 실패해도 동작에는 지장 없음) ----------
const store = {
  get(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 무시 */ }
  },
  remove(key) {
    try { localStorage.removeItem(key); } catch { /* 무시 */ }
  },
};

const state = {
  token: store.get("token", null),
  username: store.get("username", null),
  characterId: store.get("characterId", null),
  character: null,
  inventory: [],
  dungeons: [],
  quests: [],
  progress: [],
  notifications: [],
  combat: null,
  // 인벤토리 API는 item_id만 주므로 전투 보상에서 본 아이템 이름을 기억해 둔다
  itemNames: store.get("itemNames", {}),
  questsLoaded: false,
  authMode: "login",
  pollTimer: null,
};

// ---------- API ----------
class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function api(method, path, body) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "서버에 연결할 수 없습니다.");
  }
  const requestId = response.headers.get("X-Request-ID");
  if (requestId) $("last-request-id").textContent = requestId;

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = data?.error ?? { code: `HTTP_${response.status}`, message: response.statusText };
    if (response.status === 401 && state.token && !path.startsWith("/auth/")) {
      logout("로그인이 만료됐습니다. 다시 로그인하세요.");
    }
    throw new ApiError(response.status, error.code, error.message);
  }
  return data;
}

// ---------- 공통 UI ----------
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false && value != null) node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child != null) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function showView(name) {
  for (const view of ["auth", "characters", "game"]) $(`view-${view}`).hidden = view !== name;
  $("topbar-user").hidden = name === "auth";
  $("btn-switch-character").hidden = name !== "game";
  $("topbar-username").textContent = state.username ?? "";
  if (name === "game") startPolling();
  else stopPolling();
}

let toastTimer = null;
function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, 3000);
}

function setBar(barId, value, max) {
  $(barId).style.width = `${max > 0 ? Math.min(100, (value / max) * 100) : 0}%`;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const totalExp = (c) => (c.level * (c.level - 1) / 2) * 100 + c.exp;
const itemName = (id) => state.itemNames[id] ?? `아이템 #${id}`;

// ---------- 인증 ----------
function setAuthMode(mode) {
  state.authMode = mode;
  document.querySelectorAll("[data-auth-tab]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.authTab === mode);
  });
  $("btn-auth-submit").textContent = mode === "login" ? "로그인" : "회원가입 후 로그인";
  $("auth-error").textContent = "";
}

async function submitAuth(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const credentials = { username: form.get("username").trim(), password: form.get("password") };
  $("auth-error").textContent = "";
  try {
    if (state.authMode === "register") await api("POST", "/auth/register", credentials);
    const { access_token } = await api("POST", "/auth/login", credentials);
    state.token = access_token;
    state.username = credentials.username;
    store.set("token", state.token);
    store.set("username", state.username);
    event.target.reset();
    await showCharacters();
  } catch (error) {
    $("auth-error").textContent = error.message;
  }
}

function logout(message) {
  state.token = state.username = state.characterId = null;
  state.combat = null;
  ["token", "username", "characterId"].forEach((key) => store.remove(key));
  showView("auth");
  if (message) $("auth-error").textContent = message;
}

// ---------- 캐릭터 선택 ----------
async function showCharacters() {
  showView("characters");
  $("character-error").textContent = "";
  const list = $("character-list");
  list.replaceChildren();
  try {
    const characters = await api("GET", "/characters");
    if (characters.length === 0) list.append(el("li", { class: "empty" }, "캐릭터가 없습니다. 새로 만들어 보세요."));
    for (const c of characters) {
      list.append(el("li", {},
        el("button", { onclick: () => selectCharacter(c.id) },
          el("span", {}, el("strong", {}, c.name)),
          el("span", { class: "muted" }, `Lv ${c.level} · HP ${c.hp}/${c.max_hp}`),
        ),
      ));
    }
  } catch (error) {
    $("character-error").textContent = error.message;
  }
}

async function createCharacter(event) {
  event.preventDefault();
  const name = new FormData(event.target).get("name").trim();
  try {
    const character = await api("POST", "/characters", { name });
    event.target.reset();
    await selectCharacter(character.id);
  } catch (error) {
    $("character-error").textContent = error.message;
  }
}

async function selectCharacter(id) {
  state.characterId = id;
  state.progress = [];
  state.questsLoaded = false;
  store.set("characterId", id);
  await enterGame();
}

// ---------- 게임 화면 ----------
async function enterGame() {
  showView("game");
  resetCombatView();
  try {
    await Promise.all([refreshCharacter(), loadDungeons(), refreshQuests(), refreshNotifications()]);
  } catch (error) {
    if (error.status === 404) return showCharacters();
    toast(error.message);
  }
}

async function refreshCharacter() {
  const [character, inventory] = await Promise.all([
    api("GET", `/characters/${state.characterId}`),
    api("GET", `/characters/${state.characterId}/inventory`),
  ]);
  state.character = character;
  state.inventory = inventory;
  renderCharacter();
  renderDungeons();
  renderQuests();
  return character;
}

function renderCharacter(override) {
  const c = { ...state.character, ...override };
  const needed = c.level * 100;
  $("char-name").textContent = c.name;
  $("char-level").textContent = `Lv ${c.level}`;
  $("char-exp-text").textContent = `EXP ${c.exp} / ${needed}`;
  setBar("char-exp-bar", c.exp, needed);
  $("char-hp-text").textContent = `${c.hp} / ${c.max_hp}`;
  setBar("char-hp-bar", c.hp, c.max_hp);
  $("char-mp-text").textContent = `${c.mp} / ${c.max_mp}`;
  setBar("char-mp-bar", c.mp, c.max_mp);
  $("char-atk").textContent = c.atk;
  $("char-def").textContent = c.defense;
  const inCombat = Boolean(state.combat && !state.combat.finished);
  $("btn-rest").disabled = inCombat || (c.hp === c.max_hp && c.mp === c.max_mp);

  const inventory = $("inventory");
  inventory.replaceChildren();
  if (state.inventory.length === 0) inventory.append(el("li", { class: "empty" }, "비어 있음"));
  for (const item of state.inventory) {
    inventory.append(el("li", {}, el("span", {}, itemName(item.item_id)), el("span", { class: "muted" }, `× ${item.quantity}`)));
  }
}

async function rest() {
  try {
    state.character = await api("POST", `/characters/${state.characterId}/rest`);
    renderCharacter();
    toast("모닥불 곁에서 쉬었다. HP/MP가 모두 회복됐다.");
  } catch (error) {
    toast(error.message);
  }
}

// ---------- 던전 / 전투 ----------
async function loadDungeons() {
  state.dungeons = await api("GET", "/dungeons");
  renderDungeons();
}

function renderDungeons() {
  const list = $("dungeon-list");
  list.replaceChildren();
  const level = state.character?.level ?? 1;
  for (const d of state.dungeons) {
    const locked = level < d.min_level;
    list.append(el("li", {},
      el("div", {},
        el("div", { class: "name" }, d.name),
        el("div", { class: "desc" }, `${d.description} · 권장 Lv ${d.min_level}+`),
      ),
      el("button", { class: locked ? "" : "primary", disabled: locked || Boolean(state.combat), onclick: () => enterDungeon(d) },
        locked ? `🔒 Lv ${d.min_level}` : "입장"),
    ));
  }
}

function combatKey() {
  return `combat:${state.characterId}`;
}

async function enterDungeon(dungeon) {
  $("dungeon-error").textContent = "";
  try {
    const entered = await api("POST", `/dungeons/${dungeon.id}/enter`, { character_id: state.characterId });
    store.set(combatKey(), dungeon.id);
    startCombat(dungeon, entered.character, entered.monster);
    logLine(entered.message, "system");
  } catch (error) {
    if (error.code === "COMBAT_IN_PROGRESS") {
      // 새로고침 등으로 화면만 초기화된 경우: 서버에 남은 전투를 이어간다
      const dungeonId = store.get(combatKey(), dungeon.id);
      const resumed = state.dungeons.find((d) => d.id === dungeonId) ?? dungeon;
      startCombat(resumed, state.character, null);
      logLine("진행 중이던 전투로 돌아왔다. 행동을 선택하면 전투가 이어진다.", "system");
      return;
    }
    $("dungeon-error").textContent = error.message;
  }
}

function startCombat(dungeon, character, monster) {
  state.combat = { dungeon, character, monster, before: { ...state.character }, finished: false };
  $("dungeon-select").hidden = true;
  $("combat").hidden = false;
  $("combat-result").hidden = true;
  $("combat-actions").hidden = false;
  $("combat-title").textContent = dungeon.name;
  $("combat-turn").textContent = "턴 0";
  $("combat-log").replaceChildren();
  renderCombat();
}

function renderCombat() {
  const { character, monster } = state.combat;
  if (monster) {
    $("monster-name").textContent = `👹 ${monster.name}`;
    $("monster-hp-text").textContent = `${monster.hp} / ${monster.max_hp}`;
    setBar("monster-hp-bar", monster.hp, monster.max_hp);
  } else {
    $("monster-name").textContent = "👹 ???";
    $("monster-hp-text").textContent = "? / ?";
    setBar("monster-hp-bar", 1, 1);
  }
  // 전투 중 HP/MP는 dungeon-service 세션 값. 전투가 끝나면 이벤트로 character-service에 반영된다
  renderCharacter({ hp: character.hp, mp: character.mp });
  $("btn-skill").disabled = state.combat.finished || character.mp < SKILL_MP_COST;
  renderDungeons();
}

function logLine(text, kind = "") {
  const log = $("combat-log");
  log.append(el("li", { class: kind }, text));
  log.scrollTop = log.scrollHeight;
}

function classifyLine(line, monsterName) {
  if (line.includes("쓰러뜨렸다") || line.includes("도망에 성공")) return "good";
  if (line.includes("쓰러졌다") || (monsterName && line.startsWith(`${monsterName}의 공격`))) return "bad";
  return "";
}

async function act(action) {
  if (!state.combat || state.combat.finished) return;
  const buttons = document.querySelectorAll("#combat-actions button");
  buttons.forEach((b) => { b.disabled = true; });
  try {
    const turn = await api("POST", `/dungeons/${state.combat.dungeon.id}/combat`, {
      character_id: state.characterId,
      action,
    });
    state.combat.character = { ...state.combat.character, ...turn.character };
    state.combat.monster = turn.monster;
    $("combat-turn").textContent = `턴 ${turn.turn}`;
    logLine(`— 턴 ${turn.turn} —`, "turn");
    for (const line of turn.log) logLine(line, classifyLine(line, turn.monster.name));
    if (turn.status !== "ongoing") finishCombat(turn);
  } catch (error) {
    if (error.code === "NO_ACTIVE_COMBAT") {
      logLine("전투 세션이 만료됐다.", "system");
      store.remove(combatKey());
      state.combat = null;
      resetCombatView();
      return;
    }
    toast(error.message);
  } finally {
    buttons.forEach((b) => { b.disabled = false; });
    if (state.combat) renderCombat();
  }
}

function finishCombat(turn) {
  state.combat.finished = true;
  store.remove(combatKey());
  const rewards = turn.rewards ?? { exp_gained: 0, items: [] };
  for (const item of rewards.items) state.itemNames[item.id] = item.name;
  store.set("itemNames", state.itemNames);

  const text = {
    win: `🏆 승리! 경험치 +${rewards.exp_gained}` + (rewards.items.length ? ` · 획득: ${rewards.items.map((i) => i.name).join(", ")}` : ""),
    lose: "💀 패배... 마을에서 HP 1로 깨어난다.",
    flee: "🏃 무사히 도망쳤다.",
  }[turn.status];
  logLine(text, turn.status === "lose" ? "bad" : "system");
  $("combat-result-text").textContent = text;
  $("combat-actions").hidden = true;
  $("combat-result").hidden = false;
  syncAfterCombat(turn, rewards);
}

function resetCombatView() {
  $("combat").hidden = true;
  $("dungeon-select").hidden = false;
  $("dungeon-error").textContent = "";
  if (state.character) renderCharacter();
  renderDungeons();
}

function leaveCombat() {
  state.combat = null;
  resetCombatView();
}

// 전투 결과는 HTTP가 아니라 이벤트(dungeon.combat_result)로 character/quest/notification 서비스에 전파된다.
// 반영될 때까지 조회를 반복하면서 "최종적 일관성"을 화면에 보여준다.
async function syncAfterCombat(turn, rewards) {
  const before = state.combat.before;
  const status = $("sync-status");
  status.textContent = "⏳ 전투 결과가 이벤트로 반영되는 중…";
  const started = performance.now();
  const reflected = (c) => {
    if (turn.status === "win") return totalExp(c) >= totalExp(before) + rewards.exp_gained;
    if (turn.status === "lose") return c.hp === 1 || c.level > before.level;
    return c.hp === Math.min(turn.character.hp, c.max_hp);
  };
  try {
    while (performance.now() - started < SYNC_TIMEOUT_MS) {
      const character = await refreshCharacter();
      if (reflected(character)) {
        status.textContent = `✔ 반영 완료 (${((performance.now() - started) / 1000).toFixed(1)}초)`;
        if (character.level > before.level) toast(`🎉 레벨 ${character.level} 달성!`);
        break;
      }
      await sleep(400);
    }
    if (!status.textContent.startsWith("✔")) status.textContent = "⚠ 아직 반영되지 않았습니다. 잠시 후 다시 확인됩니다.";
    // 퀘스트 완료 → 보상 → 레벨업 → 알림 으로 이어지는 연쇄 이벤트를 몇 번 더 따라간다
    for (const delay of [0, 1000, 2000]) {
      await sleep(delay);
      await Promise.all([refreshCharacter(), refreshQuests(), refreshNotifications()]);
    }
  } catch (error) {
    status.textContent = `⚠ ${error.message}`;
  }
  setTimeout(() => { if (!state.combat) status.textContent = ""; }, 5000);
}

// ---------- 퀘스트 ----------
async function refreshQuests() {
  const [quests, progress] = await Promise.all([
    api("GET", "/quests"),
    api("GET", `/quests/progress?character_id=${state.characterId}`),
  ]);
  // 이벤트로 새로 완료된 퀘스트가 있으면 알려준다 (첫 로딩 때는 제외)
  if (state.questsLoaded) {
    const done = new Set(state.progress.filter((p) => p.status === "completed").map((p) => p.quest_id));
    for (const p of progress) {
      if (p.status === "completed" && !done.has(p.quest_id)) toast(`📜 퀘스트 완료: ${p.quest_name} (+${p.reward_exp} exp)`);
    }
  }
  state.quests = quests;
  state.progress = progress;
  state.questsLoaded = true;
  renderQuests();
}

function renderQuests() {
  const list = $("quest-list");
  list.replaceChildren();
  const byQuest = new Map(state.progress.map((p) => [p.quest_id, p]));
  const level = state.character?.level ?? 1;
  for (const q of state.quests) {
    const p = byQuest.get(q.id);
    const locked = level < q.min_level;
    let action;
    if (!p) {
      action = el("button", { class: "small primary", disabled: locked, onclick: () => acceptQuest(q) }, locked ? `Lv ${q.min_level}+` : "수락");
    } else if (p.status === "completed") {
      action = el("span", { class: "badge" }, "✔ 완료");
    } else {
      action = el("span", { class: "badge" }, "진행 중");
    }
    const children = [
      el("div", { class: "quest-top" }, el("span", { class: "quest-name" }, q.name), action),
      el("div", { class: "quest-meta" }, `[${QUEST_TYPE_LABEL[q.type]}] ${q.description} · 보상 ${q.reward_exp} exp`),
    ];
    if (p) {
      const bar = el("div", { class: "bar" }, el("div", { style: `width:${(p.progress / p.target_count) * 100}%` }));
      children.push(bar, el("div", { class: "quest-progress-text" }, `${p.progress} / ${p.target_count}`));
    }
    list.append(el("li", { class: p?.status === "completed" ? "completed" : "" }, children));
  }
}

async function acceptQuest(quest) {
  try {
    const progress = await api("POST", `/quests/${quest.id}/accept`, { character_id: state.characterId });
    toast(progress.status === "completed" ? `📜 조건을 이미 만족해 바로 완료! (+${quest.reward_exp} exp)` : `📜 퀘스트 수락: ${quest.name}`);
    await refreshQuests();
    if (progress.status === "completed") {
      await sleep(1000);
      await Promise.all([refreshCharacter(), refreshNotifications()]);
    }
  } catch (error) {
    toast(error.message);
  }
}

// ---------- 알림 ----------
async function refreshNotifications() {
  state.notifications = await api("GET", `/notifications?character_id=${state.characterId}`);
  renderNotifications();
}

function renderNotifications() {
  const list = $("notification-list");
  list.replaceChildren();
  const unread = state.notifications.filter((n) => !n.read_at);
  $("unread-count").hidden = unread.length === 0;
  $("unread-count").textContent = unread.length;
  $("btn-read-all").disabled = unread.length === 0;
  if (state.notifications.length === 0) list.append(el("li", { class: "empty read" }, "아직 알림이 없습니다."));
  for (const n of state.notifications) {
    const icon = n.type === "level_up" ? "🎉" : "📜";
    list.append(el("li", { class: n.read_at ? "read" : "", title: n.read_at ? "" : "클릭하면 읽음 처리", onclick: () => !n.read_at && markRead(n.id) },
      `${icon} ${n.message}`,
      el("time", {}, new Date(n.created_at).toLocaleString("ko-KR")),
    ));
  }
}

async function markRead(id) {
  try {
    await api("POST", `/notifications/${id}/read`);
    await refreshNotifications();
  } catch (error) {
    toast(error.message);
  }
}

async function markAllRead() {
  for (const n of state.notifications.filter((x) => !x.read_at)) {
    await api("POST", `/notifications/${n.id}/read`).catch(() => {});
  }
  await refreshNotifications();
}

function startPolling() {
  stopPolling();
  state.pollTimer = setInterval(() => {
    if (state.characterId) refreshNotifications().catch(() => {});
  }, NOTIFICATION_POLL_MS);
}

function stopPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = null;
}

function showSideTab(name) {
  document.querySelectorAll("[data-side-tab]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.sideTab === name);
  });
  $("side-quests").hidden = name !== "quests";
  $("side-notifications").hidden = name !== "notifications";
}

// ---------- 이벤트 연결 / 시작 ----------
document.querySelectorAll("[data-auth-tab]").forEach((tab) => tab.addEventListener("click", () => setAuthMode(tab.dataset.authTab)));
document.querySelectorAll("[data-side-tab]").forEach((tab) => tab.addEventListener("click", () => showSideTab(tab.dataset.sideTab)));
document.querySelectorAll("#combat-actions button").forEach((b) => b.addEventListener("click", () => act(b.dataset.action)));
$("form-auth").addEventListener("submit", submitAuth);
$("form-character").addEventListener("submit", createCharacter);
$("btn-logout").addEventListener("click", () => logout());
$("btn-switch-character").addEventListener("click", () => { state.combat = null; showCharacters(); });
$("btn-rest").addEventListener("click", rest);
$("btn-combat-done").addEventListener("click", leaveCombat);
$("btn-read-all").addEventListener("click", markAllRead);

if (!state.token) showView("auth");
else if (!state.characterId) showCharacters();
else enterGame();
