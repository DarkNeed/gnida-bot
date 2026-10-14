# Approved RPG sprites

The four initial character designs were approved by the user on 2026-10-14.
Separate RPG branch designs have not been approved: all nine branches reuse their base class skin.

Generated with the built-in imagegen tool using the approved four-character sheet as the edit target. No fallback CLI or external image model was used.
Original PNGs are preserved locally in `art/rpg-v1/`; compact production exports in this directory are tracked by Git.
`tools/prepare_rpg_sprites.py` applies the previously authorized alpha-only halo cleanup, preserves visible RGB, fits each whole character inside 464×720 and exports a transparent 512×768 canvas with a consistent bottom anchor. No RGB colour keying.

## Prompt set

Production files: [warrior.png](warrior.png), [mage.png](mage.png),
[priest.png](priest.png), [hunter.png](hunter.png).

### warrior

Use case: background-extraction. Input image 1: approved four-character concept sheet, EDIT TARGET. Extract ONLY the FIRST character on the FAR LEFT, the armored WARRIOR with short dark hair, dark red cape, battered steel shield in left hand and sword in right hand. Output ONE full-body game sprite in a portrait canvas on a truly transparent background. Keep the exact same identity, face, armor, red cape, sword, shield, stance, illustration style, linework and colors from the approved sheet. Remove all other characters, the blue-gray backdrop, ground shadow and surrounding scene. Do not redesign or introduce new props. Recenter the isolated character with generous transparent padding, leave all hair, cape edges, sword, shield and both boots completely visible. No floor, no cloud, no glow, no halo, no text, no watermark. This is the production cutout of an already approved design, not a new concept.

### mage

Use case: background-extraction. Input image 1: approved concept sheet, EDIT TARGET. Extract ONLY the SECOND figure from the LEFT: the adult dark-haired male MAGE with glasses, long black and violet layered robes with gold trim, large open book and a concentrated blue orb of pure mana held over his other hand. Preserve his exact identity, face, outfit, expression, pose, props, crisp ink drawing and colors. Output ONE full-body game sprite on a genuinely transparent background, portrait canvas. Remove the other three people, backdrop and floor shadow. Do not redesign any character feature or change the position of hands and legs. Recenter with transparent margins around hair, robes, both shoes, mana orb and book; show the entirety of the character. The orb is a compact defined blue object: no diffuse glow or haze outside it. No surrounding particles, floor, shadow, colored vignette or background gradient. No text or watermark. Production cutout of the approved design, not new artwork.

### priest

Use case: background-extraction. Input image 1: approved four-character sheet, EDIT TARGET. Extract ONLY the THIRD figure from the LEFT: the adult blond PRIEST in long white and wine-red ecclesiastical robes with gold embroidery, a white hood, small golden light sigil over the raised hand and a tall golden sacred staff with a circular sun-like ornament. Preserve the exact identity, androgynous adult face, costume, hair, proportions, pose, staff, colors and drawn ink style. Output ONE full-body production game sprite on a genuinely transparent background in a portrait canvas. Remove the other three characters, all backdrop and floor shadow; do not invent new details, new poses or redesign the character. Center this priest with transparent padding around the entire staff top, outer sleeves, skirt hem and both shoes. The hand sigil stays a compact golden object; remove diffuse lighting haze outside it. No floor, cast shadow, mist, vignette, gradient backdrop, labels or watermark.

### hunter

Use case: background-extraction. Input image 1: approved concept sheet, EDIT TARGET. Extract ONLY the FOURTH figure at the FAR RIGHT, the original adult gothic HUNTER in a battered feathered dark hat and long tattered leather coat, holding an ornate flintlock pistol upward in one hand and a compact saw-like transforming blade lowered in the other. Keep exactly this approved character's face, hat, feathers, posture, body proportions, outfit, leather textures, weapon designs, colors and crisp dark anime illustration style. Output ONE full-body game sprite on truly transparent background in a portrait canvas. Remove the other three people, blue-gray background and floor shadow. Recenter with transparent padding around the full raised gun barrel, feathers, coat edges, blade and BOTH boots. Do not invent new character features, redesign anything, or turn the hunter into a different named character. No scenery, ground, glow, halo, vignette, gradient backdrop, captions or watermark. A production cutout of an approved character.
