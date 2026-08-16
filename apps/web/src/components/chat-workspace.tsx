"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

type Department = { id: string; code: string; name: string };
type AgentRecord = {
  id: string;
  department_id: string;
  name: string;
  slug: string;
  status: string;
};
type ChatMessage = {
  id: string;
  sender_type: "user" | "assistant" | "system";
  content: string;
  usage?: {
    input_tokens: number;
    output_tokens: number;
    display_cost_usd: string;
    display_cost_thb: string;
  } | null;
  created_at: string;
};
type Conversation = {
  id: string;
  department_id: string;
  agent_id: string;
  agent_name: string | null;
  title: string;
  last_message_at: string | null;
  usage: {
    input_tokens: number;
    output_tokens: number;
    requests: number;
    display_cost_usd: string;
    display_cost_thb: string;
  };
  messages?: ChatMessage[];
};

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

function csrfToken(): string {
  const cookie = document.cookie.split("; ").find((item) => item.startsWith("agentdesk_csrf="));
  return cookie ? decodeURIComponent(cookie.split("=").slice(1).join("=")) : "";
}

export function ChatWorkspace({
  departments,
  agents,
  initialConversations,
}: {
  departments: Department[];
  agents: AgentRecord[];
  initialConversations: Conversation[];
}) {
  const router = useRouter();
  const [departmentId, setDepartmentId] = useState(departments[0]?.id ?? "");
  const departmentAgents = useMemo(
    () => agents.filter((agent) => agent.department_id === departmentId && agent.status === "active"),
    [agents, departmentId],
  );
  const [agentId, setAgentId] = useState(departmentAgents[0]?.id ?? agents[0]?.id ?? "");
  const [conversations, setConversations] = useState(initialConversations);
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(
    initialConversations[0] ?? null,
  );
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const visibleConversations = conversations.filter((conversation) => (
    !departmentId || conversation.department_id === departmentId
  ));
  const activeAgent = agents.find((agent) => agent.id === agentId);
  const messages = activeConversation?.messages ?? [];

  async function loadConversation(conversation: Conversation) {
    setError("");
    setBusy(true);
    const response = await fetch(`${apiUrl}/chat/conversations/${conversation.id}`, {
      credentials: "include",
    });
    const body = await response.json().catch(() => null);
    if (response.ok) {
      setActiveConversation(body.data);
      setAgentId(body.data.agent_id);
      setDepartmentId(body.data.department_id);
    } else {
      setError(body?.detail ?? "โหลดบทสนทนาไม่สำเร็จ");
    }
    setBusy(false);
  }

  async function createConversation() {
    if (!agentId) {
      setError("กรุณาเลือก Agent ก่อนเริ่มแชท");
      return null;
    }
    const response = await fetch(`${apiUrl}/chat/conversations`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({ agent_id: agentId }),
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      setError(body?.detail ?? "สร้างบทสนทนาไม่สำเร็จ");
      return null;
    }
    setConversations((current) => [body.data, ...current]);
    setActiveConversation(body.data);
    return body.data as Conversation;
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (!content) return;
    setBusy(true);
    setError("");
    setDraft("");
    const conversation = activeConversation ?? await createConversation();
    if (!conversation) {
      setBusy(false);
      setDraft(content);
      return;
    }
    const response = await fetch(`${apiUrl}/chat/conversations/${conversation.id}/messages`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({ content }),
    });
    const body = await response.json().catch(() => null);
    if (response.ok) {
      setActiveConversation(body.data.conversation);
      setConversations((current) => {
        const next = current.filter((item) => item.id !== body.data.conversation.id);
        return [body.data.conversation, ...next];
      });
      router.refresh();
    } else {
      setDraft(content);
      const detail = body?.detail;
      setError(typeof detail === "string" ? detail : detail?.message ?? "ส่งข้อความไม่สำเร็จ");
    }
    setBusy(false);
  }

  return (
    <div className="chatLayout">
      <aside className="chatSidebar">
        <div className="chatFilters">
          <label>
            แผนก
            <select value={departmentId} onChange={(event) => {
              setDepartmentId(event.target.value);
              const nextAgent = agents.find((agent) => agent.department_id === event.target.value && agent.status === "active");
              if (nextAgent) setAgentId(nextAgent.id);
            }}>
              {departments.map((department) => (
                <option key={department.id} value={department.id}>{department.name}</option>
              ))}
            </select>
          </label>
          <label>
            Agent
            <select value={agentId} onChange={(event) => setAgentId(event.target.value)}>
              {departmentAgents.map((agent) => (
                <option key={agent.id} value={agent.id}>{agent.name} ({agent.slug})</option>
              ))}
            </select>
          </label>
          <button className="primaryButton" type="button" onClick={() => {
            setActiveConversation(null);
            setError("");
          }}>
            เริ่มแชทใหม่
          </button>
        </div>
        <div className="conversationList">
          {visibleConversations.length === 0 ? (
            <p className="mutedText">ยังไม่มีประวัติแชท</p>
          ) : visibleConversations.map((conversation) => (
            <button
              className={`conversationItem ${activeConversation?.id === conversation.id ? "active" : ""}`}
              key={conversation.id}
              type="button"
              onClick={() => loadConversation(conversation)}
            >
              <strong>{conversation.title}</strong>
              <small>{conversation.agent_name ?? "Agent"} · {conversation.usage.requests} request</small>
              <small>{conversation.usage.display_cost_usd} USD / {conversation.usage.display_cost_thb} THB</small>
            </button>
          ))}
        </div>
      </aside>

      <section className="chatPanel">
        <div className="chatHeader">
          <div>
            <h1>{activeConversation?.title ?? "แชทใหม่"}</h1>
            <p>{activeAgent ? `กำลังใช้ ${activeAgent.name}` : "เลือก Agent เพื่อเริ่มแชท"}</p>
          </div>
          <div className="chatUsage">
            <span>รวม {activeConversation?.usage.requests ?? 0} requests</span>
            <strong>{activeConversation?.usage.display_cost_usd ?? "0"} USD</strong>
            <small>{activeConversation?.usage.display_cost_thb ?? "0"} THB</small>
          </div>
        </div>

        {error && <p className="formError" role="alert">{error}</p>}

        <div className="messageList">
          {messages.length === 0 ? (
            <div className="emptyState">
              <strong>พร้อมเริ่ม internal chat</strong>
              <p>ส่งข้อความแรก ระบบจะสร้าง conversation และบันทึก token/cost อัตโนมัติ</p>
            </div>
          ) : messages.map((message) => (
            <article className={`chatMessage ${message.sender_type}`} key={message.id}>
              <small>{message.sender_type === "assistant" ? "AI" : "คุณ"}</small>
              <p>{message.content}</p>
              {message.usage && (
                <div className="messageCost">
                  Cost: {message.usage.display_cost_usd} USD / {message.usage.display_cost_thb} THB
                  <span>
                    Tokens: {message.usage.input_tokens} input / {message.usage.output_tokens} output
                  </span>
                </div>
              )}
            </article>
          ))}
        </div>

        <form className="chatComposer" onSubmit={sendMessage}>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="พิมพ์ข้อความถึง Agent..."
            rows={3}
            disabled={busy}
          />
          <button className="primaryButton" type="submit" disabled={busy || !draft.trim()}>
            {busy ? "กำลังส่ง..." : "ส่ง"}
          </button>
        </form>
      </section>
    </div>
  );
}
