#!/usr/bin/env node
/**
 * Legacy helper: re-encode an existing WebM.
 * Primary HQ path is screenshot capture in hq-screencast.ts (called from record-tour.spec.ts).
 *
 * Usage:
 *   node process-tour-video.mjs <input.webm> <output.webm> [trimStartSec]
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const OUTPUT_W = 2732;
const OUTPUT_H = 2048;

const input = process.argv[2];
const output = process.argv[3];
const trimStart = Number(process.argv[4] ?? "0");

if (!input || !output) {
  console.error(
    "Usage: node process-tour-video.mjs <input.webm> <output.webm> [trimStartSec]",
  );
  process.exit(1);
}

const probe = spawnSync("ffmpeg", ["-version"], { encoding: "utf8" });
if (probe.status !== 0) {
  console.error(
    "ffmpeg not found in PATH. Install it (e.g. `brew install ffmpeg`).",
  );
  process.exit(1);
}

if (!fs.existsSync(input)) {
  console.error(`Input video not found: ${input}`);
  process.exit(1);
}

fs.mkdirSync(path.dirname(output), { recursive: true });

const args = [
  "-y",
  ...(trimStart > 0 ? ["-ss", String(trimStart)] : []),
  "-i",
  input,
  "-vf",
  `scale=${OUTPUT_W}:${OUTPUT_H}:flags=lanczos,format=yuv420p`,
  "-c:v",
  "libvpx-vp9",
  "-crf",
  "6",
  "-b:v",
  "0",
  "-deadline",
  "good",
  "-cpu-used",
  "0",
  "-row-mt",
  "1",
  "-an",
  output,
];

console.log(`ffmpeg ${args.join(" ")}`);
const result = spawnSync("ffmpeg", args, { stdio: "inherit" });
if (result.status !== 0) {
  console.error("ffmpeg failed");
  process.exit(result.status ?? 1);
}

const size = fs.statSync(output).size;
console.log(
  `Wrote ${output} (${(size / (1024 * 1024)).toFixed(1)} MiB, ${OUTPUT_W}×${OUTPUT_H} VP9)`,
);
