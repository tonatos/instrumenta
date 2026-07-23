import type { Page } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

export type HqScreencast = {
  stop: () => Promise<void>;
  framesDir: string;
  outputPath: string;
};

type FrameMeta = { file: string; wallMs: number };

/**
 * High-quality screencast: timed device-scale screenshots → ffmpeg VP9.
 *
 * Playwright's built-in video is soft VP8; CDP screencast is CSS-pixel (1×).
 * `page.screenshot({ scale: "device" })` captures the retina framebuffer.
 * JPEG q=100 is near-lossless for UI and much faster than PNG at 2×.
 */
export async function startHqScreencast(
  page: Page,
  opts: {
    outputPath: string;
    framesDir: string;
    /** Target capture rate. Actual rate depends on screenshot speed. */
    fps?: number;
  },
): Promise<HqScreencast> {
  const fps = opts.fps ?? 12;
  const intervalMs = Math.round(1000 / fps);
  const { outputPath, framesDir } = opts;

  fs.mkdirSync(framesDir, { recursive: true });
  for (const name of fs.readdirSync(framesDir)) {
    if (
      (name.startsWith("frame-") && /\.(png|jpg)$/.test(name)) ||
      name === "concat.txt"
    ) {
      fs.unlinkSync(path.join(framesDir, name));
    }
  }
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });

  let running = true;
  let frameIndex = 0;
  const frames: FrameMeta[] = [];
  const startedAt = Date.now();

  const loopPromise = (async () => {
    while (running) {
      const tickStart = Date.now();
      try {
        const buf = await page.screenshot({
          type: "jpeg",
          quality: 100,
          scale: "device",
          animations: "allow",
          caret: "initial",
        });
        if (!running) break;
        const fileName = `frame-${String(frameIndex++).padStart(6, "0")}.jpg`;
        fs.writeFileSync(path.join(framesDir, fileName), buf);
        frames.push({ file: fileName, wallMs: Date.now() - startedAt });
      } catch (err) {
        if (running) {
          console.error("screenshot frame failed:", err);
        }
        break;
      }
      const elapsed = Date.now() - tickStart;
      const wait = intervalMs - elapsed;
      if (wait > 0 && running) {
        await new Promise((r) => setTimeout(r, wait));
      }
    }
  })();

  async function stop(): Promise<void> {
    if (!running) return;
    running = false;
    await loopPromise;

    if (frames.length < 5) {
      throw new Error(
        `HQ screencast produced too few frames (${frames.length}) in ${framesDir}`,
      );
    }

    const width = 2732;
    const height = 2048;
    const concatPath = path.join(framesDir, "concat.txt");
    fs.writeFileSync(concatPath, buildConcatList(frames), "utf8");
    console.log(
      `HQ screencast: ${frames.length} frames @ ~${fps}fps target, ${width}×${height}, ~${(
        frames[frames.length - 1].wallMs / 1000
      ).toFixed(1)}s wall`,
    );
    await encodeConcatToVp9(concatPath, outputPath, width, height);
  }

  return { stop, framesDir, outputPath };
}

function buildConcatList(frames: FrameMeta[]): string {
  const lines: string[] = [];
  for (let i = 0; i < frames.length; i++) {
    const cur = frames[i];
    const next = frames[i + 1];
    let durationSec = next
      ? Math.max(1 / 60, (next.wallMs - cur.wallMs) / 1000)
      : 1 / 12;
    durationSec = Math.min(durationSec, 0.4);
    lines.push(`file '${cur.file}'`);
    lines.push(`duration ${durationSec.toFixed(4)}`);
  }
  lines.push(`file '${frames[frames.length - 1].file}'`);
  return `${lines.join("\n")}\n`;
}

function encodeConcatToVp9(
  concatPath: string,
  outputPath: string,
  width: number,
  height: number,
): Promise<void> {
  return new Promise((resolve, reject) => {
    // yuv420p for Safari/Chrome compatibility; CRF 6 keeps UI text sharp.
    const args = [
      "-y",
      "-f",
      "concat",
      "-safe",
      "0",
      "-i",
      concatPath,
      "-vf",
      `scale=${width}:${height}:flags=neighbor,format=yuv420p`,
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
      "-tile-columns",
      "2",
      "-frame-parallel",
      "1",
      "-auto-alt-ref",
      "1",
      "-lag-in-frames",
      "25",
      "-g",
      "48",
      "-an",
      outputPath,
    ];

    console.log(`ffmpeg encode → ${outputPath} (${width}×${height} VP9 CRF6)`);
    const child: ChildProcessWithoutNullStreams = spawn("ffmpeg", args, {
      cwd: path.dirname(concatPath),
      stdio: ["ignore", "inherit", "inherit"],
    });
    child.on("error", (err) => {
      reject(
        new Error(
          `ffmpeg failed to start (${err.message}). Install ffmpeg (e.g. brew install ffmpeg).`,
        ),
      );
    });
    child.on("close", (code) => {
      if (code === 0) {
        const size = fs.statSync(outputPath).size;
        console.log(
          `Wrote ${outputPath} (${(size / (1024 * 1024)).toFixed(1)} MiB)`,
        );
        resolve();
      } else {
        reject(new Error(`ffmpeg exited with code ${code}`));
      }
    });
  });
}
