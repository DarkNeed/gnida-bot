/* Optional real-browser QA: NODE_PATH must include Playwright; preview on port 8103. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const safePath = require('./qte_lab_path.cjs');
const base = process.env.QTE_LAB_URL || 'http://127.0.0.1:8103/qte-lab/';
const output = path.join(__dirname, '..', 'output', 'qte-lab');
fs.mkdirSync(output, {recursive:true});

async function followDefense(page, capture) {
  await page.evaluate(()=>__advance(1/120));
  const route = safePath(await page.evaluate(()=>JSON.parse(JSON.stringify(__defense))));
  assert(route,'Current curtain pattern must remain passable');
  const midpoint=Math.floor(route.length/2);
  async function follow(points) {
    await page.evaluate(points=>{
      const canvas=document.getElementById('game');
      for(const point of points) {
        const dx=point.x-__defense.player.x,dy=point.y-__defense.player.y;
        const code=Math.abs(dx)>.1 ? dx>0 ? 'ArrowRight' : 'ArrowLeft' : Math.abs(dy)>.1 ? dy>0 ? 'ArrowDown' : 'ArrowUp' : null;
        if(code) canvas.dispatchEvent(new KeyboardEvent('keydown',{code,bubbles:true}));
        __advance(1/60);
        if(code) canvas.dispatchEvent(new KeyboardEvent('keyup',{code,bubbles:true}));
      }
    },points);
  }
  await follow(route.slice(0,midpoint));
  if(capture) await page.screenshot({path:path.join(output,capture),fullPage:true});
  await follow(route.slice(midpoint));
}

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || undefined});
  const errors=[], requests=[];
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1100}});
    page.on('pageerror',error=>errors.push(error.message));
    page.on('request',r=>requests.push(r.url()));
    await page.addInitScript(() => {
      let clock=1000, queue=[];
      window.requestAnimationFrame=cb=>{queue.push(cb); return queue.length;};
      window.__advance=seconds=>{
        for(let i=0;i<Math.ceil(seconds*120);i++) {
          clock+=1000/120; const callbacks=queue; queue=[]; callbacks.forEach(cb=>cb(clock));
        }
      };
    });
    await page.goto(base); await page.locator('#start').waitFor();
    await page.evaluate(()=>{
      const attack=QTELab.attack;
      QTELab.attack=options=>(window.__attack=attack(options));
      const defense=QTELab.defense;
      QTELab.defense=options=>(window.__defense=defense(options));
    });
    await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.locator('#start').click();
    await page.evaluate(()=>__advance(4));
    assert.match(await page.locator('#feedback').innerText(),/0\/1 попаданий/);

    await page.locator('#start').click();
    await page.evaluate(()=>{
      while(Math.abs(QTELab.attackFrame(__attack).cursor-QTELab.attackFrame(__attack).center)>__attack.p.zone/4) __advance(1/120);
    });
    await page.screenshot({path:path.join(output,'attack.png'),fullPage:true});
    await page.keyboard.press('Space');
    assert.match(await page.locator('#feedback').innerText(),/1\/1 попаданий/);

    await page.locator('#skill').selectOption('tiger'); await page.locator('#start').click();
    for(let i=0;i<6;i++) {
      await page.evaluate(index=>{
        let steps=0;
        while((QTELab.attackFrame(__attack).index!==index || Math.abs(QTELab.attackFrame(__attack).cursor-QTELab.attackFrame(__attack).center)>__attack.p.zone/4) && steps++<500) __advance(1/120);
      },i);
      await page.keyboard.press('Space');
    }
    assert.match(await page.locator('#feedback').innerText(),/6\/6 попаданий · 72/);
    console.log('PASS browser attack: timeout, exact input, six separate hits');

    await page.locator('[data-mode=dodge]').click(); await page.locator('#pattern').selectOption('rain');
    await page.locator('#start').click(); await page.keyboard.down('ArrowLeft');
    await page.evaluate(()=>__advance(.1)); await page.keyboard.up('ArrowLeft');
    await followDefense(page,'dodge.png');
    assert.match(await page.locator('#feedback').innerText(),/ПОЛНОЕ УКЛОНЕНИЕ.*0 урона/);
    console.log('PASS browser dodge: keyboard control, complete avoidance, zero damage');

    await page.locator('#start').click(); await page.evaluate(()=>__advance(.5));
    const before=await page.evaluate(()=>__defense.time);
    await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
    await page.evaluate(()=>__advance(10));
    assert.equal(await page.evaluate(()=>__defense.time),before);
    assert.equal(await page.locator('#resume').isVisible(),true);
    await page.locator('#resume').click(); await page.evaluate(()=>__advance(.2));
    assert((await page.evaluate(()=>__defense.time))>before);
    await page.locator('#stop').click();
    console.log('PASS browser pause: no progress on loss of focus, explicit resume');

    await page.locator('[data-mode=duel]').click(); await page.locator('#skill').selectOption('strike');
    await page.locator('#start').click();
    await page.evaluate(()=>{
      while(Math.abs(QTELab.attackFrame(__attack).cursor-QTELab.attackFrame(__attack).center)>__attack.p.zone/4) __advance(1/120);
    });
    await page.keyboard.press('Space');
    assert.equal(await page.locator('#boss-hp').innerText(),'280 / 320');
    await page.evaluate(()=>__advance(1.5));
    assert.equal(await page.locator('#game').getAttribute('data-phase'),'defense');
    await page.keyboard.down('ArrowLeft'); await page.evaluate(()=>__advance(6.2)); await page.keyboard.up('ArrowLeft');
    assert.match(await page.locator('#round').innerText(),/ХОД 2/);
    await page.locator('#start').click(); await page.locator('#stop').click();
    assert.equal(await page.locator('#boss-hp').innerText(),'320 / 320');
    console.log('PASS browser duel: attack damage, boss response, next turn, reset');

    await page.locator('[data-preset=strong]').click();
    await page.locator('#skill').selectOption('tiger');
    for(let turn=1;turn<=5;turn++) {
      await page.locator('#start').click();
      for(let i=0;i<6;i++) {
        await page.evaluate(index=>{
          let steps=0;
          while((QTELab.attackFrame(__attack).index!==index || Math.abs(QTELab.attackFrame(__attack).cursor-QTELab.attackFrame(__attack).center)>__attack.p.zone/4) && steps++<500) __advance(1/120);
        },i);
        await page.keyboard.press('Space');
      }
      if(turn===5) break;
      await page.evaluate(()=>__advance(1.5));
      await followDefense(page);
    }
    assert.match(await page.locator('#feedback').innerText(),/ПОБЕДА/);
    await page.locator('#start').click(); await page.locator('#stop').click();
    assert.equal(await page.locator('#boss-hp').innerText(),'320 / 320');
    // Losing is also a real outcome: miss the QTE and stand still in aimed volleys.
    await page.locator('[data-preset=equal]').click(); await page.locator('#pattern').selectOption('slashes');
    for(let turn=0;turn<12;turn++) {
      await page.locator('#start').click(); await page.evaluate(()=>__advance(15));
      if((await page.locator('#player-hp').innerText()).startsWith('0 /')) break;
    }
    assert.match(await page.locator('#feedback').innerText(),/ПОРАЖЕНИЕ/);
    console.log('PASS full duel victory, restart and defeat');

    const mobile=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true,deviceScaleFactor:2});
    mobile.on('pageerror',error=>errors.push(error.message));
    await mobile.addInitScript(() => {
      let clock=1000,queue=[];
      window.requestAnimationFrame=cb=>{queue.push(cb);};
      window.__advance=seconds=>{for(let i=0;i<Math.ceil(seconds*120);i++) {
        clock+=1000/120; const callbacks=queue; queue=[]; callbacks.forEach(cb=>cb(clock));
      }};
    });
    await mobile.goto(base);
    await mobile.evaluate(()=>{
      const defense=QTELab.defense;
      QTELab.defense=options=>(window.__defense=defense(options));
    });
    assert.equal(await mobile.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await mobile.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
    await mobile.locator('[data-mode=dodge]').tap(); await mobile.locator('#start').tap();
    assert.equal(await mobile.locator('#pad').isVisible(),true);
    const touch=await mobile.context().newCDPSession(mobile);
    const box=await mobile.locator('#game').boundingBox();
    const point={x:box.x+box.width*.7,y:box.y+box.height*.7};
    await touch.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[point]});
    await mobile.evaluate(()=>__advance(.25));
    await touch.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:point.x-45,y:point.y-20}]});
    await mobile.evaluate(()=>__advance(.2));
    await touch.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
    const moved=await mobile.evaluate(()=>__defense.player.x);
    assert(moved>720*.32+5,'touch input must actually move the player');
    await mobile.locator('[data-move=left]').scrollIntoViewIfNeeded();
    const padBox=await mobile.locator('[data-move=left]').boundingBox();
    await touch.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:padBox.x+padBox.width/2,y:padBox.y+padBox.height/2}]});
    await mobile.evaluate(()=>__advance(.2));
    await touch.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
    assert((await mobile.evaluate(()=>__defense.player.x))<moved-10,'onscreen arrow must actually move the player');
    assert.equal(await mobile.locator('#game').getAttribute('data-phase'),'defense');
    await mobile.screenshot({path:path.join(output,'mobile-dodge.png'),fullPage:true});
    console.log('PASS mobile: no horizontal overflow, touch movement, onscreen controls');
    assert.deepEqual(errors,[]); assert(!requests.some(url=>url.includes('/api/')));
    console.log('PASS no browser errors or game API requests');
  } finally {await browser.close();}
})().catch(error=>{console.error(error); process.exitCode=1;});
