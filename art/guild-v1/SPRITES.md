# Спрайты монстров гильдии · v1

Созданы встроенным imagegen, по одному вызову на монстра. После явного разрешения пользователя программно очищен только alpha вокруг силуэта (tools/prepare_guild_sprites.py). RGB, размеры и непрозрачные части рисунков сохранены. Оригиналы в source/. Набор утверждён пользователем.

Папка готовых файлов: `webapp/assets/guild/`.

## Общая спецификация

Use case: stylized-concept. Asset type: transparent full-body enemy battle sprite for an illustrated dark fantasy 2D turn-based RPG, not pixel art.

Style: polished hand-painted dark fantasy anime game illustration, fine dark outlines, readable shapes, detailed but not noisy, muted natural palette with selective saturated accents. Composition: ONE isolated creature, full body centered, three-quarter side view FACING LEFT toward opponents, all weapons, limbs and tail inside frame, 8% clear margin. Eye-level orthographic-like game view. Plain genuinely transparent background with clean alpha. No ground, pedestal, scenery, text, labels, UI, border, watermark, drop shadow, outer glow or smoky halo. Edges crisp, no detached particles.

## Промпты отдельных монстров

### goblin

Файл: `webapp/assets/guild/goblin-v1.png`.

Subject: Goblin scout: small wiry moss-green goblin with long ears, malicious intelligent face, patched brown leather hood and scavenged straps, a chipped curved dagger held low, crouched ready to stab. No other characters.

### slime

Файл: `webapp/assets/guild/slime-v1.png`.

Subject: Mossy slime: a squat semi-translucent olive-green blob with acidic lime core, moss tufts and tiny bits of old bone trapped inside, two dim predatory eyes. Amorphous rounded body resting low, a few attached acid droplets, not cute, no separate ground.

### shaman

Файл: `webapp/assets/guild/shaman-v1.png`.

Subject: Goblin shaman: hunched green goblin with long ears, ragged oxblood and black robes, bone necklaces, rough wooden staff topped with a small bone fetish glowing dim violet. Cunning face, tattered layered silhouette.

### spider

Файл: `webapp/assets/guild/spider-v1.png`.

Subject: Veteran giant female spider: one sinister eight-legged charcoal arachnid, burgundy markings, a heavy textured abdomen, pale scars on carapace, tiny clustered red eyes, long jointed legs gathered in an attacking stance. Entire animal, no webs obscuring legs.

### wolf

Файл: `webapp/assets/guild/wolf-v1.png`.

Subject: Direwolf: one enormous lean battle-scarred charcoal grey wolf, shaggy bristling fur, long fangs, one torn ear, pale amber eyes, hunched shoulders, tense stalking side-three-quarter pose. Natural quadruped anatomy, no armor.

### orc

Файл: `webapp/assets/guild/orc-v1.png`.

Subject: Orc ravager: broad muscular dark olive orc, heavy tusks, worn blackened iron armor and rust leather, a crude heavy cleaver in one hand, aggressive forward-leaning stance. Scarred and brutal, full body.

### troll

Файл: `webapp/assets/guild/troll-v1.png`.

Subject: Swamp troll: towering hunched lanky giant, long powerful arms, mottled swamp-grey green skin, moss on back, warts and old scars, shaggy reeds over ragged loincloth, dragging a thick knotted wooden club. Hideous but readable anatomy.

### wraith

Файл: `webapp/assets/guild/wraith-v1.png`.

Subject: Wraith knight: spectral haunted medieval knight inside corroded slate-black plate, enclosed pointed helmet with narrow pale blue visor, tattered grey cloak, long ghostly ice-blue sword. Lower legs still visible, a few attached spectral wisps only, no fog cloud.

### golem

Файл: `webapp/assets/guild/golem-v1.png`.

Subject: Runic golem: massive asymmetrical humanoid stone construct, slate basalt slabs with carved old runes glowing restrained turquoise, huge blocky arms, small recessed head, moss in fissures. Heavy clear silhouette, entire stone feet visible.

### wyvern

Файл: `webapp/assets/guild/wyvern-v1.png`.

Subject: Plague wyvern: sickly olive and bruised purple winged reptile, precisely TWO hind legs and TWO leathery wings, long hooked tail, angular horned skull, pustules and yellow-green venom in fangs. Wings folded partly upward for a readable compact silhouette, whole body.

### lich

Файл: `webapp/assets/guild/lich-v1.png`.

Subject: Keeper of buried names, a lich: ancient skeletal sorcerer in shredded deep indigo robes and tarnished silver funerary ornaments, skull face with dim cold violet eye flames, narrow bone staff in one hand and closed black ledger chained at belt. Suspended subtly with robe hem and feet in frame.

### dragon

Файл: `webapp/assets/guild/dragon-v1.png`.

Subject: Crimson dragon: mighty mature crimson dragon, FOUR legs and TWO leathery wings, thick plated neck, black branching horns, glowing ember throat, heavy muscular body, proud threatening stance. Wings partially folded to fit a compact full-body silhouette, tail fully in frame.

### ancient

Файл: `webapp/assets/guild/ancient-v1.png`.

Subject: Dragon of the last dawn: ancient majestic cataclysmic dragon with FOUR legs and TWO wings, weathered black obsidian scales veined with molten pale gold, crown of long jagged horns, ash-white mane along neck, wings with gold-torn membranes. Immense but compact readable whole-body silhouette, restrained internal glow, no scenery.

### deathlord

Файл: `webapp/assets/guild/deathlord-v1.png`.

Subject: King of nameless graves: towering skeletal undead monarch in weathered black regal plate, dark iron crown, torn sepulchral violet cape, large executioner sword resting diagonally downward in one hand, other skeletal hand clutching soul flame. Hollow sockets with faint violet light, elegant commanding pose. Entire body and crown.
