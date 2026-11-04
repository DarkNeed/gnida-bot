"""Read-only validation of the generated Unity combat reference package."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile


folder = Path(sys.argv[1]).resolve()


def read(name):
    return json.loads((folder / name).read_text(encoding='utf-8'))


manifest = read('MANIFEST.json')
catalog = read('catalog.json')
profiles = read('qte_profiles.json')
fixtures = read('qte_fixtures.json')
combat = read('combat_fixtures.json')
assert len(catalog['classes']) == 13
assert len(catalog['branches']) == 25
assert len(catalog['mastery_base']) == 13
assert len(catalog['mastery_arch']) == 25
assert len({b['id'] for b in catalog['branches']}) == 25
assert all(b['final_name'] for b in catalog['branches'])
assert len({p['descriptor']['id'] for p in profiles}) == len(profiles)
assert len(fixtures) == 27 * 4
for f in fixtures:
    if '/attack/' not in f['id']:
        continue
    count = f['challenge']['strikes']
    assert len(f['input']['clicks']) == count
    assert len(set(f['input']['clicks'])) == count
    if f['id'].endswith('/perfect'):
        assert all(f['expected']['mask'])
    else:
        assert not f['expected']['mask'][0]
        assert all(f['expected']['mask'][1:])
assert len(combat) == 13
assert all(f['random_draws'] for f in combat)
assert all(f['command']['skill'] for f in combat)
for name, expected in manifest['files'].items():
    path = folder / name
    assert path.is_file(), name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
    assert path.suffix.lower() not in {'.sqlite', '.sqlite3', '.db', '.env'}, name
    assert path.name.lower() not in {'.env', 'config.py', 'secrets.json'}, name
with zipfile.ZipFile(folder.with_suffix('.zip')) as archive:
    assert archive.testzip() is None
    expected_files = set(manifest['files']) | {'MANIFEST.json'}
    assert set(archive.namelist()) == expected_files
    for name in expected_files:
        assert archive.read(name) == (folder / name).read_bytes(), name
print(json.dumps(dict(ok=True, folder=str(folder), counts=manifest['counts'],
                      verified_files=len(manifest['files']),
                      archive_bytes=folder.with_suffix('.zip').stat().st_size), ensure_ascii=False))
