# AbletonMCP Roadmap

Estado actual: **39 herramientas** en 8 modulos, conexion resiliente con retry/ping, cache, PatternEngine con 1105 patrones MIDI reales, browser tools completos, audio clip support.

Idea paralela: plugin JUCE para generar loops de ejemplo.

---

## Completado

### v1.0 — Rewrite (2026-03-17)
- [x] 67 tools → 39 tools, arquitectura producer-focused
- [x] 5 production tools (create_beat/bassline/melody/chords/pad) — workflow completo en 1 llamada
- [x] 7 browser tools — search, browse, load, build_drum_rack, list_user_folders
- [x] PatternEngine reemplaza Markov (search → pick → adapt → vary)
- [x] 11 estilos de drums con 3-4 variaciones + humanizacion
- [x] Chord progressions con Roman numeral parsing (9 presets)

### v1.1 — Audio clips y user library (2026-03-18)
- [x] `create_audio_clip` — cargar loops en clip slots especificos (Live 12+)
- [x] `get_audio_clip_info` / `set_clip_pitch` / `set_clip_warp` — warp, transpose, gain
- [x] Key detection desde filename (`_parse_key_from_name`, `_transpose_semitones`)
- [x] BPM detection desde filename (`_parse_bpm_from_name`)
- [x] `list_user_folders` / `browse_folder` — navegacion de libreria del usuario
- [x] `build_drum_rack` / `load_sample_to_drum_pad` — drum kits custom

### v1.2 — Resiliencia y fixes criticos (2026-03-21)
- [x] Fix coercion `str` ← `int` — `Union[str, int]` en sound/query params
- [x] `_try_load_instrument` busca 2 niveles (encuentra Kit-909 en Drums/Drum Rack/)
- [x] `search_browser` con retry automatico + timeout configurable (30s)
- [x] Remote Script: `.is_folder` en vez de `bool(children)` — elimina enumeracion lazy
- [x] Remote Script: timing guard 10s, skip subtrees pesados, max_depth 6
- [x] `connection.py`: auto-retry en `send_command`, `ping()` health check, env vars
- [x] Remote Script: recv timeout, TCP keepalive/NODELAY, buffer cap, `_handle_client` rewrite
- [x] PreToolUse hook (`.claude/hooks/ableton-pretool.mjs`) — corrige tipos + valida enums
- [x] `.mcp.json` configurado para Claude Code
- [x] `install.sh` actualizado (sin Markov, busca User Remote Scripts)

---

## Siguiente — v2.0 (IA creativa)

### P0 — Random loop generator
Herramienta que genera ideas musicales rapidamente cargando LOOPS (audio, no MIDI) de la libreria del usuario.
- [ ] `generate_idea(style, artists, key)` — Elige loops aleatorios de user folders por keywords
- [ ] Carga loops en audio tracks separados
- [ ] Detecta key desde filename y transpone para compatibilidad
- [ ] Ajusta niveles automaticamente
- [ ] Mezcla artistas: "kick de Sidney Charles, bass de Matt Tolfrey, synth de Cuartero"
- Base: `list_user_folders` + `browse_folder(filter="loop")` + `create_audio_clip` + `set_clip_pitch`

### P0 — Key/note awareness global
- [ ] **Deteccion de tonalidad (Krumhansl-Schmuckler)** — Analizar notas MIDI para detectar clave/escala. ~100 lineas.
- [ ] **Key tracking en sesion** — Mantener la key actual de la sesion para transponer loops/clips automaticamente
- [ ] **Validacion de compatibilidad** — Al cargar un loop, verificar si su key es compatible y sugerir transposicion

### P1 — Templates y variaciones
- [ ] **Templates por genero** — `create_template("trap")` crea estructura completa de tracks (nombres, volumenes, panning). Generos: trap, house, lo-fi, rock, ambient, reggaeton, dnb, jazz. ~200 lineas.
- [ ] **Variaciones de clips** — Dado un clip, generar variaciones: transponer, invertir, retrogradar, desplazar ritmo, simplificar, ornamentar. ~150 lineas.
- [ ] **Sugerencias de mezcla** — Clasificar tracks por rol y sugerir volumen/panning/sends segun genero. ~250 lineas.

### P2 — Analisis musical
- [ ] **Analisis ritmico** — Detectar grid, swing ratio, densidad, syncopation desde notas MIDI. ~200 lineas.
- [ ] **Clasificacion de genero** — Heuristica basada en tempo, nombres, time signature, num tracks. ~150 lineas.

---

## v2.1 — Nuevos comandos de Ableton (requieren cambios en Remote Script)

### Automation (Session clips)
- [ ] **Crear automation envelope** — `create_automation(track, clip, device, param, breakpoints)`. Usa `clip.automation_envelope(param)` + `insert_step()`. Solo session clips.
- [ ] **Leer automation** — `get_automation(track, clip, device, param, time)`. Usa `value_at_time()`.
- [ ] **Limpiar automation** — `clear_automation` / `clear_all_automation`. Usa `clip.clear_envelope()`.

### Arrangement view
- [ ] **Leer clips de arrangement** — `get_arrangement_clips(track)`. Usa `track.arrangement_clips`.
- [ ] **Crear clips en arrangement** — MIDI y audio.
- [ ] **Duplicar clip a arrangement** — `duplicate_clip_to_arrangement(track, clip, destination_time)`.

### Warp markers
- [ ] `add_warp_marker()`, `move_warp_marker()`, `remove_warp_marker()`, `get_warp_markers()`.

### Return tracks
- [ ] **Crear/borrar return track** — `song.create_return_track()` / `song.delete_return_track()`.
- [ ] **Routing** — `set_track_routing(track, input_type, output_type)`.

### Groove pool
- [ ] **Leer grooves** — `get_groove_pool()`.
- [ ] **Asignar groove a clip** — `set_clip_groove(track, clip, groove_index)`.
- [ ] **Ajustar groove** — timing, quantization, velocity, random amounts.

---

## v2.2 — Developer Experience

- [ ] **Mock in-process** — `MockAbletonConnection` para tests sin Ableton corriendo. ~500-800 lineas.
- [ ] **Fixtures de pytest** — sesion vacia, sesion con tracks/clips, estados de error. ~100 lineas.
- [ ] **Tests de tool modules** — Tests para los 8 modulos usando el mock. ~400 lineas.
- [ ] **Structured logging (JSON)** — JSON formatter, loggers por modulo, niveles via env vars. ~50 lineas.
- [ ] **Protocol framing** — Length-prefix para robustez. Backward-compatible. ~100 lineas por lado.

---

## No viable (confirmado)

- ~~Export/render audio~~ — **NO existe en la API**. Solo via GUI.
- ~~Leer MIDI mappings del usuario~~ — **NO expuesto**. Solo mappings del control surface propio.
- ~~Automation en arrangement clips~~ — **API devuelve None** explicitamente.
- ~~Mover clips en arrangement~~ — **start_time es read-only**.
- ~~WebSocket en vez de TCP~~ — Python del Remote Script no tiene WebSocket.
- ~~Connection pooling~~ — Llamadas MCP secuenciales, overhead minimo.
- ~~Plugin system (Remote Script)~~ — Ableton carga un solo `__init__.py`.
- ~~Variaciones con Markov~~ — Reemplazado por PatternEngine con 1105 patrones reales.

---

## Prioridades

| Prioridad | Feature | Impacto |
|-----------|---------|---------|
| **P0** | Random loop generator | Idea generation instantanea desde user library |
| **P0** | Key awareness global | Base para toda la IA contextual musical |
| **P1** | Templates por genero | Setup completo de proyecto en 1 llamada |
| **P1** | Variaciones de clips | Workflow de produccion esencial |
| **P1** | Automation (session) | Separa prototipo de produccion real |
| **P2** | Sugerencias de mezcla | Muy util para mixing |
| **P2** | Arrangement view | Session + Arrangement = completo |
| **P2** | Return tracks + routing | Mezcla profesional |
| **P2** | Mock + tests | Permite iterar rapido sin Ableton |
| **P3** | Warp markers | Control fino de audio |
| **P3** | Groove pool | Nicho pero interesante |
| **P3** | Structured logging | Debugging mas facil |
