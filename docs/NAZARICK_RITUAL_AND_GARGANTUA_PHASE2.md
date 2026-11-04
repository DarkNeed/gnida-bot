# Виктим, обратная связь попаданий и второй облик Гаргантюа

Локальное демо: http://127.0.0.1:8157/nazarick-dungeon-review. Не опубликовано.

- Ритуал: 45 секунд с подготовкой; 12 последовательностей в шести частях.
  Цепи → рои печатей → рассечения → проходы между стенами → орбитальные печати
  → сочетание угроз в финале. Окна предупреждения и контроль скорости сохранены.
  Вес мелкого снаряда 0,085, рассечения 0,18, волны 0,22 относительно урона навыка.
- Блок: 40 отдельных угроз с меняющимся ритмом, направлениями, волнами и ложными
  поднятиями. Длительность та же. После испытания печать завершает бой как раньше.
- Трансляция остаётся временной, без хранения повторов; допустимая длительность
  ограничена 60 секундами и размером пакета 512 КБ для длинного испытания.
- Звук проигрывается на новых контактах с положительным уроном: qte_hit / critical
  для атаки, qte_hurt для защиты. Перерисовка не повторяет звук, безуронный блок
  молчит; близкие контакты сгруппированы ограничением 90 мс. Настройки громкости,
  mute и состояние скрытой страницы сохраняют действие. Web Audio разблокируется
  реальным касанием или клавишей; отказ звука не ломает бой.
- Гаргантюа меняет спрайт при переходе во вторую фазу. Размер art увеличен с 265 до
  370 px на ПК и с 200 до 280 px на телефоне; исходные пропорции не растягиваются.

## Проверка

- 96 целевых Python-тестов: стражи, фазы, очередь, ресурсы, совместные атаки,
  просмотр, длительность ритуала и его завершение.
- 19 тестов звука и отдельная проверка обратной связи: новый контакт, крит,
  ограничение частоты, отсутствие звука травмы при точном безуронном блоке.
- Реальный браузер: все 45 секунд ритуала, шесть этапов, события звука,
  завершение боя после серверной проверки. Ошибок JavaScript не получено.
- Обе фазы Гаргантюа проверены при ширине 1100 и 390 px: новый спрайт крупнее,
  горизонтального переполнения страницы нет. Скриншоты находятся в
  `output/nzd-long-ritual-review/`.
- Это целевые проверки, а не заявление о прохождении всего исторического набора
  тестов проекта. Субъективная сложность оставлена для проверки игроком в демо.

## Изображение

Сгенерировано встроенным image_gen с текущим спрайтом как референсом. Исходники
первой фазы не изменены.

- Исходник: `art/nazarick-dungeon-v2/source/gargantua-phase2-v1.png`.
- Игровая копия: `webapp/assets/nazarick-dungeon-v2/gargantua-phase2-v1.png`.
- Уменьшение с сохранением прозрачности: `tools/prepare_guardian_revision.py
  --variant gargantua-phase2-v1`. Программное уменьшение ранее разрешено пользователем.

Финальный промпт (встроенный инструмент, не CLI):

Use case: stylized-concept. Asset type: transparent full-body dark fantasy 2D RPG
boss sprite, phase TWO of the exact stone colossus shown in reference image 1.
Reference image 1 is identity/style reference, keep the same grey-olive rough
stone, squat gigantic build, tiny recessed head, enormous fists, red eyes and
branching crimson V-shaped chest fissures. Make this recognizable second phase
MUCH more menacing: shoulders lifted and hunched forward, one huge stone fist
raised ready to smash, the other braced down with claw-like stone fingers, wider
brutal silhouette, larger jagged broken shoulder plates and exposed blazing
deep-red fissures across chest, arms and face, concentrated bright scarlet eyes
and darker stone shadows. Threat comes from mass and violent attacking posture,
not jewelry or fantasy armor. Slight three-quarter view, visibly facing and
attacking toward the RIGHT of the image (the game mirrors this left toward
heroes). Entire body including all hands and feet visible, small transparent
margin all around. Match the crisp hand-painted cutout game-art treatment of
the reference, not pixel art, not photorealistic. Genuine transparent alpha
background with clean silhouette, NO fog, smoke, surrounding glow halo, ground,
pedestal, environment, text, symbols, runes, wings, weapons or extra characters.
Preserve the character identity but clearly distinguish the unleashed phase by
posture, stone damage and intensified internal crimson light.
