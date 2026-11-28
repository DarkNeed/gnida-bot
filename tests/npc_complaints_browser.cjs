const assert=require('node:assert/strict');
const {chromium}=require('playwright');

(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>Object.defineProperty(crypto,'randomUUID',{value:undefined}));
    await page.goto((process.env.NPC_ORIGIN||'http://127.0.0.1:8171')+'/npc-review');
    const get=()=>page.evaluate(async()=>(await fetch('/api/holdings/-100')).json());
    const act=(name)=>page.locator(`[data-npc-act="${name}"]`);
    const dialog=page.locator('dialog.holdings-dialog');
    const notice=page.locator('#holdings-notice');
    const result=()=>page.waitForResponse(r=>r.url().endsWith('/api/holdings/-100')&&r.request().method()==='POST');

    await page.locator('[data-h="tab:trader"]').click();
    await act('buy').first().click();
    assert.match(await dialog.innerText(),/В кошельке чата/);
    const buy=result();await dialog.locator('[data-npc-act="confirm"]').click();
    const purchase=await buy;assert.equal(purchase.status(),200);
    await notice.getByText(/Списано/).waitFor();
    assert.equal((await purchase.json()).holdings.npc.workers.length,5);

    await act('buy').first().click();
    const stale=await dialog.locator('[data-npc-act="confirm"]').getAttribute('data-npc-id');
    await page.evaluate(()=>fetch('/demo/time',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hours:25})}));
    const failing=result();await dialog.locator('[data-npc-act="confirm"]').click();
    assert.equal((await failing).status(),400);
    await notice.getByText(/Предложение устарело/).waitFor();
    assert.equal(await page.locator(`[data-npc-act="buy"][data-npc-id="${stale}"]`).count(),0);

    await page.locator('[data-h="tab:overview"]').click();
    await act('conditions').first().click();assert.match(await dialog.innerText(),/побег .*похищение/);
    if(!(await dialog.getByText(/Договор действует до/).count())){
      await dialog.locator('[data-npc-act="agreement"]').click();
      const agreement=result();await dialog.locator('[data-npc-act="confirm"]').click();
      assert.equal((await agreement).status(),200);await notice.getByText(/Договор действует/).waitFor();
    }
    assert((await get()).npc.workforce.risk.agreement_until);

    await page.locator('[data-demo-event="escaped"]').click();
    await act('event').first().click();assert.match(await dialog.innerText(),/Крайний срок/);
    await dialog.locator('[data-npc-act="negotiate"]').click();
    const recovery=result();await dialog.locator('[data-npc-act="confirm"]').click();
    assert.equal((await recovery).status(),200);await notice.getByText(/Работник возвращён/).waitFor();
    assert.deepEqual(errors,[]);
    console.log('PASS mobile NPC purchase without randomUUID, stale market refresh, agreement and escape recovery');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
