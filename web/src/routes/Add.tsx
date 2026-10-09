import { api } from "@/api/client";
import { IconLink } from "@/components/Icons";
import { MediaPicker } from "@/components/MediaPicker";
import { ErrorBox } from "@/components/ui";
import { relativeDate, stageLabel } from "@/lib/format";
import { prepareAll } from "@/lib/images";
import { takeShared } from "@/lib/share";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

const isTouch = () =>
  typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches;

const URL_ONLY = /^https?:\/\/\S+$/i;

interface Payload {
  text: string;
  files: File[];
}

export function Add() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [pasteHint, setPasteHint] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sharedHandled = useRef(false);

  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.jobs(false),
    refetchInterval: (q) =>
      (q.state.data ?? []).some((j) =>
        ["queued", "fetching", "transcribing", "reading", "extracting"].includes(j.status),
      )
        ? 1500
        : false,
  });

  const submit = useMutation({
    mutationFn: async ({ text: raw, files: picked }: Payload) => {
      const trimmed = raw.trim();
      const extra = URL_ONLY.test(trimmed) ? { url: trimmed } : { text: trimmed };
      if (picked.length > 0) {
        setProgress(0);
        const ready = await prepareAll(picked);
        return api.ingestFiles(ready, extra, (sent, total) => setProgress(sent / total));
      }
      return api.ingest(extra);
    },
    onSuccess: (job) => {
      setText("");
      setFiles([]);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      navigate(`/j/${job.id}`);
    },
    onSettled: () => setProgress(null),
  });

  // Shared from another app's share sheet: the service worker stashed it, and
  // there is nothing left to decide, so capture it straight away.
  useEffect(() => {
    if (!params.has("shared") || sharedHandled.current) return;
    sharedHandled.current = true;
    void (async () => {
      const shared = await takeShared();
      setParams({}, { replace: true });
      if (!shared) return;
      const sharedText = [shared.url, shared.text].filter(Boolean).join("\n").trim();
      if (!sharedText && shared.files.length === 0) return;
      setText(sharedText);
      setFiles(shared.files);
      submit.mutate({ text: sharedText, files: shared.files });
    })();
  }, [params, setParams, submit]);

  // On a phone the keyboard would cover half the screen before you chose anything.
  useEffect(() => {
    if (!isTouch()) inputRef.current?.focus();
  }, []);

  const paste = async () => {
    setPasteHint(false);
    try {
      const clip = (await navigator.clipboard.readText()).trim();
      if (clip) {
        setText(clip);
        return;
      }
    } catch {
      /* permission refused or not supported; fall back to the system paste menu */
    }
    setPasteHint(true);
    inputRef.current?.focus();
  };

  const canSubmit = (text.trim().length > 0 || files.length > 0) && !submit.isPending;
  const busyLabel =
    progress === null
      ? "Starting…"
      : progress < 1
        ? `Uploading ${Math.round(progress * 100)}%`
        : "Reading…";

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <h1 className="text-lg font-semibold sm:text-base">Add a recipe</h1>
        <p className="text-sm text-muted">
          Paste a link from Instagram, TikTok or a recipe site, paste the recipe itself, or
          photograph a cookbook page or a handwritten card.
        </p>
      </div>

      <form
        className="card space-y-3 p-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (canSubmit) submit.mutate({ text, files });
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          setFiles([...files, ...Array.from(event.dataTransfer.files)]);
        }}
      >
        <div className="relative">
          <textarea
            ref={inputRef}
            className={`field min-h-32 resize-y ${dragging ? "border-accent" : ""}`}
            placeholder={"Link or recipe text"}
            autoCapitalize="sentences"
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              setPasteHint(false);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && canSubmit) {
                event.preventDefault();
                submit.mutate({ text, files });
              }
            }}
          />
          {!text && (
            <button
              type="button"
              className="btn btn-sm absolute bottom-2 right-2"
              onClick={() => void paste()}
            >
              Paste
            </button>
          )}
        </div>
        {pasteHint && (
          <p className="text-xs text-muted">Press and hold in the box above, then choose Paste.</p>
        )}

        <MediaPicker files={files} onChange={setFiles} />

        <button
          type="submit"
          className="btn btn-primary w-full sm:ml-auto sm:w-auto"
          disabled={!canSubmit}
        >
          {submit.isPending ? busyLabel : "Save recipe"}
        </button>
        {progress !== null && progress < 1 && (
          <div className="h-1 overflow-hidden rounded bg-surface">
            <div
              className="h-full bg-accent transition-[width]"
              style={{ width: `${Math.round(progress * 100)}%` }}
            />
          </div>
        )}

        {submit.isError && <ErrorBox error={submit.error} />}
        <p className="hidden text-xs text-faint sm:block">
          <span className="kbd">⌘</span> <span className="kbd">↵</span> to save. You can also drop
          photos onto this box.
        </p>
      </form>

      <p className="text-xs text-faint sm:hidden">
        On Android, install Onigiri to your home screen and it appears in the share menu of
        Instagram and other apps. On iPhone, copy the link and tap Paste.
      </p>

      <section className="space-y-2">
        <h2 className="label">Recent captures</h2>
        {jobs.data && jobs.data.length === 0 && (
          <p className="text-sm text-muted">Nothing captured yet.</p>
        )}
        <ul className="card divide-y divide-line">
          {jobs.data?.slice(0, 12).map((job) => (
            <li key={job.id}>
              <Link
                to={`/j/${job.id}`}
                className="flex items-center gap-3 px-3 py-2 hover:bg-surface"
              >
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${
                    job.status === "done"
                      ? "bg-muted"
                      : job.status === "failed"
                        ? "bg-danger"
                        : job.status === "needs_input"
                          ? "bg-warn"
                          : "animate-pulse bg-warn"
                  }`}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-ink">
                    {job.stage_log.at(-1)?.note ?? job.input_url ?? "Capture"}
                  </span>
                  <span className="block truncate text-xs text-faint">
                    {job.input_url && (
                      <>
                        <IconLink className="mr-1 inline h-3 w-3" />
                        {job.input_url}
                      </>
                    )}
                  </span>
                </span>
                <span className="shrink-0 text-xs text-faint">{stageLabel(job.status)}</span>
                <span className="hidden shrink-0 text-xs text-faint sm:inline">
                  {relativeDate(job.created_at)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
