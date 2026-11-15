# Мимик — Голодное отражение

Способ: встроенный генератор изображений, редактирование по референсу.
Прозрачный фон, PNG. Программное удаление фона и перерисовка не применялись.

Референс пользователя: `C:/Users/Pikac/OneDrive/Изображения/Art/Ps/HW8LfhjXUAIVZXj.jpg`.

## Основной спрайт — `webapp/assets/mimic.png`

Full-body transparent-background battle sprite based on the central character in
the reference: a tall, slender, faceless humanoid mimic in a charcoal pinstripe
suit, pale shirt and grey tie, black inky tendril hair and very long blade-like
fingers. Preserve the elegant, unsettling silhouette, restrained magenta rim
light and small mirror shards. Three-quarter view facing LEFT toward the players.
Entire feet, hair and claws visible, isolated, sharp dark anime painterly game
art. No scenery, floor, lettering, signature, watermark or smoky halo.

## Финальная фаза — `webapp/assets/mimic_final.png`

Use the generated first sprite as the character reference. Preserve the same
suited faceless humanoid, left-facing orientation and inky hair. Final awakened
phase: wider, threatening arm pose, fragmented mirror plates at shoulders and
forearms, bright magenta fissures across the featureless face and gloves, long
claws. Keep the same identity and readable full-body game sprite silhouette.
Transparent background; entire feet and claws visible. No extra heads, wings,
scenery, text, watermark or smoky halo.

## Исходные результаты генерации

- `C:/Users/Pikac/.codex/generated_images/01a0290d-bff1-7480-9538-e6a0b5b63241/exec-048580de-2e3e-4348-a6d3-59d0dd1ac6c9.png`
- `C:/Users/Pikac/.codex/generated_images/01a0290d-bff1-7480-9538-e6a0b5b63241/exec-90366527-4678-4314-8016-4f604a7403eb.png`

## Фон — `webapp/assets/mimic_hall.png`

Режим: встроенный image_gen, новый непрозрачный фон по исходному арту пользователя.
Исходник результата сохранён без изменений:
`C:/Users/Pikac/.codex/generated_images/01a0290d-bff1-7480-9538-e6a0b5b63241/exec-4a5c596d-cf25-42cf-ad0d-b4c65745e009.png`.

Use case: stylized-concept. Asset type: landscape 16:9 illustrated battle background for a dark fantasy RPG, an EMPTY arena where game character sprites will be overlaid. Input image 1 is STYLE AND ENVIRONMENT REFERENCE only: use its charcoal hall of tilted tall mirrors, unsettling eye imagery, smoky shadows and hot magenta spectral reflections. Generate a new wide environment, NOT a crop of the image. A spacious abandoned hall of tall black-framed mirrors receding into darkness, angled cracked glass panels along the back wall and sides, a few unnatural reddish-magenta eyes looking from within the deepest mirror reflections. Polished dark stone floor across the bottom 35 percent, with subtle reflected pink light, shallow steps and scattered tiny glass fragments. Magenta wisps coil around the FAR edges of the floor and between mirrors; middle foreground remains unobstructed, readable and quiet for combat sprites. Sharp elegant dark anime painterly illustration like the supplied art, charcoal grey and dusty violet architecture, restrained vivid pink/magenta highlights, unsettling grandeur. Perspective from audience facing the arena, moderately low viewpoint, horizontal floor for characters to stand on. Important: no person, no humanoid silhouettes or central boss, no monsters standing on the floor, no suit or floating hands, no UI, no lettering, no signature or watermark. Preserve visible grey architectural detail rather than crushed pitch black. Full bleed opaque background.

## Музыка

Собственная процедурная композиция в `webapp/arena-audio`, без импортированных записей и внешнего музыкального генератора:

- `mimic` — «Чужая мелодия», 122 BPM.
- `mimic_stitched` — «Двойной отпечаток», 140 BPM.
- `mimic_original` — «Оригинал не нужен», 158 BPM.

Общий восьминотный хроматический мотив и его обратный ход, стеклянные аддитивные тембры, низкий бас, перкуссия, медные и синтетический хор. Четыре варианта аранжировки на 32 такта; во второй фазе вступает ответный голос, в третьей — плотный хор и ритм. В бою темы переключаются штатной единственной аудиосистемой, учитывают выключение звука и остановку приложения.
