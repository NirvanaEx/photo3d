# Звук: авторы и лицензии

Файл обязателен, а не вежливость: звуки шагов лежат под **CC-BY 3.0**, и она
требует указывать автора везде, где работа используется — включая релиз игры.
Убрать этот файл, оставив звуки, значит нарушить лицензию.

Если игра пойдёт наружу, эти же строки должны попасть в её титры или в экран
«О программе». Не в README репозитория — там их увидит разработчик, а не
игрок.

## Шаги — `steps/`

Набор [Footsteps on different surfaces](https://opengameart.org/content/footsteps-on-different-surfaces)
автора **congusbongus**, OpenGameArt, CC-BY 3.0. Он, в свою очередь, собран из
записей с freesound.org — исходные авторы ниже, по папкам:

| папка | откуда | автор | лицензия |
|---|---|---|---|
| `wood` | [footstep-wood.wav](https://freesound.org/people/swuing/sounds/38876/) | swuing | CC-BY 3.0 |
| `tile` | [footstep-concrete.wav](https://freesound.org/people/swuing/sounds/38873/), [Squeaky footstep.wav](https://freesound.org/people/ceberation/sounds/235524/) | swuing, ceberation | CC-BY 3.0 |
| `boots` | [footstep-concrete.wav](https://freesound.org/people/swuing/sounds/38873/) | swuing | CC-BY 3.0 |
| `grass` | [footstep-grass.wav](https://freesound.org/people/swuing/sounds/38874/) | swuing | CC-BY 3.0 |
| `metal` | [boots on aluminum ladder 01](https://freesound.org/people/Eelke/sounds/462598/) | Eelke | CC-BY 3.0 |
| `water` | [Water Footsteps](https://freesound.org/people/EminYILDIRIM/sounds/608663/), footstep-concrete.wav | EminYILDIRIM, swuing | CC-BY 3.0 |
| `gravel` | [Gravel Footsteps](https://freesound.org/people/Ali_6868/packs/21608/) | Ali_6868 | **CC0** — упоминания не требует |

Оригинальные `license.txt` оставлены внутри каждой папки нетронутыми: это
первоисточник, и переписывать его пересказом незачем.

## Фон помещения — `room_tone.wav`

Синтезирован `scripts/make_sounds.py`, лицензия не нужна. Правится числами
там же: тембр комнаты собран из трёх низких резонансов, гул ламп — 100 Гц
(вторая гармоника сети, именно её слышно от дросселей).
