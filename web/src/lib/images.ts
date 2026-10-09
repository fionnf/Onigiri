/**
 * Shrink phone photos before they are uploaded.
 *
 * A phone camera photo is 3 to 12 MB. Claude reads at most 1600 px on the long edge,
 * so anything past ~2400 px is only upload time on a mobile connection. Re-encoding
 * also turns iPhone HEIC into JPEG wherever the browser can decode it; where it
 * cannot, the original goes up and the server converts it.
 */

const MAX_EDGE = 2400;
const QUALITY = 0.85;
const SMALL_ENOUGH = 1.5 * 1024 * 1024;

function isHeic(file: File): boolean {
  return /image\/hei[cf]/i.test(file.type) || /\.hei[cf]$/i.test(file.name);
}

function jpegName(name: string): string {
  const base = name.replace(/\.[^.]+$/, "") || "photo";
  return `${base}.jpg`;
}

async function encode(bitmap: ImageBitmap, width: number, height: number): Promise<Blob | null> {
  if (typeof OffscreenCanvas !== "undefined") {
    const canvas = new OffscreenCanvas(width, height);
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(bitmap, 0, 0, width, height);
    return canvas.convertToBlob({ type: "image/jpeg", quality: QUALITY });
  }
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(bitmap, 0, 0, width, height);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", QUALITY));
}

export async function prepareForUpload(file: File): Promise<File> {
  const heic = isHeic(file);
  if (!file.type.startsWith("image/") && !heic) return file;
  if (file.type === "image/gif") return file;
  if (file.size <= SMALL_ENOUGH && !heic) return file;

  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));
    const blob = await encode(bitmap, width, height);
    bitmap.close();
    if (!blob) return file;
    if (blob.size >= file.size && !heic) return file;
    return new File([blob], jpegName(file.name), {
      type: "image/jpeg",
      lastModified: file.lastModified,
    });
  } catch {
    // The browser could not decode it (HEIC outside Safari, say). The server can.
    return file;
  }
}

export async function prepareAll(files: File[]): Promise<File[]> {
  return Promise.all(files.map(prepareForUpload));
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
