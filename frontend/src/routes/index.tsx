import { createFileRoute } from "@tanstack/react-router";

import { KnowledgeInbox } from "@/components/knowledge-inbox";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "AI Knowledge Inbox" },
      { name: "description", content: "Your private library for notes, links, and grounded answers." },
    ],
  }),
  component: KnowledgeInbox,
});
