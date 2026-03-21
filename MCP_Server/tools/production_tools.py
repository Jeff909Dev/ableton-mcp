"""Production workflow tools for AbletonMCP.

These are the primary tools for music creation. Each tool handles a complete
workflow: creating a track, generating a pattern, and writing it to Ableton.
"""
import json
import logging
import random
from typing import Union
from MCP_Server.tools.pattern_generator import (
    generate_from_patterns,
    generate_humanized_drums,
    NOTE_NAMES,
    _note_name_to_pitch_class,
)

logger = logging.getLogger("AbletonMCPServer")

# ---------------------------------------------------------------------------
# Chord theory constants for create_chords
# ---------------------------------------------------------------------------

CHORD_INTERVALS = {
    "major": [0, 4, 7],
    "minor": [0, 3, 7],
    "dim": [0, 3, 6],
    "aug": [0, 4, 8],
    "maj7": [0, 4, 7, 11],
    "min7": [0, 3, 7, 10],
    "dom7": [0, 4, 7, 10],
    "sus2": [0, 2, 7],
    "sus4": [0, 5, 7],
    "add9": [0, 4, 7, 14],
    "power": [0, 7],
}

COMMON_PROGRESSIONS = {
    "pop": "I-V-vi-IV",
    "jazz": "ii-V-I",
    "blues": "I-I-I-I-IV-IV-I-I-V-IV-I-V",
    "rock": "I-IV-V-V",
    "sad": "vi-IV-I-V",
    "epic": "I-V-vi-iii-IV-I-IV-V",
    "reggaeton": "i-iv-VII-v",
    "andalusian": "iv-III-II-I",
    "house": "i-VI-III-VII",
}

_MAJOR_SCALE_DEGREES = {
    "I": (0, "major"), "ii": (2, "minor"), "iii": (4, "minor"),
    "IV": (5, "major"), "V": (7, "major"), "vi": (9, "minor"),
    "vii": (11, "dim"),
}

_MINOR_SCALE_DEGREES = {
    "i": (0, "minor"), "ii": (2, "dim"), "III": (3, "major"),
    "iv": (5, "minor"), "v": (7, "minor"), "VI": (8, "major"),
    "VII": (10, "major"),
}

_ROMAN_NUMERAL_SEMITONES = {
    "i": 0, "ii": 2, "iii": 4, "iv": 5, "v": 7, "vi": 9, "vii": 11,
}


def _parse_roman(numeral, key_pc, mode):
    """Parse a Roman numeral into (root_pitch_class, chord_quality)."""
    numeral = numeral.strip()
    if not numeral:
        raise ValueError("Empty Roman numeral")
    is_dim = numeral.endswith("\u00b0") or numeral.endswith("o")
    clean = numeral.rstrip("\u00b0o")
    is_upper = clean[0].isupper()

    degree_map = _MINOR_SCALE_DEGREES if mode == "minor" else _MAJOR_SCALE_DEGREES
    if numeral in degree_map:
        offset, quality = degree_map[numeral]
    elif clean in degree_map:
        offset, quality = degree_map[clean]
    else:
        lower = clean.lower()
        if lower not in _ROMAN_NUMERAL_SEMITONES:
            raise ValueError("Unknown numeral: {}".format(numeral))
        offset = _ROMAN_NUMERAL_SEMITONES[lower]
        quality = "major" if is_upper else "minor"

    if is_dim:
        quality = "dim"
    return (key_pc + offset) % 12, quality


def _generate_chord_notes(key, mode, progression, octave, bars):
    """Generate MIDI notes for a chord progression."""
    prog_str = COMMON_PROGRESSIONS.get(progression, progression)
    numerals = [n.strip() for n in prog_str.split("-") if n.strip()]
    if not numerals:
        return [], prog_str, []

    key_pc = _note_name_to_pitch_class(key)
    beats_per_chord = (bars * 4.0) / len(numerals)

    notes = []
    chord_names = []
    for i, numeral in enumerate(numerals):
        root_pc, quality = _parse_roman(numeral, key_pc, mode)
        intervals = CHORD_INTERVALS.get(quality, [0, 4, 7])
        base_midi = (octave + 1) * 12 + root_pc

        chord_midi = [base_midi + iv for iv in intervals]
        chord_midi = [n for n in chord_midi if 0 <= n <= 127]

        start = i * beats_per_chord
        duration = beats_per_chord * 0.95

        for pitch in chord_midi:
            notes.append({
                "pitch": pitch,
                "start_time": round(start, 4),
                "duration": round(duration, 4),
                "velocity": random.randint(75, 95),
                "mute": False,
            })

        root_name = NOTE_NAMES[root_pc]
        chord_names.append("{} {}".format(root_name, quality))

    return notes, prog_str, chord_names


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register(mcp, get_connection, cache):
    """Register production workflow tools."""

    async def _setup_track(conn, name, bars, clip_index=0):
        """Create a MIDI track with a clip. Returns (track_index, clip_length)."""
        result = await conn.send_command("create_midi_track", {"index": -1})
        track_index = result.get("index", 0)
        await conn.send_command("set_track_name", {
            "track_index": track_index, "name": name,
        })
        clip_length = bars * 4
        await conn.send_command("create_clip", {
            "track_index": track_index, "clip_index": clip_index, "length": clip_length,
        })
        return track_index, clip_length

    async def _try_load_instrument(conn, track_index, query, category="all"):
        """Load an instrument by browsing category folders (NOT recursive search).

        Uses get_browser_items_at_path which lists children at one level —
        much faster than search_browser which walks the entire tree recursively.

        Searches up to 2 levels deep. For drums, tries known subpaths where
        kits actually live (Drums/Drum Rack, Drums/Drum Hits).
        """
        # Map category to browsable paths — include known subpaths where
        # loadable items actually live (they're rarely at the top level)
        if category == "drums":
            paths = ["Drums/Drum Rack", "Drums/Drum Hits", "Drums"]
        elif category == "sounds":
            paths = ["Sounds"]
        elif category == "instruments":
            paths = ["Instruments"]
        elif category == "audio_effects":
            paths = ["Audio Effects"]
        else:
            paths = ["Drums/Drum Rack", "Drums/Drum Hits", "Drums",
                     "Sounds", "Instruments"]

        query_lower = str(query).lower()

        def _find_match(items):
            """Return the first loadable item matching query, or None."""
            for item in items:
                name = item.get("name", "")
                if query_lower in name.lower() and item.get("is_loadable") and item.get("uri"):
                    return item
            return None

        for browse_path in paths:
            try:
                result = await conn.send_command("get_browser_items_at_path", {
                    "path": browse_path,
                })
                items = result.get("items", [])

                # Level 1: check items at this path
                match = _find_match(items)
                if match:
                    await conn.send_command("load_browser_item", {
                        "track_index": track_index, "item_uri": match["uri"],
                    })
                    return {"loaded": True, "name": match["name"], "uri": match["uri"]}

                # Level 2: descend into subfolders that are non-loadable folders
                for item in items:
                    if item.get("is_folder") and not item.get("is_loadable"):
                        subfolder = "{}/{}".format(browse_path, item["name"])
                        try:
                            sub_result = await conn.send_command(
                                "get_browser_items_at_path", {"path": subfolder},
                            )
                            sub_match = _find_match(sub_result.get("items", []))
                            if sub_match:
                                await conn.send_command("load_browser_item", {
                                    "track_index": track_index,
                                    "item_uri": sub_match["uri"],
                                })
                                return {"loaded": True, "name": sub_match["name"],
                                        "uri": sub_match["uri"]}
                        except Exception:
                            continue
            except Exception as exc:
                logger.warning("Error browsing '%s' for '%s': %s", browse_path, query, exc)

        return {
            "loaded": False,
            "query": query,
            "reason": "No match for '{}' in {}".format(query, paths),
            "suggestion": "Use browse_folder to navigate categories manually.",
        }

    async def _write_notes(conn, track_index, clip_index, notes, clip_name):
        """Write notes to a clip and name it."""
        if notes:
            await conn.send_command("add_notes_to_clip", {
                "track_index": track_index, "clip_index": clip_index, "notes": notes,
            })
        await conn.send_command("set_clip_name", {
            "track_index": track_index, "clip_index": clip_index, "name": clip_name,
        })

    # Style → default drum search query
    # These are broad terms that match Ableton's built-in content
    _DRUM_DEFAULTS = {
        "house": "Kit-909", "techno": "Kit-909", "rock": "Kit-Acoustic",
        "hiphop": "Kit-Hip Hop", "trap": "Kit-808", "dnb": "Kit-Breakbeat",
        "reggaeton": "Kit-Latin", "bossa_nova": "Kit-Brush",
        "jazz_swing": "Kit-Jazz", "funk": "Kit-Funk", "basic": "Drum Rack",
    }

    @mcp.tool()
    async def create_beat(
        style: str = "house",
        bars: int = 4,
        sound: Union[str, int] = "",
        track_index: int = -1,
        clip_index: int = 0,
    ) -> str:
        """Create a drum beat with pattern and sound on a track.

        Creates a MIDI track, tries to load a drum kit from Ableton's built-in
        browser, generates a drum pattern, and writes it to a clip.

        Only searches built-in content. When the user wants samples from their
        own library (artist packs, custom folders), do NOT use this tool.
        Instead use list_user_folders + browse_folder + load_sample_to_drum_pad
        to build a custom kit from the user's samples.

        Styles: house, techno, rock, hiphop, trap, dnb, reggaeton, bossa_nova,
        jazz_swing, funk, basic. Each call generates a different variation.

        Args:
            style: Drum style. Default "house".
            bars: Number of bars (1-16). Default 4.
            sound: Search term for built-in drum kits (e.g. "909", "808").
                Do not pass user library content here.
            track_index: Track to write to. -1 = create new track (default).
            clip_index: Clip slot to use (default 0).
        """
        try:
            sound = str(sound) if sound else ""
            bars = max(1, min(16, bars))
            conn = await get_connection()
            session = await conn.send_command("get_session_info")
            tempo = session.get("tempo", 120)

            if track_index == -1:
                track_name = "{} Beat".format(style.title())
                track_index, _ = await _setup_track(conn, track_name, bars, clip_index)
            else:
                await conn.send_command("create_clip", {
                    "track_index": track_index, "clip_index": clip_index,
                    "length": bars * 4,
                })

            # Try to load drum kit FIRST (so the track has sound)
            drum_query = str(sound) if sound else _DRUM_DEFAULTS.get(style, "Drum Rack")
            instrument = await _try_load_instrument(conn, track_index, drum_query, "drums")

            notes = generate_humanized_drums(style=style, bars=bars)
            if not notes:
                cache.invalidate_all()
                return json.dumps({
                    "error": "Unknown style: {}. Options: house, techno, rock, hiphop, "
                             "trap, dnb, reggaeton, bossa_nova, jazz_swing, funk, basic".format(style),
                })

            clip_name = "{} {}bar".format(style.title(), bars)
            await _write_notes(conn, track_index, clip_index, notes, clip_name)
            cache.invalidate_all()

            result = {
                "status": "ok",
                "track_index": track_index,
                "clip_index": clip_index,
                "style": style,
                "bars": bars,
                "tempo": tempo,
                "notes_count": len(notes),
                "instrument": instrument,
            }
            if not instrument.get("loaded"):
                result["action_needed"] = (
                    "No drum kit was loaded — the track has MIDI notes but NO SOUND. "
                    "You must load a drum instrument: use search_browser to find a kit, "
                    "then load_browser_item to load it. Or use list_user_folders + "
                    "browse_folder + load_sample_to_drum_pad to build a custom kit."
                )
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error creating beat: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def create_bassline(
        key: str = "C",
        bars: int = 4,
        sound: Union[str, int] = "",
        track_index: int = -1,
        clip_index: int = 0,
    ) -> str:
        """Create a bassline from real bass patterns in the library.

        Creates a MIDI track, loads a bass synth (e.g. Analog, Wavetable),
        picks a real bass pattern matched to the session tempo and key,
        and writes to a clip.

        Bass synths generate their own sound — no samples needed. This tool
        searches Ableton's built-in instruments. If you need a specific
        bass sound from a user sample pack, use the browser tools instead:
        search_browser + load_browser_item to load the specific instrument.

        Args:
            key: Musical key (e.g. "C", "F#", "Am", "Bb"). Default "C".
            bars: Number of bars (1-16). Default 4.
            sound: Search term for BUILT-IN bass presets (e.g. "Analog",
                "Sub Bass", "Acid Bass"). Not for user sample packs.
            track_index: Track to write to. -1 = create new track (default).
            clip_index: Clip slot to use (default 0).
        """
        try:
            sound = str(sound) if sound else ""
            bars = max(1, min(16, bars))
            conn = await get_connection()
            session = await conn.send_command("get_session_info")
            tempo = session.get("tempo", 120)

            if track_index == -1:
                track_index, _ = await _setup_track(conn, "Bass", bars, clip_index)
            else:
                await conn.send_command("create_clip", {
                    "track_index": track_index, "clip_index": clip_index,
                    "length": bars * 4,
                })

            # Load instrument first
            bass_query = str(sound) if sound else "Bass"
            instrument = await _try_load_instrument(conn, track_index, bass_query, "sounds")

            notes = generate_from_patterns(category="bass", key=key, bars=bars, bpm=tempo)
            if not notes:
                cache.invalidate_all()
                return json.dumps({"error": "Failed to generate bass pattern"})
            notes.sort(key=lambda n: (n["start_time"], n["pitch"]))

            clip_name = "Bass {} {}bar".format(key, bars)
            await _write_notes(conn, track_index, clip_index, notes, clip_name)
            cache.invalidate_all()

            result = {
                "status": "ok",
                "track_index": track_index,
                "clip_index": clip_index,
                "key": key,
                "bars": bars,
                "tempo": tempo,
                "notes_count": len(notes),
                "instrument": instrument,
            }
            if not instrument.get("loaded"):
                result["action_needed"] = (
                    "No bass instrument was loaded — the track has MIDI notes but NO SOUND. "
                    "Load a synth instrument: use search_browser('Bass', 'sounds') or "
                    "search_browser('Analog', 'instruments'), then load_browser_item."
                )
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error creating bassline: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def create_melody(
        key: str = "C",
        category: str = "synth",
        bars: int = 4,
        sound: Union[str, int] = "",
        track_index: int = -1,
        clip_index: int = 0,
    ) -> str:
        """Create a melodic pattern from real MIDI patterns in the library.

        Creates a MIDI track, loads a sound preset, picks a real pattern
        matched to key and tempo, and writes to a clip.

        Categories: synth (251 patterns), keys (155), chords (96), pads (50), melody (27).

        Args:
            key: Musical key (e.g. "C", "Am", "F#"). Default "C".
            category: Pattern type: synth, keys, chords, pads, melody. Default "synth".
            bars: Number of bars (1-16). Default 4.
            sound: Sound to search for in Ableton's browser. Can be a preset
                ("Lead", "Pluck", "Piano"), a pack/artist name, or any search
                term. Leave empty for auto-detect by category.
            track_index: Track to write to. -1 = create new track (default).
            clip_index: Clip slot to use (default 0).
        """
        try:
            sound = str(sound) if sound else ""
            valid = {"synth", "keys", "chords", "pads", "melody"}
            if category not in valid:
                return json.dumps({
                    "error": "Unknown category: {}. Options: {}".format(
                        category, ", ".join(sorted(valid))),
                })

            bars = max(1, min(16, bars))
            conn = await get_connection()
            session = await conn.send_command("get_session_info")
            tempo = session.get("tempo", 120)

            category_names = {
                "synth": "Synth", "keys": "Keys", "chords": "Chords",
                "pads": "Pad", "melody": "Melody",
            }

            if track_index == -1:
                track_name = category_names.get(category, category.title())
                track_index, _ = await _setup_track(conn, track_name, bars, clip_index)
            else:
                await conn.send_command("create_clip", {
                    "track_index": track_index, "clip_index": clip_index,
                    "length": bars * 4,
                })

            notes = generate_from_patterns(
                category=category, key=key, bars=bars, bpm=tempo,
            )
            if not notes:
                cache.invalidate_all()
                return json.dumps({"error": "Failed to generate {} pattern".format(category)})
            notes.sort(key=lambda n: (n["start_time"], n["pitch"]))

            clip_name = "{} {} {}bar".format(
                category_names.get(category, category.title()), key, bars,
            )
            await _write_notes(conn, track_index, clip_index, notes, clip_name)

            default_sounds = {
                "synth": "Lead", "keys": "Piano",
                "chords": "Piano", "pads": "Pad",
                "melody": "Lead",
            }
            sound_query = str(sound) if sound else default_sounds.get(category, "Synth")
            instrument = await _try_load_instrument(
                conn, track_index, sound_query, "sounds",
            )
            cache.invalidate_all()

            result = {
                "status": "ok",
                "track_index": track_index,
                "clip_index": clip_index,
                "key": key,
                "category": category,
                "bars": bars,
                "tempo": tempo,
                "notes_count": len(notes),
                "instrument": instrument,
            }
            if not instrument.get("loaded"):
                result["action_needed"] = (
                    "No instrument was loaded — the track has MIDI notes but NO SOUND. "
                    "Load an instrument: use search_browser('{}', 'sounds'), "
                    "then load_browser_item.".format(sound_query)
                )
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error creating melody: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def create_chords(
        key: str = "C",
        mode: str = "major",
        progression: str = "I-V-vi-IV",
        bars: int = 4,
        octave: int = 4,
        sound: Union[str, int] = "",
        track_index: int = -1,
        clip_index: int = 0,
    ) -> str:
        """Create a chord progression on a track.

        Creates a MIDI track, loads a keys/piano sound, generates chords from
        Roman numeral notation, and writes them to Ableton.

        Presets (pass as progression): pop, jazz, blues, rock, sad, epic,
        house, reggaeton, andalusian. Or custom: "I-V-vi-IV".

        Args:
            key: Root note (e.g. "C", "F#", "Bb"). Default "C".
            mode: "major" or "minor". Default "major".
            progression: Roman numerals or preset name. Default "I-V-vi-IV".
            bars: Number of bars. Default 4.
            octave: MIDI octave for voicings (3-5). Default 4.
            sound: What to search in Ableton's browser. Leave empty for
                default ("Piano"). Or pass any term: pack name, preset, etc.
            track_index: Track to write to. -1 = create new track (default).
            clip_index: Clip slot to use (default 0).
        """
        try:
            sound = str(sound) if sound else ""
            bars = max(1, min(16, bars))
            conn = await get_connection()
            session = await conn.send_command("get_session_info")
            tempo = session.get("tempo", 120)

            notes, prog_str, chord_names = _generate_chord_notes(
                key, mode, progression, octave, bars,
            )
            if not notes:
                return json.dumps({
                    "error": "Could not generate chords for: {}".format(progression),
                })

            if track_index == -1:
                track_index, _ = await _setup_track(conn, "Chords", bars, clip_index)
            else:
                await conn.send_command("create_clip", {
                    "track_index": track_index, "clip_index": clip_index,
                    "length": bars * 4,
                })

            clip_name = "{} {} {}".format(key, mode, prog_str)
            await _write_notes(conn, track_index, clip_index, notes, clip_name)

            # Load instrument first
            chord_query = str(sound) if sound else "Piano"
            instrument = await _try_load_instrument(conn, track_index, chord_query, "sounds")
            cache.invalidate_all()

            result = {
                "status": "ok",
                "track_index": track_index,
                "clip_index": clip_index,
                "key": key,
                "mode": mode,
                "progression": prog_str,
                "chords": chord_names,
                "bars": bars,
                "tempo": tempo,
                "notes_count": len(notes),
                "instrument": instrument,
            }
            if not instrument.get("loaded"):
                result["action_needed"] = (
                    "No instrument was loaded — the track has MIDI notes but NO SOUND. "
                    "Load a keys instrument: use search_browser('Piano', 'sounds') or "
                    "search_browser('Grand Piano', 'sounds'), then load_browser_item."
                )
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error creating chords: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def create_pad(
        key: str = "C",
        bars: int = 4,
        sound: Union[str, int] = "",
        track_index: int = -1,
        clip_index: int = 0,
    ) -> str:
        """Create a pad/texture pattern from real pad patterns in the library.

        Creates a MIDI track, loads a pad sound, generates sustained atmospheric
        patterns from the library, and writes to a clip.

        Args:
            key: Musical key (e.g. "C", "Am", "F#"). Default "C".
            bars: Number of bars (1-16). Default 4.
            sound: What to search in Ableton's browser. Leave empty for
                default ("Pad"). Or pass any term: pack name, preset, etc.
            track_index: Track to write to. -1 = create new track (default).
            clip_index: Clip slot to use (default 0).
        """
        try:
            sound = str(sound) if sound else ""
            bars = max(1, min(16, bars))
            conn = await get_connection()
            session = await conn.send_command("get_session_info")
            tempo = session.get("tempo", 120)

            if track_index == -1:
                track_index, _ = await _setup_track(conn, "Pad", bars, clip_index)
            else:
                await conn.send_command("create_clip", {
                    "track_index": track_index, "clip_index": clip_index,
                    "length": bars * 4,
                })

            notes = generate_from_patterns(
                category="pads", key=key, bars=bars, bpm=tempo,
            )
            if not notes:
                cache.invalidate_all()
                return json.dumps({"error": "Failed to generate pad pattern"})
            notes.sort(key=lambda n: (n["start_time"], n["pitch"]))

            clip_name = "Pad {} {}bar".format(key, bars)
            await _write_notes(conn, track_index, clip_index, notes, clip_name)

            # Load instrument first
            pad_query = str(sound) if sound else "Pad"
            instrument = await _try_load_instrument(conn, track_index, pad_query, "sounds")
            cache.invalidate_all()

            result = {
                "status": "ok",
                "track_index": track_index,
                "clip_index": clip_index,
                "key": key,
                "bars": bars,
                "tempo": tempo,
                "notes_count": len(notes),
                "instrument": instrument,
            }
            if not instrument.get("loaded"):
                result["action_needed"] = (
                    "No instrument was loaded — the track has MIDI notes but NO SOUND. "
                    "Load a pad instrument: use search_browser('Pad', 'sounds'), "
                    "then load_browser_item."
                )
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error creating pad: %s", e)
            return json.dumps({"error": str(e)})
