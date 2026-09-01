const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();
tg?.setHeaderColor?.('#101827');
setTimeout(() => tg?.requestFullscreen?.(), 120);

const params = new URLSearchParams(location.search);
const wastelandToken = params.get('wasteland');
const token = params.get('battle') || wastelandToken;
const isWasteland = Boolean(wastelandToken);
const apiRoot = isWasteland ? '/api/wasteland' : '/api/battle';
const root = document.getElementById('app');
let payload = null;
let selectedSkill = null;
let flash = '';
let flashTimer = null;

const headers = () => ({'Content-Type': 'application/json', 'X-Telegram-Init-Data': tg?.initData || ''});
const escapeHtml = value => String(value ?? '').replace(/[&<'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const pct = (value, max) => Math.max(0, Math.min(100, max ? value / max * 100 : 0));

async function request(path, options = {}) {
  const response = await fetch(path, {...options, headers: {...headers(), ...(options.headers || {})}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || data.status || 'Ошибка запроса');
  return data;
}

function ownSide(battle) {
  const active = battle.state?.active_side;
  if ((battle.controller_sides || []).includes(active)) return active;
  return battle.controller_sides?.[0] || battle.owner_sides?.[0] || 'a';
}

function fighterCard(side, position) {
  const battle = payload.battle;
  const fighter = battle.state.sides[side];
  const user = battle.fighters[side];
  const cls = payload.classes[fighter.class_id] || {name:fighter.class_id, resource_name:'Выносливость'};
  const effects = Object.values(fighter.effects || {}).map(effect => `${effect.id} (${effect.turns})`).join(' · ');
  return `<section class="combatant ${position}"><div class="sprite ${position === 'enemy' ? 'enemy-sprite' : ''}"><span>${position === 'enemy' ? '👤' : '🧍'}</span></div><div class="status-card"><div class="status-title"><strong>${escapeHtml(user.name)}</strong><b>Lv.${fighter.level}</b></div><div class="class-name">${escapeHtml(cls.name)}${fighter.controlled ? ' · контроль −20%' : ''}</div><div class="hp-line"><span>HP</span><div class="meter hp"><i style="width:${pct(fighter.hp, fighter.stats.max_hp)}%"></i></div><em>${Math.round(fighter.hp)}/${Math.round(fighter.stats.max_hp)}</em></div><div class="hp-line resource"><span>${escapeHtml(cls.resource_name)}</span><div class="meter resource-meter"><i style="width:${pct(fighter.resource, fighter.stats.resource_max)}%"></i></div><em>${Math.round(fighter.resource)}</em></div><div class="effects">${escapeHtml(effects)}</div></div></section>`;
}

function recentLog() {
  const entries = (payload.battle.state.log || []).slice(-4).reverse();
  return entries.map(entry => `<div><b>Ход ${entry.turn}</b> ${entry.events.map(escapeHtml).join(' · ')}</div>`).join('') || '<div>Ожидание первого действия.</div>';
}

function actionPanel() {
  const battle = payload.battle;
  const state = battle.state;
  const active = state.active_side;
  const controlled = (battle.controller_sides || []).includes(active);
  const fighter = state.sides[active];
  const who = escapeHtml(battle.fighters[active].name);
  if (state.phase === 'dodge') {
    const pending = state.pending_action || {};
    const skill = payload.skills[pending.skill_id];
    const text = skill ? `${escapeHtml(battle.fighters[pending.side]?.name || 'Противник')} использует «${escapeHtml(skill.name)}»!` : 'Противник атакует!';
    if (!controlled) return `<section class="command-box"><p>${text}</p><small>Ожидание уклонения соперника…</small></section>`;
    return `<section class="command-box"><p>${text}</p><b>Куда уклоняться?</b><div class="direction-row"><button data-dodge="left">◀ Влево</button><button data-dodge="right">Вправо ▶</button></div></section>`;
  }
  if (!controlled) return `<section class="command-box"><p>Ходит ${who}.</p><small>Ожидание выбора навыка…</small></section>`;
  const skills = fighter.loadout.map(id => payload.skills[id]).filter(Boolean);
  if (!selectedSkill || !skills.some(skill => skill.id === selectedSkill)) selectedSkill = null;
  if (selectedSkill) {
    const skill = payload.skills[selectedSkill];
    if (!skill.hostile) return `<section class="command-box"><p>Использовать «${escapeHtml(skill.name)}»?</p><div class="direction-row"><button id="use-support">Использовать</button><button class="secondary" id="cancel-skill">Назад</button></div></section>`;
    return `<section class="command-box"><p>«${escapeHtml(skill.name)}» — откуда бьём?</p><div class="direction-row"><button data-attack="left">◀ Слева</button><button data-attack="right">Справа ▶</button></div><button class="back" id="cancel-skill">← К навыкам</button></section>`;
  }
  return `<section class="command-box"><p>Что сделает ${who}?</p><div class="skill-grid">${skills.map(skill => `<button class="skill" data-skill="${skill.id}" ${fighter.cooldowns[skill.id] || fighter.resource < skill.cost ? 'disabled' : ''}><strong>${escapeHtml(skill.name)}</strong><small>${skill.cost} ресурса${fighter.cooldowns[skill.id] ? ` · КД ${fighter.cooldowns[skill.id]}` : ''}</small></button>`).join('')}</div></section>`;
}

function render() {
  if (!payload?.battle) return;
  const battle = payload.battle;
  if (!battle.state) { root.innerHTML = '<div class="notice">Загрузка боя…</div>'; return; }
  if (isWasteland && battle.status === 'victory') {
    const reward = battle.state.wasteland?.reward_xp || 0;
    root.innerHTML = `<div class="notice">🏜 Этаж ${battle.floor} пройден. Получено ${reward} XP.<button id="next-floor">Идти дальше</button></div>`;
    document.getElementById('next-floor')?.addEventListener('click', nextFloor);
    return;
  }
  if (isWasteland && battle.status === 'defeated') { root.innerHTML = `<div class="notice">🏜 Поход завершён на этаже ${battle.floor}. Штрафов нет — новый поход доступен в /menu.</div>`; return; }
  if (battle.status !== 'active') { root.innerHTML = `<div class="notice">${battle.status === 'finished' ? 'Битва завершена.' : 'Битва ещё не началась.'}</div>`; return; }
  const own = ownSide(battle);
  const enemy = own === 'a' ? 'b' : 'a';
  const title = isWasteland ? `🏜 Пустошь · этаж ${battle.floor}` : '⚔️ Битва рабов';
  const potion = !isWasteland && battle.owner_sides?.length ? '<button class="potion" id="potion">🧪 Использовать зелье</button>' : '';
  root.innerHTML = `<div class="arena"><header><div><h1>${title}</h1><small>Ход ${battle.state.turn}</small></div>${tg?.requestFullscreen ? '<button class="fullscreen" id="fullscreen" title="Развернуть">⛶</button>' : ''}</header><section class="battlefield">${fighterCard(enemy, 'enemy')}${fighterCard(own, 'ally')}</section>${flash ? `<div class="battle-flash">${escapeHtml(flash)}</div>` : ''}${actionPanel()}${potion}<section class="battle-log">${recentLog()}</section></div>`;
  document.getElementById('fullscreen')?.addEventListener('click', () => tg?.requestFullscreen?.());
  document.querySelectorAll('[data-skill]').forEach(button => button.addEventListener('click', () => { selectedSkill = button.dataset.skill; render(); }));
  document.querySelectorAll('[data-attack]').forEach(button => button.addEventListener('click', () => submitAction({skill_id:selectedSkill, attack_direction:button.dataset.attack})));
  document.querySelectorAll('[data-dodge]').forEach(button => button.addEventListener('click', () => submitAction({dodge_direction:button.dataset.dodge})));
  document.getElementById('use-support')?.addEventListener('click', () => submitAction({skill_id:selectedSkill}));
  document.getElementById('cancel-skill')?.addEventListener('click', () => { selectedSkill = null; render(); });
  document.getElementById('potion')?.addEventListener('click', usePotion);
}

function showFlash(value) { flash = value; clearTimeout(flashTimer); flashTimer = setTimeout(() => { flash = ''; render(); }, 1800); }
async function load() { if (!token) { root.innerHTML = '<div class="error">Не указан ID битвы.</div>'; return; } try { payload = await request(`${apiRoot}/${encodeURIComponent(token)}`); render(); } catch (error) { root.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; } }
async function submitAction(action) { try { const result = await request(`${apiRoot}/${encodeURIComponent(token)}/action`, {method:'POST', body:JSON.stringify(action)}); selectedSkill = null; if (result.state?.log?.length) showFlash(result.state.log.at(-1).events.join(' · ')); tg?.HapticFeedback?.impactOccurred?.('medium'); await load(); } catch (error) { tg?.showAlert?.(error.message); } }
async function usePotion() { try { const result = await request(`/api/battle/${encodeURIComponent(token)}/potion`, {method:'POST', body:JSON.stringify({side:ownSide(payload.battle)})}); showFlash(`Восстановлено ${result.healed} HP`); await load(); } catch (error) { tg?.showAlert?.(error.message); } }
async function nextFloor() { try { await request(`${apiRoot}/${encodeURIComponent(token)}/next`, {method:'POST', body:'{}'}); await load(); } catch (error) { tg?.showAlert?.(error.message); } }
load();
setInterval(load, 2500);
