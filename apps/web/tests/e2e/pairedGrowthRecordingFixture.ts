import type { Page } from "@playwright/test";
import { spawn } from "node:child_process";

export type RecordingShot = {
  organism: string;
  visit: string;
  width: number;
  excluded?: boolean;
};

function encodeRecording(frames: Buffer[]): Promise<Buffer> {
  // Use the FFmpeg distributed with ReefVision. For a source checkout, set
  // this to the result of imageio_ffmpeg.get_ffmpeg_exe() in the app's Python.
  const executable = process.env.REEFVISION_PAIRED_GROWTH_FFMPEG;
  if (!executable) {
    throw new Error(
      "Set REEFVISION_PAIRED_GROWTH_FFMPEG for the recording fixture",
    );
  }
  return new Promise((resolve, reject) => {
    const encoder = spawn(
      executable,
      [
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "image2pipe",
        "-framerate",
        "2",
        "-c:v",
        "mjpeg",
        "-i",
        "pipe:0",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        "1",
        "-movflags",
        "frag_keyframe+empty_moov",
        "-f",
        "mp4",
        "pipe:1",
      ],
      { windowsHide: true, timeout: 15_000 },
    );
    const chunks: Buffer[] = [];
    const diagnostics: Buffer[] = [];
    encoder.stdout.on("data", (chunk: Buffer) => chunks.push(chunk));
    encoder.stderr.on("data", (chunk: Buffer) => diagnostics.push(chunk));
    encoder.stdin.on("error", reject);
    encoder.on("error", reject);
    encoder.on("close", (code) => {
      if (code === 0) resolve(Buffer.concat(chunks));
      else
        reject(
          new Error(
            `Could not encode time-lapse: ${Buffer.concat(diagnostics)}`,
          ),
        );
    });
    encoder.stdin.end(Buffer.concat(frames));
  });
}

export async function recordPairedGrowthTimeLapse(
  page: Page,
  shots: RecordingShot[],
  recordingIndex: number,
) {
  // The same rendered acquisitions become the source JPEGs retained
  // by the growth workflow and one time-lapse encoding with compressed playback.
  const photos = await page.evaluate(
    ({ shots, recordingIndex }) => {
      const canvas = document.createElement("canvas");
      canvas.width = 80;
      canvas.height = 60;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Cannot render the synthetic recording");

      return shots.map((shot, capture) => {
        context.fillStyle = `hsl(${recordingIndex * 60} 30% 20%)`;
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.fillStyle = "#b1d5bc";
        context.fillRect(5, 8, shot.width, 12);
        context.fillStyle = "white";
        context.fillText(`Synthetic frame ${capture + 1}`, 3, 34);
        context.fillText(shot.visit, 3, 49);
        if (shot.excluded) {
          context.fillStyle = "rgba(255,255,255,.8)";
          context.fillRect(shot.width - 1, 5, 10, 18);
        }
        return canvas.toDataURL("image/jpeg", 0.94).split(",")[1];
      });
    },
    { shots, recordingIndex },
  );
  return {
    video: await encodeRecording(
      photos.map((photo) => Buffer.from(photo, "base64")),
    ),
    photos,
  };
}
