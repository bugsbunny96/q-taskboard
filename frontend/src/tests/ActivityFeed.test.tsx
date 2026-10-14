import { describe, it, expect } from "vitest";
import { describeActivity } from "@/components/ActivityFeed";
import type { ApiActivity } from "@/types";

const base: ApiActivity = {
  id: "a1",
  verb: "task_created",
  taskId: "t1",
  taskTitle: "Ship it",
  data: {},
  createdAt: "2026-10-14T09:00:00Z",
  actor: { id: "u1", name: "Meera Iyer", email: "m@x" },
};

describe("describeActivity", () => {
  it("describes each event type", () => {
    expect(describeActivity(base)).toBe("created “Ship it”");
    expect(describeActivity({ ...base, verb: "status_changed", data: { from: "todo", to: "done" } }))
      .toBe("moved “Ship it” from todo to done");
    expect(describeActivity({ ...base, verb: "assignee_changed", data: { from: null, to: { id: "u2", name: "Kavya" } } }))
      .toBe("assigned “Ship it” to Kavya");
    expect(describeActivity({ ...base, verb: "assignee_changed", data: { from: { id: "u2", name: "Kavya" }, to: null } }))
      .toBe("unassigned “Ship it”");
    expect(describeActivity({ ...base, verb: "comment_added" })).toBe("commented on “Ship it”");
  });
});
