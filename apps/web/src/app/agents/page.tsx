import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AgentManager, AgentRecord } from "@/components/agent-manager";
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
  canManageAgents: boolean;
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
  const canManageAgents = user.system_role === "super_admin"
    || activeMemberships.some((membership) => ["department_admin", "agent_manager"].includes(membership.role));
  return { user, departments, agents: agentGroups.flat(), canManageAgents };
}

export default async function AgentsPage() {
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
          <Link className="navItem active" href="/agents">Agents</Link>
          {data.user.system_role === "super_admin" && <Link className="navItem" href="/usage">Token และค่าใช้จ่าย</Link>}
          {data.user.system_role === "super_admin" && <Link className="navItem" href="/settings/openrouter">ตั้งค่า OpenRouter</Link>}
        </nav>
        <div className="sidebarFooter">
          <span className="avatar">{data.user.system_role === "super_admin" ? "SA" : "DA"}</span>
          <div><strong>{data.user.display_name}</strong><small>{data.user.system_role === "super_admin" ? "Super Admin" : "Department User"}</small></div>
        </div>
      </aside>
      <section className="content">
        <header className="topbar">
          <span>AgentDesk / <strong>Agents</strong></span>
          <div className="topbarActions"><span className="environment">Local Pilot</span><LogoutButton /></div>
        </header>
        <div className="page">
          <AgentManager
            departments={data.departments}
            initialAgents={data.agents}
            canManageAgents={data.canManageAgents}
          />
        </div>
      </section>
    </main>
  );
}
