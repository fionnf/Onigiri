import { formatBytes } from "@/lib/images";
import { useEffect, useMemo } from "react";
import { IconCamera, IconPlus, IconX } from "./Icons";

/** Photos and videos chosen for a capture, with previews and thumb-sized controls. */
export function MediaPicker({
  files,
  onChange,
  showCamera = true,
  chooseLabel = "Photos or video",
}: {
  files: File[];
  onChange: (next: File[]) => void;
  showCamera?: boolean;
  chooseLabel?: string;
}) {
  const previews = useMemo(
    () => files.map((file) => (file.type.startsWith("image/") ? URL.createObjectURL(file) : null)),
    [files],
  );
  useEffect(
    () => () => {
      for (const url of previews) if (url) URL.revokeObjectURL(url);
    },
    [previews],
  );

  const add = (list: FileList | null) => {
    if (list?.length) onChange([...files, ...Array.from(list)]);
  };

  return (
    <div className="space-y-2">
      {files.length > 0 && (
        <ul className="grid grid-cols-3 gap-2 sm:grid-cols-5">
          {files.map((file, index) => (
            <li
              key={`${file.name}-${file.size}-${file.lastModified}`}
              className="relative overflow-hidden rounded-md border border-line bg-surface"
            >
              {previews[index] ? (
                <img
                  src={previews[index] ?? ""}
                  alt=""
                  className="aspect-square w-full object-cover"
                />
              ) : (
                <div className="flex aspect-square w-full items-center justify-center p-1 text-center text-xs text-muted">
                  {file.type.startsWith("video/") ? "Video" : "File"}
                </div>
              )}
              <span className="absolute inset-x-0 bottom-0 truncate bg-page/80 px-1 text-[10px] text-muted">
                {formatBytes(file.size)}
              </span>
              <button
                type="button"
                className="absolute right-1 top-1 inline-flex h-8 w-8 items-center justify-center rounded-full bg-page/90 text-ink shadow"
                onClick={() => onChange(files.filter((_, i) => i !== index))}
                aria-label={`Remove ${file.name}`}
              >
                <IconX className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-2">
        {showCamera && (
          <label className="btn btn-sm cursor-pointer sm:hidden">
            <IconCamera className="h-4 w-4" />
            Take photo
            <input
              type="file"
              className="hidden"
              accept="image/*"
              capture="environment"
              onChange={(event) => {
                add(event.target.files);
                event.target.value = "";
              }}
            />
          </label>
        )}
        <label className="btn btn-sm cursor-pointer">
          <IconPlus className="h-4 w-4" />
          {chooseLabel}
          <input
            type="file"
            className="hidden"
            multiple
            accept="image/*,video/*,.heic,.heif"
            onChange={(event) => {
              add(event.target.files);
              event.target.value = "";
            }}
          />
        </label>
      </div>
    </div>
  );
}
