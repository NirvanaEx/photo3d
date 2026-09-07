# Класс на закате · v2 — класс, коридор и задний двор

Связанная прогулка от первого лица: после уроков, сентябрь, 17:42.
Из класса можно открыть любую из двух дверей, пройти по коридору,
открыть торцевую дверь и выйти во двор. Все переходы в одной сцене.

## Открыть

Игровые модели, текстуры и Blender-исходники сохранены через Git LFS.
После клонирования репозитория выполните `git lfs install` и `git lfs pull`,
затем откройте `game/project.godot`: Godot пересоздаст локальный кэш импорта.
Веса генеративных моделей, входные фотографии и служебные кэши в Git не входят.

- Blender: `data/output/loc_classroom_v2/school_v2.blend`.
- Игра: ярлык «photo3d — игры» → «Класс на закате · v2».
- Сцена Godot: `game/scenes/classroom_v2.tscn`.
- Игровая геометрия: `school_v2.glb`, `school_door.glb`, `school_tree.glb`
  в `game/assets/models/`; размещение дверей и деревьев в `game/assets/school_layout.json`.

Текстуры упакованы в Blender-файл; двери стоят в настоящих проёмах.
Сохранён редактируемый исходник с отдельными объектами. Старый v1 сохранён,
а предыдущая v2 скопирована в `data/output/loc_classroom_v2_before_expansion`.

## Масштаб и управление

Рост 1,75 м, глаза 1,64 м, вертикальный угол обзора 56°.
Парта 70 × 50 см, высота 75 см; сиденье стула 45 см.
Класс 7,4 × 9 м, потолок 3 м; коридор шириной 3,18 м.
Ходьба 1,6 м/с, бег 3,65 м/с, плавный разгон и сдержанное движение камеры.

Клик захватывает мышь. WASD — ходьба, мышь — взгляд, Shift — бег,
E — открыть/закрыть дверь или осмотреть предмет, Ctrl — присесть,
Space — прыжок. Esc освобождает мышь, повторный Esc закрывает сцену.
Дверь останавливается при открывании на игрока и отходит назад, если
попытаться закрыть её на игрока. Закрытая дверь физически перекрывает проход.

## Звук

Четыре покрытия: дерево, плитка, трава и каменные дорожки.
Шаги выбираются по физической поверхности, с отдельными вариантами для бега,
небольшим изменением громкости и высоты; подряд не повторяется один сэмпл.
Ритм зависит от пройденного расстояния. При упоре в стену шаги прекращаются;
приземление имеет отдельный акцент. Двери звучат из положения створки.

В коридоре сильнее реверберация, снаружи меньше эха и отчётливее птицы.
Открытая дверь во двор пропускает больше внешнего звука в коридор.
Использовано 60 OGG-файлов; исходники, авторы и условия распространения —
`game/assets/audio/school/CREDITS.md`. Сборка и нормализация:
`scripts/build_school_audio.py`. Короткий пример без обработки помещений:
`data/output/loc_classroom_v2/school_audio_demo.wav`.

## Изображения и проверка

В `data/output/loc_classroom_v2/`:

- `school_classroom.png`, `school_corridor.png`, `school_garden.png` — Cycles.
- `school_game_classroom.png`, `school_game_corridor.png`,
  `school_game_garden.png`, `school_game_doorway.png` — реальные кадры Godot.
- `school_probe.json` — проверки движения, дверей, поверхностей и акустики.
- `school_game_review.json` — измерения четырёх фиксированных игровых ракурсов.

Cycles и Godot используют разные системы освещения. Godot: Forward+, SDFGI,
мягкие тени, SSAO, SSIL, SSR и слабая объёмная дымка. В четырёх проверенных
ракурсах при 1600 × 1000 на RTX 3060 достигнут установленный предел 60 FPS.
Это не измерение минимальной частоты кадров всей прогулки.

Физический прогон проверяет 33 условия, включая путь класс → коридор → двор
→ класс, блокировку закрытой дверью и безопасное закрывание, ходьбу и бег,
приземление, автоматический выбор покрытия и смену акустики.

## Пересобрать

Из корня photo3d; Blender 4.5.9 и Godot 4.7.1:

```powershell
python scripts/fetch_school_assets.py
& 'C:/tools/blender-4.5.9-windows-x64/blender.exe' -b -P pipeline/blender/prepare_school_tree.py
python scripts/build_school_audio.py
& 'C:/tools/blender-4.5.9-windows-x64/blender.exe' -b -P pipeline/blender/school_expansion.py
& 'C:/tools/Godot/Godot_v4.7.1-stable_win64_console.exe' --headless --editor --import --path game
```

Сборка использует сохранённый исходник до расширения, кэш исходных текстур
класса и скачанные записи звуков. Повторно завершить материалы, размещение,
рендеры и экспорт уже сохранённой школы:

```powershell
& 'C:/tools/blender-4.5.9-windows-x64/blender.exe' -b -P pipeline/blender/finish_school.py
```

В игровой копии статическая геометрия объединена по материалам: 57 мешей,
5 групп поверхностей столкновения. Дерево сокращено до примерно 121 тысяч
треугольников и размещено семью экземплярами с общими мешами. Двери имеют
отдельные шарниры и физические тела. Скрипты v2 изолированы в
`game/scripts/school/`, общий контроллер старых сцен не заменён.

Проверки:

```powershell
& 'C:/tools/Godot/Godot_v4.7.1-stable_win64_console.exe' --headless --fixed-fps 60 --path game --script res://tools/school_probe.gd -- D:/Projects/Personal/photo3d/data/output/loc_classroom_v2/school_probe.json
& 'C:/tools/Godot/Godot_v4.7.1-stable_win64_console.exe' --path game --resolution 1600x1000 --max-fps 60 --script res://tools/school_review.gd -- D:/Projects/Personal/photo3d/data/output/loc_classroom_v2
```

## Ассеты

Основа класса — существующий photo3d. Коридор, двери, лавки, двор,
фурнитура, вещи и надписи созданы геометрией в Blender-скриптах проекта.

Powered by [Poly Haven](https://polyhaven.com/):
[Tree Small 02](https://polyhaven.com/a/tree_small_02),
[Terrazzo Tiles](https://polyhaven.com/a/terrazzo_tiles),
[Leafy Grass](https://polyhaven.com/a/leafy_grass),
[Precast Stone Paving](https://polyhaven.com/a/precast_stone_paving).
Также используются исходные материалы класса из локального кэша Poly Haven.
[Лицензия материалов и дерева — CC0](https://polyhaven.com/license).
Список записей звука и лицензий сохранён отдельно в CREDITS рядом со звуками.
