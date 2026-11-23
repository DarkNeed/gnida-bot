const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

const people = [[10,'DDO'],[20,'MiniDDO'],[30,'Promix'],[40,'LSD'],
  [50,'Other sibling'],[60,'Third sibling'],[70,'Other spouse']];
const state = {
  revision:1, title:'Family layout', actor:10, owner:false, judge:false,
  origin:0, members:[0,...people.map(([id])=>id)], detached:[], branches:[10],
  people:people.map(([id,name])=>({id,name})),
  parents:[[10,20],[10,50]], siblings:[[30,40],[20,50],[50,60]],
  marriages:[[20,40],[50,70]], cases:[],
};

(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    for(const width of [320,900]){
      const page=await browser.newPage({viewport:{width,height:900},isMobile:width===320,hasTouch:width===320});
      const errors=[];
      page.on('pageerror',error=>errors.push(error.message));
      await page.route('https://telegram.org/**',route=>route.fulfill({
        contentType:'text/javascript',body:'window.Telegram={WebApp:{initData:"layout-test"}}',
      }));
      await page.route('https://family.test/**',route=>{
        const name=new URL(route.request().url()).pathname.split('/').at(-1);
        if(['family','family.js','family.css'].includes(name)){
          const file=name==='family'?'family.html':name;
          return route.fulfill({
            contentType:({family:'text/html','family.js':'text/javascript','family.css':'text/css'})[name],
            body:fs.readFileSync(path.join(__dirname,'../webapp',file),'utf8'),
          });
        }
        if(name==='-100')return route.fulfill({json:state});
        return route.fulfill({status:404});
      });
      await page.goto('https://family.test/family?entry=family_-100');
      await page.locator('[data-person="30"]').waitFor();
      assert.equal(await page.locator('.wires .sibling').count(),3);
      assert.equal(await page.locator('.wires .spouse').count(),2);
      const {cards,rings}=await page.locator('.world').evaluate(world=>{
        const rect=node=>{
          const {top,left,right}=node.getBoundingClientRect();
          return {top,left,right};
        };
        return {
          cards:Object.fromEntries([...world.querySelectorAll('[data-person]')].map(node=>[node.dataset.person,rect(node)])),
          rings:[...world.querySelectorAll('.ring')].map(rect),
        };
      });
      for(const [[a,b],ring] of state.marriages.map((pair,i)=>[pair,rings[i]])){
        const [left,right]=[cards[a],cards[b]].sort((x,y)=>x.left-y.left);
        assert.equal(left.top,right.top,'The married pair stays on the same generation row in this fixture');
        assert(!Object.values(cards).some(card=>card.top===left.top&&card.left>left.left&&card.left<right.left),
          'No relative may be placed between spouses');
        const ringX=(ring.left+ring.right)/2;
        assert(ringX>left.right&&ringX<right.left,'Ring lands in the gap between spouses');
      }
      assert.deepEqual(errors,[]);
      await page.close();
    }
  }finally{await browser.close();}
  console.log('Family layout: both spouse pairs stay adjacent on desktop and phone.');
})().catch(error=>{console.error(error);process.exitCode=1;});
