import type { ReactElement } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TaskComments } from "@/components/TaskComments";

const comments = [
  { id: "c1", taskId: "t1", body: "first", createdAt: "2026-10-14T08:00:00Z", author: { id: "u1", name: "Meera Iyer", email: "m@x" } },
  { id: "c2", taskId: "t1", body: "second", createdAt: "2026-10-14T09:00:00Z", author: { id: "u2", name: "Kavya Reddy", email: "k@x" } },
];

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("<TaskComments />", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          return new Response(JSON.stringify({ comment: comments[0] }), { status: 201 });
        }
        return new Response(JSON.stringify({ comments }), { status: 200 });
      }),
    );
  });

  it("lists comments in order with author names", async () => {
    renderWithClient(<TaskComments taskId="t1" canComment />);
    const items = await screen.findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Meera Iyer");
    expect(items[0]).toHaveTextContent("first");
    expect(items[1]).toHaveTextContent("second");
  });

  it("hides the form for viewers", async () => {
    renderWithClient(<TaskComments taskId="t1" canComment={false} />);
    await screen.findAllByRole("listitem");
    expect(screen.queryByPlaceholderText("add a comment")).not.toBeInTheDocument();
    expect(screen.getByText(/viewers can read comments/)).toBeInTheDocument();
  });

  it("posts a new comment", async () => {
    renderWithClient(<TaskComments taskId="t1" canComment />);
    fireEvent.change(screen.getByPlaceholderText("add a comment"), { target: { value: "hello" } });
    fireEvent.click(screen.getByText("post"));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/tasks/t1/comments",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ body: "hello" }) }),
      ),
    );
  });
});
