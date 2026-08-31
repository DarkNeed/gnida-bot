const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const params = new URLSearchParams(location.search);
const token = params.get('battle');
const root = document.getElementById('app');
let payload = null;
let selectedSkill = null;
let controlledSide = null;

const headers = () => ({
  'Content-Type': 'application/json',
  'X-Telegram-Init-Data': tg?.initData || ''
});

const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const pct = (value, max) => Math.max(0, Math.min(100, max ? value / max * 100 : 0));

async function request(path, options = {}) {
  const response = await fetch(path, {...options, headers: {...headers(), ...(options.headers || {})}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || data.status || 'Ошибка запроса');
  return data;
}

function fighterCard(side, enemy = false) {
  const battle = payload.battle;
  const fighter = battle.state.sides[side];
  const user = battle.fighters[side];
  const cls = payload.classes[fighter.class_id] || {name:fighter.class_id,resource_name:'Выносливость'};
  const effects = Object.values(fighter.effects || {}).map(e => `${e.id} (${e.turns})`).join(' · ');
  return `<section class="fighter ${enemy ? 'enemy' : ''}">
    <div class="fighter-head"><div class="avatar">🧍</div><div><h2>${escapeHtml(user.name)}</h2><div class="class-name">${escapeHtml(cls.name)} · ур. ${fighter.level}${fighter.controlled ? ' · контроль −20%' : ''}</div></div></div>
    <div class="bar hp"><span style="width:${pct(fighter.hp,fighter.stats.max_hp)}%"></span></div>
    <div class="bar-label"><span>HP</span><span>${Math.round(fighter.hp)} / ${Math.round(fighter.stats.max_hp)}</span></div>
    <div class="bar mana"><span style="width:${pct(fighter.resource,fighter.stats.resource_max)}%"></span></div>
    <div class="bar-label"><span>${escapeHtml(cls.resource_name)}</span><span>${Math.round(fighter.resource)} / ${Math.round(fighter.stats.resource_max)}</span></div>
    <div class="effects">${escapeHtml(effects)}</div>
  </section>`;
}

function battleLog() {
  const entries = (payload.battle.state.log || []).slice().reverse();
  return entries.map(entry => `<div><b>Ход ${entry.turn}:</b> ${entry.events.map(escapeHtml).join(' · ')}</div>`).join('') || '<div>Бой только начался.</div>';
}

function controls() {
  const battle = payload.battle;
  const sides = battle.controller_sides || [];
  if (!controlledSide || !sides.includes(controlledSide)) controlledSide = sides[0] || null;
  const side = controlledSide;
  const owner = battle.owner_sides.length > 0;
  if (!side) {
    return `<section class="panel"><div class="notice">Вы наблюдаете за боем.</div>${owner ? '<button class="item" id="potion">🧪 Использовать Зелье</button>' : ''}</section>`;
  }
  const fighter = battle.state.sides[side];
  const skills = fighter.loadout.map(id => payload.skills[id]).filter(Boolean);
  if (!selectedSkill || !skills.some(skill => skill.id === selectedSkill)) selectedSkill = skills[0]?.id;
  const sidePicker = sides.length > 1 ? `<div class="side-picker">${sides.map(item => `<button class="item ${item === side ? '' : 'secondary'}" data-side="${item}">Ход за ${escapeHtml(battle.fighters[item].name)}</button>`).join('')}</div>` : '';
  return `<section class="panel">${sidePicker}
    <div class="skills">${skills.map(skill => `<button class="skill ${selectedSkill === skill.id ? '' : 'secondary'}" data-skill="${skill.id}" ${fighter.cooldowns[skill.id] || fighter.resource < skill.cost ? 'disabled' : ''}>${escapeHtml(skill.name)}<br><small>${skill.cost} ресурса${fighter.cooldowns[skill.id] ? ` · КД ${fighter.cooldowns[skill.id]}` : ''}</small></button>`).join('')}</div>
    <div class="directions">
      <div class="direction-box"><strong>Атака</strong><label><input type="radio" name="attack" value="left" checked> слева</label><label><input type="radio" name="attack" value="right"> справа</label></div>
      <div class="direction-box"><strong>Уклонение</strong><label><input type="radio" name="dodge" value="left" checked> от левого</label><label><input type="radio" name="dodge" value="right"> от правого</label></div>
    </div>
    <button class="submit" id="submit">Подтвердить действие</button>
    ${owner ? '<button class="item" id="potion">🧪 Использовать Зелье</button>' : ''}
  </section>`;
}

function render() {
  if (!payload?.battle) return;
  const battle = payload.battle;
  if (battle.status !== 'active' || !battle.state) {
    root.innerHTML = `<div class="notice">${battle.status === 'finished' ? 'Битва завершена.' : 'Битва ещё не началась.'}</div>`;
    return;
  }
  const own = battle.controller_side || battle.owner_sides[0] || 'a';
  const enemy = own === 'a' ? 'b' : 'a';
  root.innerHTML = `<div class="arena"><header class="headline"><h1>Битва рабов #${battle.id}</h1><p>Ход ${battle.state.turn}</p></header>${fighterCard(enemy,true)}${fighterCard(own)}${controls()}<section class="panel log">${battleLog()}</section></div>`;
  document.querySelectorAll('.skill').forEach(button => button.addEventListener('click', () => { selectedSkill = button.dataset.skill; render(); }));
  document.querySelectorAll('[data-side]').forEach(button => button.addEventListener('click', () => { controlledSide = button.dataset.side; selectedSkill = null; render(); }));
  document.getElementById('submit')?.addEventListener('click', submitAction);
  document.getElementById('potion')?.addEventListener('click', usePotion);
}

async function load() {
  if (!token) { root.innerHTML = '<div class="error">Не указан ID битвы.</div>'; return; }
  try { payload = await request(`/api/battle/${encodeURIComponent(token)}`); render(); }
  catch (error) { root.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; }
}

async function submitAction() {
  const button = document.getElementById('submit');
  button.disabled = true;
  try {
    const skill = payload.skills[selectedSkill];
    const attack = document.querySelector('input[name="attack"]:checked')?.value || 'left';
    const dodge = document.querySelector('input[name="dodge"]:checked')?.value || 'left';
    const result = await request(`/api/battle/${encodeURIComponent(token)}/action`, {method:'POST',body:JSON.stringify({side:controlledSide,skill_id:selectedSkill,attack_direction:skill?.hostile ? attack : null,dodge_direction:dodge})});
    tg?.HapticFeedback?.notificationOccurred(result.status === 'finished' ? 'success' : 'warning');
    await load();
  } catch (error) { tg?.showAlert?.(error.message); button.disabled = false; }
}

async function usePotion() {
  try { const result = await request(`/api/battle/${encodeURIComponent(token)}/potion`, {method:'POST',body:JSON.stringify({side:controlledSide})}); tg?.showAlert?.(`Восстановлено HP: ${result.healed}`); await load(); }
  catch (error) { tg?.showAlert?.(error.message); }
}

load();
setInterval(load, 2500);
