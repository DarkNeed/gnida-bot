"""Persisted dungeon-room art, never a per-refresh random roll or arbitrary URL."""

BACKGROUNDS = {
    'hall': ('Каменный зал','/static/assets/guild/backgrounds/hall-v1.png'),
    'catacombs': ('Катакомбы','/static/assets/guild/backgrounds/catacombs-v1.png'),
    'cavern': ('Подземная пещера','/static/assets/guild/backgrounds/cavern-v1.png'),
}


def room_background(contract, node):
    """Rank measures danger, not architecture; keep outdoor/volcanic identity."""
    if contract['kind']!='dungeon':return 'biome'
    biome=contract['biome'];kind=node['kind'];event=node.get('event')
    if biome=='caldera':return 'biome'
    if biome=='forest':
        return 'cavern' if kind in ('treasure','elite','boss') or event in ('cocoon','chest') else 'biome'
    if biome in ('mines','crypt'):
        if kind in ('treasure','elite','boss') or event in ('shrine','chest'):return 'hall'
        return 'catacombs' if biome=='crypt' else 'cavern'
    return 'biome'


def assign_background(contract, node):
    # Preserve existing snapshots. Legacy rooms get an assignment on entry,
    # while battles already in progress retain their original appearance.
    if node.get('scenery') not in (*BACKGROUNDS,'biome'):
        node['scenery']=room_background(contract,node)
    return node['scenery']


def background_view(key):
    name,url=BACKGROUNDS.get(key,('Окружение локации',''))
    return dict(key=key if key in BACKGROUNDS else 'biome',name=name,url=url)
