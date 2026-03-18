"""Clip manipulation tools for AbletonMCP."""
import json
import logging
import re
from typing import List, Dict
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("AbletonMCPServer")

# Key detection regex for sample filenames
_KEY_PATTERN = re.compile(
    r'[_\s-]([A-G][b#]?)\s*'       # note name: C, F#, Bb
    r'(m(?:in(?:or)?)?|maj(?:or)?)?'  # optional mode: m, min, minor, maj, major
    r'(?=[_\s.\-]|$)',               # followed by separator or end
    re.IGNORECASE,
)
_BPM_PATTERN = re.compile(r'(\d{2,3})\s*bpm', re.IGNORECASE)

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_TO_SHARP = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}


def _parse_key_from_name(name):
    """Extract musical key from a filename. Returns e.g. 'Am', 'C', 'F#m' or None."""
    match = _KEY_PATTERN.search(name)
    if not match:
        return None
    note = match.group(1)
    mode = match.group(2) or ""
    # Normalize
    note = note[0].upper() + note[1:]
    if note in FLAT_TO_SHARP:
        note = FLAT_TO_SHARP[note]
    is_minor = mode.lower().startswith("m") if mode else False
    return note + ("m" if is_minor else "")


def _parse_bpm_from_name(name):
    """Extract BPM from a filename. Returns int or None."""
    match = _BPM_PATTERN.search(name)
    if match:
        bpm = int(match.group(1))
        if 60 <= bpm <= 200:
            return bpm
    return None


def _note_to_semitone(key):
    """Convert key string to semitone offset (0-11). Returns (semitone, is_minor)."""
    if not key:
        return None, False
    is_minor = key.endswith("m")
    note = key.rstrip("m")
    if note in FLAT_TO_SHARP:
        note = FLAT_TO_SHARP[note]
    if note in NOTE_NAMES:
        return NOTE_NAMES.index(note), is_minor
    return None, False


def _transpose_semitones(from_key, to_key):
    """Calculate semitones needed to transpose from_key to to_key.
    For minor keys, transposes relative minor to relative minor."""
    from_st, from_minor = _note_to_semitone(from_key)
    to_st, to_minor = _note_to_semitone(to_key)
    if from_st is None or to_st is None:
        return 0
    diff = (to_st - from_st) % 12
    if diff > 6:
        diff -= 12
    return diff


def register(mcp: FastMCP, get_connection, cache):
    """Register clip tools."""

    @mcp.tool()
    async def create_audio_clip(
        track_index: int, clip_index: int, file_path: str,
    ) -> str:
        """Load an audio file into a specific clip slot on an audio track.

        Unlike load_browser_item (which always loads to slot 0), this tool
        lets you place audio clips in ANY clip slot. Use this for building
        session views with multiple loops organized by scene.

        The file_path comes from browse_folder results (the "file_path" field).

        Requires Ableton Live 12.0.5+.

        Args:
            track_index: Audio track index.
            clip_index: Clip slot (scene) to place the audio clip in.
            file_path: Full filesystem path to the audio file (WAV/AIF/FLAC).
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("create_audio_clip", {
                "track_index": track_index,
                "clip_index": clip_index,
                "file_path": file_path,
            })
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error creating audio clip: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def create_clip(track_index: int, clip_index: int, length: float = 4.0) -> str:
        """Create an empty MIDI clip.

        Args:
            track_index: Track to create the clip on.
            clip_index: Clip slot index.
            length: Clip length in beats (4.0 = 1 bar). Default 4.0.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("create_clip", {
                "track_index": track_index,
                "clip_index": clip_index,
                "length": length,
            })
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error creating clip: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def add_notes_to_clip(
        track_index: int,
        clip_index: int,
        notes: List[Dict],
    ) -> str:
        """Add MIDI notes to an existing clip.

        For generating patterns, prefer create_beat, create_bassline,
        create_melody, or create_chords — they handle the full workflow.
        Use this only when you need to place specific individual notes.

        Note format: [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100}]

        Args:
            track_index: Track containing the clip.
            clip_index: Clip slot index.
            notes: List of note dicts with pitch, start_time, duration, velocity.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("add_notes_to_clip", {
                "track_index": track_index,
                "clip_index": clip_index,
                "notes": notes,
            })
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error adding notes: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def delete_clip(track_index: int, clip_index: int) -> str:
        """Delete a clip from a track.

        Args:
            track_index: Track containing the clip.
            clip_index: Clip slot index.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("delete_clip", {
                "track_index": track_index,
                "clip_index": clip_index,
            })
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error deleting clip: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def duplicate_clip(
        track_index: int,
        clip_index: int,
        target_track: int,
        target_clip: int,
    ) -> str:
        """Copy a clip to another slot.

        Args:
            track_index: Source track.
            clip_index: Source clip slot.
            target_track: Destination track.
            target_clip: Destination clip slot.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("duplicate_clip_to_slot", {
                "track_index": track_index,
                "clip_index": clip_index,
                "target_track": target_track,
                "target_clip": target_clip,
            })
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error duplicating clip: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_audio_clip_info(track_index: int, clip_index: int) -> str:
        """Get properties of an audio clip (pitch, warp, gain, file path).

        Use this to inspect audio clips after loading loops. Returns pitch
        transpose, warp mode, gain, file path, and whether it's audio or MIDI.

        Args:
            track_index: Track containing the clip.
            clip_index: Clip slot index.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("get_audio_clip_info", {
                "track_index": track_index, "clip_index": clip_index,
            })
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error getting audio clip info: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def set_clip_pitch(
        track_index: int, clip_index: int,
        semitones: int = 0, cents: int = 0,
    ) -> str:
        """Transpose an audio clip by semitones and/or cents.

        Use this to match an audio loop's key to the session key. For example,
        if a loop is in Am and you need it in Cm, set semitones=3.

        Only works on audio clips (not MIDI). Range: -48 to 48 semitones,
        -500 to 500 cents.

        Args:
            track_index: Track containing the audio clip.
            clip_index: Clip slot index.
            semitones: Pitch shift in semitones (-48 to 48). Default 0.
            cents: Fine pitch in cents (-500 to 500). Default 0.
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("set_clip_pitch", {
                "track_index": track_index,
                "clip_index": clip_index,
                "pitch_coarse": semitones,
                "pitch_fine": cents,
            })
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error setting clip pitch: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def set_clip_warp(
        track_index: int, clip_index: int,
        warping: bool = True, warp_mode: int = 0,
    ) -> str:
        """Set warp mode on an audio clip.

        Warping enables time-stretching so loops play at the session tempo.
        Different warp modes suit different material:
          0 = beats (drums, percussion)
          1 = complex (full mixes)
          2 = complex_pro (high quality full mixes)
          3 = repitch (like a turntable — changes pitch with tempo)
          4 = rex (for REX files)
          5 = texture (ambient, pads)
          6 = tones (melodic, vocals, bass)

        Args:
            track_index: Track containing the audio clip.
            clip_index: Clip slot index.
            warping: Enable warping. Default True.
            warp_mode: Warp algorithm (0-6). Default 0 (beats).
        """
        try:
            conn = await get_connection()
            result = await conn.send_command("set_clip_warp", {
                "track_index": track_index,
                "clip_index": clip_index,
                "warping": warping,
                "warp_mode": warp_mode,
            })
            cache.invalidate_all()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error("Error setting clip warp: %s", e)
            return json.dumps({"error": str(e)})
