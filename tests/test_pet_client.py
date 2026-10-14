"""Pet detail cards must not show another pet's upgrade instructions."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from arena_pets import PETS


@unittest.skipUnless(shutil.which('node'), 'Node is needed for client tests')
class PetDetailClientTests(unittest.TestCase):
    def inspect(self, pet_id, owned=True):
        source = (Path(__file__).resolve().parents[1] / 'webapp' / 'pet-client').read_text(encoding='utf-8')
        source = source.replace('  boot();', "  view=input;inspect(input.catalog[0].id);out=JSON.stringify({level:$('detailLevel').textContent,effect:$('detailEffect').textContent,name:$('detailName').textContent});")
        pet = dict(PETS[pet_id], sprite_url='/pets/' + pet_id + '.png')
        data = dict(catalog=[pet], equipped=None, owned=[dict(pet, level=1, power=0, tempo=0)] if owned else [])
        script = """
const vm=require('node:vm');
const p=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const elements=new Map();
const el=id=>{if(!elements.has(id))elements.set(id,{textContent:'',checked:false,open:false,getContext(){return null},showModal(){this.open=true}});return elements.get(id)};
const c={window:{},document:{getElementById:el,addEventListener(){}},location:{search:''},
 URLSearchParams,ResizeObserver:class{observe(){}},matchMedia:()=>({matches:false}),
 localStorage:{getItem(){return null}},setInterval(){},input:p.data,out:''};
vm.runInNewContext(p.source,c);
process.stdout.write(c.out);
"""
        result = subprocess.run([shutil.which('node'), '-e', script], input=json.dumps(dict(source=source, data=data)),
                                text=True, encoding='utf-8', capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_owl_has_bleeding_hint_not_sandwich(self):
        card = self.inspect('smesharik')
        self.assertEqual(card['name'], PETS['smesharik']['name'])
        self.assertEqual(card['effect'], PETS['smesharik']['description'])
        self.assertIn('Сила усиливает кровотечение', card['level'])
        self.assertIn('частота уменьшает число попаданий', card['level'])
        self.assertNotIn('сэндвич', card['level'])
        self.assertNotIn('порог HP', card['level'])

    def test_sandwich_hint_only_in_sandwich_card(self):
        for pet_id in PETS:
            with self.subTest(pet_id=pet_id):
                text = self.inspect(pet_id)['level']
                self.assertEqual('сэндвич' in text, pet_id == 'sandwich')
                self.assertEqual('один раз за бой' in text, pet_id == 'sandwich')
                self.assertIn('Уровень 1 / 10', text)

    def test_unowned_pet_shows_collection_hint_without_upgrades(self):
        card = self.inspect('smesharik', owned=False)
        self.assertIn('Ещё нет в коллекции', card['level'])
        self.assertNotIn('Сила усиливает', card['level'])
