import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-client";
import type { ApiActivity } from "@/types";

function personName(value: ApiActivity["data"]["to"]): string {
  if (value && typeof value === "object") return value.name;
  return "nobody";
}

export function describeActivity(a: ApiActivity): string {
  const task = `“${a.taskTitle}”`;
  switch (a.verb) {
    case "task_created":
      return `created ${task}`;
    case "status_changed":
      return `moved ${task} from ${String(a.data.from)} to ${String(a.data.to)}`;
    case "assignee_changed":
      return a.data.to
        ? `assigned ${task} to ${personName(a.data.to)}`
        : `unassigned ${task}`;
    case "comment_added":
      return `commented on ${task}`;
    default:
      return `updated ${task}`;
  }
}

export function ActivityFeed({ projectId }: { projectId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["activity", projectId],
    queryFn: () =>
      apiFetch<{ activity: ApiActivity[] }>(`/api/projects/${projectId}/activity?limit=30`),
  });

  const items = data?.activity ?? [];

  return (
    <section className="mt-10">
      <h2 className="text-sm font-medium mb-3">recent activity</h2>
      <div className="bg-surface border border-border rounded-lg">
        {isLoading && <p className="px-4 py-3 text-xs text-muted">loading…</p>}
        {error && (
          <p className="px-4 py-3 text-xs text-red-400">
            {error instanceof Error ? error.message : "failed to load activity"}
          </p>
        )}
        {!isLoading && !error && items.length === 0 && (
          <p className="px-4 py-3 text-xs text-muted">no activity yet</p>
        )}
        <ul className="divide-y divide-border">
          {items.map((a) => (
            <li key={a.id} className="px-4 py-3 flex items-baseline justify-between gap-4 text-sm">
              <span>
                <span className="font-medium">{a.actor.name}</span>{" "}
                <span className="text-muted">{describeActivity(a)}</span>
              </span>
              <time className="text-xs text-muted shrink-0" dateTime={a.createdAt}>
                {new Date(a.createdAt).toLocaleString()}
              </time>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
