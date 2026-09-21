import { api } from "@/api/client";
import { IconCamera, IconLink, IconPlus } from "@/components/Icons";
import { ErrorBox } from "@/components/ui";
import { relativeDate, stageLabel } from "@/lib/format";
import { takeShared } from "@/lib/share";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

export function Add() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

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
    mutationFn: async () => {
      const trimmed = text.trim();
      const looksLikeUrl = /^https?:\/\/\S+$/i.test(trimmed);
      if (files.length > 0) {
        return api.ingestFiles(files, looksLikeUrl ? { url: trimmed } : { text: trimmed });
      }
      return api.ingest(looksLikeUrl ? { url: trimmed } : { text: trimmed });
    },
    onSuccess: (job) => {
      setText("");
      setFiles([]);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      navigate(`/j/${job.id}`);
    },
  });

  // A share from the phone's share sheet is stashed by the service worker.
  useEffect(() => {
    if (!params.has("shared")) return;
    void (async () => {
      const shared = await takeShared();
      if (!shared) return;
      if (shared.files.length > 0) setFiles(shared.files);
      const parts = [shared.url, shared.text].filter(Boolean).join("\n").trim();
      if (parts) setText(parts);
      inputRef.current?.focus();
    })();
  }, [params]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const canSubmit = text.trim().length > 0 || files.length > 0;

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <h1 className="text-base font-semibold">Add a recipe</h1>
        <p className="text-sm text-muted">
          Paste a link or the recipe itself, or add photos of a cookbook page. On your phone, share
          straight into Onigiri from Instagram.
        </p>
      </div>

      <form
        className="card space-y-3 p-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (canSubmit) submit.mutate();
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
        <textarea
          ref={inputRef}
          className={`field min-h-32 resize-y font-mono text-[13px] ${
            dragging ? "border-accent" : ""
          }`}
          placeholder={
            "https://www.instagram.com/reel/…\n\nor paste the recipe text\n\nor drop photos here"
          }
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && canSubmit) {
              event.preventDefault();
              submit.mutate();
            }
          }}
        />

        {files.length > 0 && (
          <ul className="flex flex-wrap gap-2">
            {files.map((file, index) => (
              <li key={`${file.name}-${index}`} className="chip">
                {file.type.startsWith("video/") ? "Video" : "Photo"} · {file.name.slice(0, 28)}
                <button
                  type="button"
                  className="text-faint hover:text-ink"
                  onClick={() => setFiles(files.filter((_, i) => i !== index))}
                  aria-label={`Remove ${file.name}`}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <label className="btn btn-sm cursor-pointer">
            <IconCamera className="h-3.5 w-3.5" />
            Photos or video
            <input
              type="file"
              className="hidden"
              multiple
              accept="image/*,video/*"
              onChange={(event) => setFiles([...files, ...Array.from(event.target.files ?? [])])}
            />
          </label>
          <span className="flex-1" />
          <span className="hidden text-xs text-faint sm:inline">
            <span className="kbd">⌘</span> <span className="kbd">↵</span> to capture
          </span>
          <button
            type="submit"
            className="btn btn-primary btn-sm"
            disabled={!canSubmit || submit.isPending}
          >
            <IconPlus className="h-3.5 w-3.5" />
            {submit.isPending ? "Starting…" : "Capture"}
          </button>
        </div>

        {submit.isError && <ErrorBox error={submit.error} />}
      </form>

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
