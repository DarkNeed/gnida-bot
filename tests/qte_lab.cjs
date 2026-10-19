const assert = require('node:assert/strict');
const E = require('../webapp/qte-lab/engine');
const equal = {accuracy:75, evasion:25, enemyAccuracy:75, enemyEvasion:25};
const strong = {accuracy:95, evasion:80, enemyAccuracy:50, enemyEvasion:10};
const weak = {accuracy:40, evasion:10, enemyAccuracy:95, enemyEvasion:70};
let checks = 0;
function test(name, fn) {fn(); checks++; console.log('PASS ' + name);}

test('Stats change actual zone, cursor, warning, speed and density monotonically', () => {
  const a = E.params(strong), b = E.params(equal), c = E.params(weak);
  assert(a.zone > b.zone && b.zone > c.zone);
  assert(a.cursor < b.cursor && b.cursor < c.cursor);
  assert(a.bulletSpeed < b.bulletSpeed && b.bulletSpeed < c.bulletSpeed);
  assert(a.warning > b.warning && b.warning > c.warning);
  assert(a.count <= b.count && b.count <= c.count);
});
test('Extreme stats retain nonzero, bounded, reachable target zones', () => {
  for (const accuracy of [0, 100]) for (const enemyEvasion of [0, 100]) {
    const s = E.attack({skill:'tiger', stats:{...equal, accuracy, enemyEvasion}, seed:2});
    assert(s.p.zone >= .075 && s.p.zone <= .29);
    assert(s.zones.every(x => x - s.p.zone/2 > 0 && x + s.p.zone/2 < 1));
  }
});
test('Curtains gain speed and shorter warnings; aiming and cross stay unchanged', () => {
  for (const stats of [strong, equal, weak, {accuracy:0,evasion:0,enemyAccuracy:100,enemyEvasion:100}]) {
    const base = E.params(stats);
    for (const pattern of Object.keys(E.PATTERNS)) {
      const s = E.defense({pattern,stats,seed:2});
      const multiplier = pattern === 'cross' ? 1 : pattern === 'rain' ? 1.6 : 1.55;
      assert.equal(s.p.bulletSpeed, base.bulletSpeed * multiplier);
      assert.equal(s.p.zone,base.zone); assert.equal(s.p.cursor,base.cursor);
      assert.equal(s.p.moveSpeed,base.moveSpeed);
      if(pattern === 'cross') assert.deepEqual(s.p,base);
      else {assert(s.p.warning<base.warning); assert(s.p.gap>60);}
      E.defenseStep(s,1.3);
      assert(s.bullets.length>0);
      for (const bullet of s.bullets) assert.equal(Math.hypot(bullet.vx,bullet.vy),s.p.bulletSpeed);
    }
    assert.equal(E.attack({skill:'strike',stats,seed:2}).p.bulletSpeed,base.bulletSpeed);
  }
});
test('Curtains have multiple pulses, solid walls and visible openings, from both sides', () => {
  for(const pattern of ['slashes','rain']) {
    const s=E.defense({pattern,stats:weak,seed:12});
    assert(s.waves.length>s.pattern.hits);
    assert(s.waves.some(w=>w.reverse) && s.waves.some(w=>!w.reverse));
    E.defenseStep(s,1.3);
    assert(s.bullets.length>20);
    const first=s.waves[0];
    assert(first.curtain && first.warned);
  }
});
test('Cross pattern retains its original seeded lanes and timing', () => {
  const s=E.defense({pattern:'cross',stats:equal,seed:12});
  let seed=12;
  for(let i=0;i<s.waves.length;i++) {
    seed=(Math.imul(seed,1664525)+1013904223)>>>0;
    assert.equal(s.waves[i].lane,.17+(seed/4294967296)*.66);
    assert.equal(s.waves[i].at,.2+i*.6);
    assert.equal(s.waves[i].strike,i);
  }
});
test('Curtains have legal zero-damage paths at every stat extreme', () => {
  const plan = require('./qte_lab_path.cjs');
  for(const pattern of ['slashes','rain']) for(const evasion of [0,25,80,100]) for(const seed of [1,10,23,42]) {
    const s=E.defense({pattern,stats:{...equal,enemyAccuracy:100,evasion},seed});
    const path=plan(s);
    assert(path,`${pattern} evasion=${evasion} seed=${seed} must remain passable`);
    for(const point of path) E.defenseStep(s,1/60,{target:point});
    assert.equal(E.defenseResult(s).damage,0,`${pattern} evasion=${evasion} seed=${seed}`);
  }
});
test('A correct input always hits; there is no second evasion roll', () => {
  for (let seed = 1; seed <= 200; seed++) {
    const s = E.attack({skill:'strike', stats:weak, seed});
    s.time = s.zones[0] / (s.p.cursor * 2);
    assert.equal(E.hit(s), true);
    assert.deepEqual(E.attackResult(s), {hits:1, total:1, damage:40});
  }
});
test('Wrong input and timeout miss, duplicate input cannot reroll', () => {
  const s = E.attack({skill:'tiger', stats:equal, seed:1});
  assert.equal(E.hit(s), false); assert.equal(E.hit(s), null);
  E.attackStep(s, 10);
  assert.equal(s.ended, true); assert.equal(E.attackResult(s).damage, 0);
  assert.equal(E.hit(s), null);
});
test('Tiger has six independent timing windows and exactly six possible hits', () => {
  const s = E.attack({skill:'tiger', stats:equal, seed:3});
  for (let i = 0; i < 6; i++) {
    s.time = s.skill.slot*i + s.zones[i] / (s.p.cursor*2);
    assert.equal(E.hit(s), true);
  }
  assert.equal(s.ended, true);
  assert.deepEqual(E.attackResult(s), {hits:6, total:6, damage:72});
});
test('Attack result does not depend on display refresh rate', () => {
  for (const rate of [30, 60, 144]) {
    const s = E.attack({skill:'tiger', stats:equal});
    while (!s.ended) E.attackStep(s, 1/rate);
    assert.deepEqual(s.results, [false,false,false,false,false,false]);
  }
});
test('A clean defense is a full dodge with exactly zero damage', () => {
  const s = E.defense({pattern:'rain', stats:equal, seed:3});
  s.waves = []; E.defenseStep(s, 6);
  assert.equal(s.ended, true);
  assert.deepEqual(E.defenseResult(s), {hits:0, total:3, dodged:3, damage:0});
});
test('Aimed warnings are locked before launch, not retargeted while dodging', () => {
  const s = E.defense({pattern:'slashes', stats:equal, seed:5});
  E.defenseStep(s,.25);
  const lane = s.waves[0].lane;
  assert.equal(s.waves[0].warned,true);
  E.defenseStep(s,.6,{x:0,y:1});
  assert.equal(s.waves[0].lane,lane);
  assert(s.player.y > lane*E.H);
});
test('Camping in the center or a corner is punished by aimed volleys', () => {
  for (const pattern of Object.keys(E.PATTERNS)) for (const corner of [false,true]) {
    const s=E.defense({pattern,stats:equal,seed:10});
    if(corner) {s.player.x=12; s.player.y=12;}
    E.defenseStep(s,6);
    assert(s.received.length>0,pattern+' corner='+corner);
  }
});
test('Multiple projectiles of one strike cannot deal repeated damage', () => {
  const s = E.defense({pattern:'slashes', stats:equal}); s.waves = [];
  s.bullets = Array.from({length:8}, () => ({...s.player, vx:0, vy:0, strike:2, r:8}));
  E.defenseStep(s, .1); E.defenseStep(s, .1);
  assert.deepEqual(E.defenseResult(s), {hits:1, total:6, dodged:5, damage:10});
});
test('Collision is swept, preventing tunnelling through the marker', () => {
  const s = E.defense({pattern:'slashes', stats:equal}); s.waves = [];
  s.bullets = [{x:s.player.x-100,y:s.player.y,vx:30000,vy:0,strike:0,r:5}];
  E.defenseStep(s, 1/60); assert.equal(s.received.length, 1);
});
test('Pointer movement is speed-limited and diagonal keyboard motion is normalized', () => {
  const a = E.defense({stats:equal}), b = E.defense({stats:equal}); a.waves=[]; b.waves=[];
  const x=a.player.x, y=a.player.y;
  E.defenseStep(a,.1,{target:{x:10000,y:10000}}); E.defenseStep(b,.1,{x:1,y:1});
  assert(Math.hypot(a.player.x-x,a.player.y-y) <= a.p.moveSpeed*.1+.0001);
  assert(Math.abs(Math.hypot(b.player.x-x,b.player.y-y)-b.p.moveSpeed*.1)<.0001);
});
test('Leaving the field is impossible with either control scheme', () => {
  const s = E.defense({stats:equal}); s.waves=[];
  E.defenseStep(s, 5, {target:{x:-1000,y:1000}});
  assert.equal(s.player.x,12); assert.equal(s.player.y,E.H-12);
});
test('Defense collisions agree at 30/60/144 Hz', () => {
  const results=[];
  for (const rate of [30,60,144]) {
    const s=E.defense({pattern:'cross',stats:equal,seed:42});
    while (!s.ended) E.defenseStep(s,1/rate,{x:0,y:0});
    results.push(E.defenseResult(s));
  }
  assert.deepEqual(results[0],results[1]); assert.deepEqual(results[1],results[2]);
});
test('All volleys launch and leave before trial end, even at minimum speed', () => {
  for (const pattern of Object.keys(E.PATTERNS)) {
    const s=E.defense({pattern,stats:{...equal,enemyAccuracy:0,evasion:100},seed:2});
    E.defenseStep(s,6);
    assert(s.waves.every(w=>w.spawned));
    assert.equal(s.bullets.length,0,pattern);
  }
});
console.log(`${checks} simulation checks passed.`);
