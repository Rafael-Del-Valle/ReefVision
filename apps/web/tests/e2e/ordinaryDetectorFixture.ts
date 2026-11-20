import { deflateSync } from "node:zlib";

const pngSignature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const size = 96;

function pngChunk(type: string, data: Buffer) {
  const chunk = Buffer.alloc(data.length + 12);
  chunk.writeUInt32BE(data.length);
  chunk.write(type, 4, "ascii");
  data.copy(chunk, 8);

  let crc = 0xffffffff;
  for (const byte of chunk.subarray(4, -4)) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
  }
  chunk.writeUInt32BE((crc ^ 0xffffffff) >>> 0, chunk.length - 4);
  return chunk;
}

/** Explicit synthetic training and evaluation geometry in source pixels. */
export function detectorStill(index: number) {
  const x = 18 + index;
  const y = 19 + (index % 4) * 4;
  const box = { x_min: x, y_min: y, x_max: x + 34, y_max: y + 32 };
  const rowLength = 1 + size * 3;
  const pixels = Buffer.alloc(rowLength * size);
  for (let row = 0; row < size; row++) {
    for (let column = 0; column < size; column++) {
      const inside =
        column >= box.x_min &&
        column <= box.x_max &&
        row >= box.y_min &&
        row <= box.y_max;
      const offset = row * rowLength + 1 + column * 3;
      pixels[offset] = inside ? 190 : 19 + index * 2;
      pixels[offset + 1] = inside ? 210 : 22;
      pixels[offset + 2] = inside ? 40 + index * 7 : 33;
    }
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header[8] = 8; // Bits per channel
  header[9] = 2; // RGB
  return {
    box,
    file: {
      name: `synthetic-square-${index}.png`,
      mimeType: "image/png",
      buffer: Buffer.concat([
        pngSignature,
        pngChunk("IHDR", header),
        pngChunk("IDAT", deflateSync(pixels)),
        pngChunk("IEND", Buffer.alloc(0)),
      ]),
    },
  };
}
