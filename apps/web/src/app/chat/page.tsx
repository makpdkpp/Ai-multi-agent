import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";

import { ChatWorkspace } from "@/components/chat-workspace";
import { LogoutButton } from "@/components/logout-button";

type CurrentUser = {
  display_name: string;
  system_role: string;
  memberships: Array<{
    department_id: string;
    department_name: string;
    role: string;
    status: string;
  }>;
};
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

const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000/api/v1";

async function apiFetch(path: string) {
  const cookieStore = await cookies();
  return fetch(`${apiUrl}${path}`, {
    headers: { cookie: cookieStore.toString() },
    cache: "no-store",
  });
}

async function loadPage(): Promise<{
  user: CurrentUser;
  departments: Department[];
  agents: AgentRecord[];
  conversations: Conversation[];
} | null> {
  const meResponse = await apiFetch("/me");
  if (meResponse.status === 401) return null;
  const user = (await meResponse.json()).data as CurrentUser;
  const activeMemberships = user.memberships.filter((membership) => membership.status === "active");
  if (user.system_role !== "super_admin" && activeMemberships.length === 0) redirect("/");

  const departments = user.system_role === "super_admin"
    ? await (async () => {
        const response = await apiFetch("/departments");
        if (!response.ok) throw new Error("Unable to load departments");
        return (await response.json()).data as Department[];
      })()
    : activeMemberships.map((membership) => ({
        id: membership.department_id,
        code: membership.department_id,
        name: membership.department_name,
      }));

  const agentGroups = await Promise.all(
    departments.map(async (department) => {
      const response = await apiFetch(`/departments/${department.id}/agents`);
      if (!response.ok) throw new Error("Unable to load agents");
      return (await response.json()).data as AgentRecord[];
    }),
  );
  const conversationsResponse = await apiFetch("/chat/conversations");
  if (!conversationsResponse.ok) throw new Error("Unable to load conversations");
  const conversations = (await conversationsResponse.json()).data as Conversation[];
  if (conversations[0]) {
    const activeConversationResponse = await apiFetch(`/chat/conversations/${conversations[0].id}`);
    if (activeConversationResponse.ok) {
      conversations[0] = (await activeConversationResponse.json()).data as Conversation;
    }
  }

  return {
    user,
    departments,
    agents: agentGroups.flat(),
    conversations,
  };
}

export default async function ChatPage() {
  const data = await loadPage();
  if (!data) redirect("/login");

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brandMark">AI</span><span>AgentDesk</span></div>
        <p className="sidebarLabel">{data.user.system_role === "super_admin" ? "SUPER ADMIN" : "DEPARTMENT"}</p>
        <nav aria-label="เมนูหลัก">
          <Link className="navItem" href="/">ภาพรวมระบบ</Link>
          {data.user.system_role === "super_admin" && <Link className="navItem" href="/departments">แผนกทั้งหมด</Link>}
          <Link className="navItem" href="/agents">Agents</Link>
          <Link className="navItem active" href="/chat">Internal Chat</Link>
          {data.user.system_role === "super_admin" && <Link className="navItem" href="/usage">Token และค่าใช้จ่าย</Link>}
          {data.user.system_role === "super_admin" && <Link className="navItem" href="/settings/openrouter">ตั้งค่า OpenRouter</Link>}
        </nav>
        <div className="sidebarFooter">
          <span className="avatar">{data.user.system_role === "super_admin" ? "SA" : "DU"}</span>
          <div><strong>{data.user.display_name}</strong><small>Internal Chat</small></div>
        </div>
      </aside>
      <section className="content">
        <header className="topbar">
          <span>AgentDesk / <strong>Internal Chat</strong></span>
          <div className="topbarActions"><span className="environment">Local Pilot</span><LogoutButton /></div>
        </header>
        <div className="page">
          <ChatWorkspace
            departments={data.departments}
            agents={data.agents}
            initialConversations={data.conversations}
          />
        </div>
      </section>
    </main>
  );
}
