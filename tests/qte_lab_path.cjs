/* Test-only offline reachability check. Never served or used by the game client. */
const E = require('../webapp/qte-lab/engine');

module.exports = function safePath(initial) {
  const s = JSON.parse(JSON.stringify(initial));
  if (s.id === 'cross') throw new Error('Planner is for fixed curtain patterns only');
  const vertical = s.id === 'rain', fixed = vertical ? s.player.y : s.player.x;
  const axis = vertical ? 'x' : 'y', other = vertical ? 'y' : 'x';
  const max = (vertical ? E.W : E.H) - 12, dt = 1 / 60;
  let frontier = new Map([[s.player[axis].toFixed(3), {at:s.player[axis], cost:0}]]);
  const history = [];
  while (!s.ended) {
    const step = Math.min(dt, s.duration - s.time);
    E.defenseStep(s,step);
    const close = s.bullets.filter(b => Math.min(b[other], b[other] - b['v'+other]*step) <= fixed+b.r+s.player.r
      && Math.max(b[other], b[other] - b['v'+other]*step) >= fixed-b.r-s.player.r);
    const next = new Map();
    for (const [key, node] of frontier) for (const delta of [0,-s.p.moveSpeed*step,s.p.moveSpeed*step]) {
      const at = E.clamp(node.at + delta,12,max), label = at.toFixed(3);
      const cost = node.cost + Math.abs(at-node.at);
      if (next.has(label) && next.get(label).cost <= cost) continue;
      if (close.some(b => {
        const x1 = b.x-b.vx*step-(vertical ? node.at : fixed), y1=b.y-b.vy*step-(vertical ? fixed : node.at);
        const x2 = b.x-(vertical ? at : fixed), y2=b.y-(vertical ? fixed : at);
        return E.segmentDistance(0,0,x1,y1,x2,y2) <= b.r+s.player.r+.15;
      })) continue;
      next.set(label,{at,cost,previous:key});
    }
    if (!next.size) return null;
    history.push(next); frontier=next;
  }
  let label = [...frontier].sort((a,b)=>a[1].cost-b[1].cost)[0][0];
  const path=[];
  for(let i=history.length-1;i>=0;i--) {
    const node=history[i].get(label);
    path.push(vertical ? {x:node.at,y:fixed} : {x:fixed,y:node.at});
    label=node.previous;
  }
  return path.reverse();
};
