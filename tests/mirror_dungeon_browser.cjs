const assert=require('node:assert/strict');
const {chromium}=require('playwright');

(async()=>{
  const origin=process.env.MIRROR_ORIGIN||'http://127.0.0.1:8174';
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:320,height:790},isMobile:true,hasTouch:true});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(origin+'/mirror-review?fresh=1&qte=0');
    await page.locator('.mirror-map-grid').waitFor();
    const backdrop=()=>page.locator('.mirror-map-scroll').evaluate(async el=>{
      const css=getComputedStyle(el);
      const path=css.backgroundImage.match(/url\("([^"]+)"\)/)?.[1];
      if(!path?.endsWith('/static/assets/mirror/other-side-v1.webp'))return false;
      const art=new Image();
      art.src=path;
      await art.decode();
      return art.naturalWidth>0&&css.backgroundSize.split(',').some(v=>v.trim()==='cover');
    });
    assert(await backdrop());
    const rows=await page.locator('[data-mirror-floor]').count();
    assert(rows>=4&&rows<=7);
    assert.equal(await page.locator(`[data-mirror-floor="${rows}"] button.mirror-node.shop[data-lane="1"]`).count(),1);
    assert.equal(await page.locator('button.mirror-node.shop').count(),1);
    assert.equal(await page.locator('.mirror-final-row button.mirror-node.boss[data-lane="1"]').count(),1);
    assert.equal(await page.locator('.mirror-node:enabled').count(),3);
    assert((await page.locator('.mirror-node.fight:enabled').evaluateAll(nodes=>nodes.map(n=>n.title)))
      .every(title=>title.endsWith('ур. 15')));
    assert(await page.locator('.mirror-node img').count()>=6);
    assert(await page.locator('[data-mirror-floor]').evaluateAll(rows=>rows.some(row=>{
      const nodes=[...row.querySelectorAll('button')], rect=row.getBoundingClientRect();
      return nodes.length===2&&nodes.every(node=>{
        const n=node.getBoundingClientRect(), x=rect.x+(Number(node.dataset.lane)+.5)*rect.width/3;
        return Math.abs(n.x+n.width/2-x)<1;
      });
    })));
    await page.waitForFunction(()=>document.querySelector('.mirror-node img')?.naturalWidth>0);
    const geometry=await page.locator('button.mirror-node.fight').first().evaluate(node=>{
      const tile=node.querySelector('.mirror-node-tile'), art=node.querySelector('.mirror-map-sprite');
      const t=tile.getBoundingClientRect(),a=art.getBoundingClientRect();
      return {corners:getComputedStyle(tile,'::before').clipPath.split(',').length,
        aligned:Math.abs(t.x+t.width/2-a.x-a.width/2)<1,
        overlaps:a.y<t.y&&a.bottom>t.y&&a.bottom<t.y+t.height/2,
        glyph:!!tile.querySelector('svg path')};
    });
    assert.deepEqual(geometry,{corners:8,aligned:true,overlaps:true,glyph:true});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    if(process.env.MIRROR_SCREENSHOT)await page.screenshot({path:process.env.MIRROR_SCREENSHOT});
    const terminals=page.locator('.mirror-map-grid .mirror-node-caption');
    assert.deepEqual(await terminals.allTextContents(),['Босс','Магазин']);
    assert.equal(await page.locator('[data-mirror-jump="end"]').count(),0);
    const fullscreen=()=>page.locator('.mirror-map-scroll').evaluate(map=>{
      const {x,y,width,height}=map.getBoundingClientRect();
      return x===0&&y===0&&Math.abs(width-innerWidth)<1&&Math.abs(height-innerHeight)<1;
    });
    assert(await fullscreen());
    assert(await page.locator('.mirror-map-scroll').evaluate(map=>{
      const rows=[...map.querySelectorAll('[data-mirror-floor]')];
      const dock=document.querySelector('.mirror-dock').getBoundingClientRect();
      const entry=rows.at(-1).getBoundingClientRect();
      return rows.every((n,i)=>Number(n.dataset.mirrorFloor)===rows.length-i)&&
        entry.top>=0&&entry.bottom<dock.top&&dock.top-entry.bottom<30&&
        [...map.querySelectorAll('.guild-map-lines path')].every(path=>{
          const d=path.getAttribute('d').match(/[\d.]+/g).map(Number);
          return d[1]>d[7];
        });
    }));

    await page.goto(origin+'/mirror-review?stage=shop&fresh=1');
    await page.getByRole('heading',{name:'Торговец отражениями'}).waitFor();
    const artifact=page.locator('.mirror-offer.artifact:enabled').first();
    assert(await artifact.count());
    assert(Number(await page.locator('.mirror-dashboard>div:last-child strong').innerText())>=18);
    await artifact.click();
    await page.locator('.mirror-info summary').click();
    await page.locator('.mirror-stash').getByText(/Артефакты забега · 1/).waitFor();
    await page.locator('.mirror-info summary').click();
    await page.reload();await page.getByRole('heading',{name:'Торговец отражениями'}).waitFor();
    assert.equal(await page.locator('button.mirror-node:enabled').count(),1);

    await page.goto(origin+'/mirror-review?fresh=1&qte=0');
    await page.locator('.mirror-node.fight:enabled').first().click();
    await page.locator('.battle').waitFor();
    assert.match(await page.locator('.battle').innerText(),/ЭТАЖ 1 \/ 10/);
    await page.locator('[data-do^="mirror:"]').first().click();
    await page.getByRole('heading',{name:'Бой на этаже 1'}).waitFor();

    await page.goto(origin+'/mirror-review?stage=final&fresh=1&qte=0');
    await page.getByRole('heading',{name:'К лавке перед боссом'}).waitFor();
    const shop=page.locator('button.mirror-node.shop');
    const boss=page.locator('.mirror-final-row .boss');
    assert(await boss.isDisabled());
    assert.equal(await page.locator('button.mirror-node:enabled').count(),1);
    await shop.click();
    await page.getByRole('heading',{name:'Торговец отражениями'}).waitFor();
    assert(await boss.isEnabled());
    await boss.click();
    await page.locator('.battle').waitFor();
    assert.match(await page.locator('.battle').innerText(),/ЗЕРКАЛО · БОСС · ЭТАЖ 1 \/ 10/);
    await page.goto(origin+'/mirror-review?stage=deep&fresh=1&qte=0');
    await page.locator('.mirror-map-grid').waitFor();
    assert.match(await page.locator('.mirror-dashboard').innerText(),/10\s*\/\s*10/);
    assert.match(await boss.getAttribute('title'),/ур\. 30$/);
    assert.match(await page.locator('.mirror-node.elite').first().getAttribute('title'),/ур\. 28$/);
    assert.match(await page.locator('.mirror-node.fight:enabled').first().getAttribute('title'),/ур\. 25$/);
    await page.setViewportSize({width:1280,height:720});
    await page.goto(origin+'/mirror-review?fresh=1&qte=0');
    await page.locator('.mirror-map-scroll').waitFor();
    assert(await fullscreen());
    assert(await backdrop());
    await page.setViewportSize({width:320,height:790});
    await page.goto(origin+'/mirror-review?stage=rewards');
    await page.getByRole('heading',{name:'Последнее отражение разбито'}).waitFor();
    assert.equal(await page.locator('[data-do^="mirrorchoice:claim:gear-"]').count(),4);
    assert.equal(await page.locator('[data-do^="mirrorchoice:claim:treatise-"]').count(),3);
    assert.match(await page.locator('[data-do="mirrorchoice:claim:gear-weapon"]').innerText(),/Эпический/);
    const pages=page.locator('[data-do="mirrorchoice:claim:pages"]');
    assert.match(await pages.innerText(),/6 редких/);
    await pages.scrollIntoViewIfNeeded();
    assert(await pages.evaluate(el=>{
      const a=el.getBoundingClientRect(), b=el.closest('.mirror-action-sheet').getBoundingClientRect();
      return a.top>=b.top-1&&a.bottom<=b.bottom+1;
    }));
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.locator('.mirror-info summary').click();
    assert.match(await page.locator('.mirror-receipts').innerText(),/Разбивший отражение/);
    assert.deepEqual(errors,[]);
    console.log('PASS 320px map, sprites, shop purchase, valid links, combat, and reload');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
