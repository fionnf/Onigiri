import { api } from "@/api/client";
import { IconAlert, IconCheck, IconRefresh } from "@/components/Icons";
import { MediaPicker } from "@/components/MediaPicker";
import { ErrorBox, Spinner } from "@/components/ui";
import { stageLabel } from "@/lib/format";
import { useJobStream } from "@/lib/hooks";
import { prepareAll } from "@/lib/images";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

const ORDER = ["queued", "fetching", "transcribing", "reading", "extracting", "done"];

export function JobView() {
  const { jobId } = useParams<{ jobId: string }>();
  const job = useJobStream(jobId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [paste, setPaste] = useState("");
  const [files, setFiles] = useState<File[]>([]);

  useEffect(() => {
    if (job?.status === "done" && job.recipe_id) {
      queryClient.invalidateQueries({ queryKey: ["recipes"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      const timer = setTimeout(() => navigate(`/r/${job.recipe_id}`), 700);
      return () => clearTimeout(timer);
    }
  }, [job?.status, job?.recipe_id, navigate, queryClient]);

  const [progress, setProgress] = useState<number | null>(null);
  const rescue = useMutation({
    mutationFn: async () => {
      if (!jobId) throw new Error("No capture");
      if (files.length > 0) {
        setProgress(0);
        const ready = await prepareAll(files);
        return api.jobInputFiles(jobId, ready, paste.trim() || undefined, (sent, total) =>
          setProgress(sent / total),
        );
      }
      return api.jobInput(jobId, paste.trim());
    },
    onSuccess: () => {
      setPaste("");
      setFiles([]);
    },
    onSettled: () => setProgress(null),
  });

  const retry = useMutation({
    mutationFn: () => api.retryJob(jobId as string),
  });

  if (!job) {
    return (
      <div className="mx-auto max-w-2xl">
        <Spinner label="Opening the capture…" />
      </div>
    );
  }

  const reachedIndex = ORDER.indexOf(job.status);

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-center gap-2">
        <h1 className="flex-1 text-base font-semibold">
          {job.status === "done" ? "Captured" : "Capturing"}
        </h1>
        <Link to="/add" className="btn btn-sm">
          Add another
        </Link>
      </div>

      {job.input_url && (
        <p className="truncate text-xs text-faint">
          <a href={job.input_url} target="_blank" rel="noreferrer" className="link">
            {job.input_url}
          </a>
        </p>
      )}

      <ol className="card divide-y divide-line">
        {job.stage_log.map((entry, index) => (
          <li key={`${entry.at}-${index}`} className="flex gap-3 px-3 py-2">
            <span className="mt-0.5">
              {entry.stage === "failed" || entry.stage === "needs_input" ? (
                <IconAlert className="h-4 w-4 text-warn" />
              ) : (
                <IconCheck className="h-4 w-4 text-muted" />
              )}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm text-ink">{entry.note}</span>
              <span className="block text-xs text-faint">{stageLabel(entry.stage)}</span>
            </span>
          </li>
        ))}
        {reachedIndex >= 0 && reachedIndex < ORDER.length - 1 && (
          <li className="flex items-center gap-3 px-3 py-2">
            <Spinner label={`${stageLabel(job.status)}…`} />
          </li>
        )}
      </ol>

      {job.status === "needs_input" && (
        <div className="card space-y-3 border-warn/40 p-3">
          <div className="flex items-start gap-2">
            <IconAlert className="mt-0.5 h-4 w-4 text-warn" />
            <p className="flex-1 text-sm text-ink">{job.needs_input_reason}</p>
          </div>

          <textarea
            className="field min-h-28"
            placeholder="Paste the caption or the recipe text here…"
            value={paste}
            onChange={(event) => setPaste(event.target.value)}
          />

          <MediaPicker
            files={files}
            onChange={setFiles}
            chooseLabel="Add the video or a screenshot"
          />

          <button
            type="button"
            className="btn btn-primary w-full sm:ml-auto sm:flex sm:w-auto"
            disabled={(!paste.trim() && files.length === 0) || rescue.isPending}
            onClick={() => rescue.mutate()}
          >
            {rescue.isPending
              ? progress !== null && progress < 1
                ? `Uploading ${Math.round(progress * 100)}%`
                : "Sending…"
              : "Continue"}
          </button>
          {rescue.isError && <ErrorBox error={rescue.error} />}
        </div>
      )}

      {job.status === "failed" && (
        <div className="card space-y-3 border-danger/40 p-3">
          <p className="text-sm text-ink">{job.error}</p>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => retry.mutate()}
            disabled={retry.isPending}
          >
            <IconRefresh className="h-3.5 w-3.5" />
            Try again
          </button>
        </div>
      )}

      {job.status === "done" && job.recipe_id && (
        <Link to={`/r/${job.recipe_id}`} className="btn btn-primary">
          Open the recipe
        </Link>
      )}
    </div>
  );
}
