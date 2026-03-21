#!/usr/bin/env node
/**
 * PreToolUse hook for Ableton MCP tools.
 *
 * 1. Coerces numeric values to strings for parameters that Pydantic expects as str
 *    (fixes the "909" → 909 integer coercion bug).
 * 2. Validates known enum values (style, category, warp_mode, track type).
 * 3. Outputs warnings to stderr for suspicious inputs.
 */

import { readFileSync } from "fs";

const input = JSON.parse(readFileSync("/dev/stdin", "utf8"));
const toolName = input.tool_name || "";

// Only process Ableton MCP tools — match any server name containing "ableton"
if (!/^mcp__.*ableton.*__/.test(toolName)) {
  process.exit(0);
}

// --- Parameter type definitions ---

// These parameters MUST remain as numbers (indices, counts, pitches, etc.)
const NUMERIC_PARAMS = new Set([
  "track_index",
  "clip_index",
  "bars",
  "pad_note",
  "semitones",
  "scene_index",
  "bpm",
  "tempo",
  "volume",
  "pan",
  "velocity",
  "duration",
  "start_time",
  "pitch",
  "parameter_index",
  "value",
  "octave",
  "length",
  "gain",
  "fine_cents",
  "warp_mode",
  "pitch_coarse",
  "pitch_fine",
]);

// Known enum values for validation
const VALID_STYLES = new Set([
  "house",
  "techno",
  "rock",
  "hiphop",
  "trap",
  "dnb",
  "reggaeton",
  "bossa_nova",
  "jazz_swing",
  "funk",
  "basic",
]);

const VALID_CATEGORIES = new Set([
  "all",
  "instruments",
  "drums",
  "sounds",
  "samples",
  "audio_effects",
  "midi_effects",
  "packs",
]);

const VALID_TRACK_TYPES = new Set(["midi", "audio"]);
const VALID_WARP_MODES = new Set([0, 1, 2, 3, 4, 5, 6]);

// --- Processing ---

const toolInput = input.tool_input;
if (!toolInput || typeof toolInput !== "object") {
  process.exit(0);
}

let changed = false;
const updated = { ...toolInput };
const warnings = [];

for (const [key, val] of Object.entries(toolInput)) {
  // Coerce numbers to strings for non-numeric params
  if (typeof val === "number" && !NUMERIC_PARAMS.has(key)) {
    updated[key] = String(val);
    changed = true;
    warnings.push(`Coerced ${key}: ${val} (int) → "${val}" (string)`);
  }

  // Validate known enums
  if (key === "style" && typeof val === "string" && !VALID_STYLES.has(val)) {
    warnings.push(
      `Unknown style "${val}". Valid: ${[...VALID_STYLES].join(", ")}`
    );
  }
  if (
    key === "category" &&
    typeof val === "string" &&
    !VALID_CATEGORIES.has(val)
  ) {
    warnings.push(
      `Unknown category "${val}". Valid: ${[...VALID_CATEGORIES].join(", ")}`
    );
  }
  if (key === "type" && typeof val === "string" && !VALID_TRACK_TYPES.has(val)) {
    warnings.push(
      `Unknown track type "${val}". Valid: ${[...VALID_TRACK_TYPES].join(", ")}`
    );
  }
  if (key === "warp_mode" && typeof val === "number" && !VALID_WARP_MODES.has(val)) {
    warnings.push(`Invalid warp_mode ${val}. Valid: 0-6`);
  }
}

// Output warnings to stderr (visible in debug mode)
if (warnings.length > 0) {
  process.stderr.write(
    `[ableton-hook] ${toolName}: ${warnings.join("; ")}\n`
  );
}

// Return updated input if anything changed
if (changed) {
  console.log(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        updatedInput: updated,
      },
    })
  );
}

process.exit(0);
