const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
let input='';process.stdin.on('data',s=>input+=s);process.stdin.on('end',async()=>{
 try{
 const view=JSON.parse(input),app={innerHTML:'',events:{},addEventListener(k,f){this.events[k]=f},querySelector(){return null}};
 const sandbox={window:{},console,AbortController,crypto:require('node:crypto').webcrypto,setInterval:()=>1,clearInterval(){},document:{hidden:false},fetch:async path=>({ok:true,json:async()=>path==='/api/kingdom/chats'?{chats:[{chat_id:-100,title:'Мир'}]}:structuredClone(view)})};vm.createContext(sandbox);
 for(const file of ['kingdom-map','kingdom-army','kingdom-diplomacy','kingdom-budget','kingdom'])vm.runInContext(fs.readFileSync('webapp/'+file+'.js','utf8'),sandbox);
 await sandbox.window.KingdomApp.open({app,chat:-100,initData:'test'});
 const click=k=>app.events.click({target:{closest:s=>s==='[data-k]'?{dataset:{k},disabled:false}:null}});
 assert(app.innerHTML.includes('k-live-camp'));assert(app.innerHTML.includes('Живые лагеря'));
 const nav=()=>app.innerHTML.split('aria-label="Разделы королевства">')[1].split('</nav>')[0];
 assert.equal((nav().match(/data-k="section:/g)||[]).length,4);
 assert(!nav().includes('tab:'));assert(app.innerHTML.includes('class="k-map-label"'));
 const boxes=()=>[...app.innerHTML.matchAll(/data-label-rect="([\d.,-]+)"/g)].map(m=>m[1].split(',').map(Number));
 const checkLabels=()=>{const all=boxes();assert(all.length>5);for(let i=0;i<all.length;i++){const[x,y,w,h]=all[i];assert(x>=0&&y>=0&&x+w<=964&&y+h<=652);for(let j=i+1;j<all.length;j++){const[a,b,c,d]=all[j];assert(!(x<a+c&&x+w>a&&y<b+d&&y+h>b),'nameplates overlap')}}};
 checkLabels();assert(app.innerHTML.includes('data-k="layer:names" aria-pressed="true"'));
 for(const label of app.innerHTML.matchAll(/<g class="k-name-label[^]*?<\/g>/g))assert(!label[0].includes('<rect '),'name background returned');
 await click('layer:names');assert(!app.innerHTML.includes('class="k-map-label"'));assert(app.innerHTML.includes('data-k="layer:names" aria-pressed="false"'));
 await click('layer:names');checkLabels();
 assert(!app.innerHTML.includes('k-resources'));assert(app.innerHTML.includes('k-status-strip'));
 await click('section:town');assert(app.innerHTML.includes('Особые сооружения'));assert(app.innerHTML.includes('Казна и налоги'));
 await click('section:military');assert(app.innerHTML.includes('Отряды и строй'));assert(app.innerHTML.includes('Походы и отчёты'));
 await click('section:government');assert(app.innerHTML.includes('Политика и вера'));assert(app.innerHTML.includes('Летопись'));
 await click('section:map');await click('campfocus:'+view.camps[0].id);
 checkLabels();assert.equal((app.innerHTML.match(/k-selected-label/g)||[]).length,1);
 await click('layer:camps');assert(!app.innerHTML.includes('class="k-live-camp '));
 await click('layer:camps');assert(app.innerHTML.includes('class="k-live-camp '));
 await click('tab:camps');assert(app.innerHTML.includes('Прочность укреплений'));assert(app.innerHTML.includes('camp_march:'));assert(!app.innerHTML.includes('undefined'));
 await click('camp_march:'+view.camps[0].id);assert(app.innerHTML.includes('Погибшие отряды'));assert(app.innerHTML.includes('role="dialog"'));await click('cancel');
 await click('tab:lands');assert(app.innerHTML.includes('k-estate-color'));assert(app.innerHTML.includes('Имя и украшение'));
 const town=view.towns.find(t=>t.own);await click('decor:'+town.q+':'+town.r);assert(app.innerHTML.includes('k-land-decoration'));await click('cancel');
 await click('tab:specials');assert(app.innerHTML.includes('Военная академия'));assert(app.innerHTML.includes('Чудо государства'));assert(app.innerHTML.includes('special_build:academy'));assert(!app.innerHTML.includes('NaN'));
 await click('special_build:academy');assert(app.innerHTML.includes('120'));assert(app.innerHTML.includes('role="dialog"'));
 console.log('PASS: real living-world renderer and confirmation routes');
 }catch(e){console.error(e);process.exitCode=1}
});
