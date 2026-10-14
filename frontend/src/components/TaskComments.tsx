import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-client";
import type { ApiComment } from "@/types";

type Props = {
  taskId: string;
  canComment: boolean;
};

export function TaskComments({ taskId, canComment }: Props) {
  const queryClient = useQueryClient();
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["comments", taskId],
    queryFn: () => apiFetch<{ comments: ApiComment[] }>(`/api/tasks/${taskId}/comments`),
  });

  const addComment = useMutation({
    mutationFn: (text: string) =>
      apiFetch<{ comment: ApiComment }>(`/api/tasks/${taskId}/comments`, {
        method: "POST",
        body: JSON.stringify({ body: text }),
      }),
    onSuccess: () => {
      setBody("");
      queryClient.invalidateQueries({ queryKey: ["comments", taskId] });
    },
    onError: (err) => setError(err instanceof Error ? err.message : "comment failed"),
  });

  const comments = data?.comments ?? [];

  return (
    <section className="mt-6 border-t border-border pt-4">
      <h3 className="text-sm font-medium mb-3">comments</h3>

      {isLoading && <p className="text-xs text-muted">loading…</p>}
      {!isLoading && comments.length === 0 && (
        <p className="text-xs text-muted">no comments yet</p>
      )}

      <ul className="space-y-3 max-h-56 overflow-y-auto mb-3">
        {comments.map((c) => (
          <li key={c.id} className="text-sm">
            <div className="flex items-baseline gap-2">
              <span className="font-medium">{c.author.name}</span>
              <time className="text-xs text-muted" dateTime={c.createdAt}>
                {new Date(c.createdAt).toLocaleString()}
              </time>
            </div>
            <p className="whitespace-pre-wrap break-words text-muted">{c.body}</p>
          </li>
        ))}
      </ul>

      {canComment ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!body.trim()) return;
            setError(null);
            addComment.mutate(body.trim());
          }}
          className="flex gap-2"
        >
          <input
            type="text"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="add a comment"
            maxLength={5000}
            className="flex-1 rounded-md bg-bg border border-border px-3 py-2 text-sm focus:border-accent focus:outline-none"
          />
          <button
            type="submit"
            disabled={addComment.isPending || !body.trim()}
            className="text-sm px-4 py-2 rounded-md bg-accent text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            post
          </button>
        </form>
      ) : (
        <p className="text-xs text-muted">viewers can read comments but not post</p>
      )}
      {error && (
        <p className="text-sm text-red-400 mt-2" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
