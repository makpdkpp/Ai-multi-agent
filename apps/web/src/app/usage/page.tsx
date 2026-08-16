import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";

import { LogoutButton } from "@/components/logout-button";
import { DepartmentUsage, UsageDashboard, UsageSummary } from "@/components/usage-dashboard";

type CurrentUser = { display_name: string; system_role: string };
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
  systemSummary: UsageSummary;
  departments: DepartmentUsage[];
} | null> {
  const [meResponse, departmentsResponse, usageResponse] = await Promise.all([
    apiFetch("/me"),
    apiFetch("/departments"),
    apiFetch("/system/usage/summary"),
  ]);
  if (meResponse.status === 401) return null;
  const user = (await meResponse.json()).data as CurrentUser;
  if (user.system_role !== "super_admin") redirect("/");
  if (!departmentsResponse.ok || !usageResponse.ok) throw new Error("Unable to load usage dashboard");
  const departments = (await departmentsResponse.json()).data as Department[];
  const summaries = await Promise.all(
    departments.map(async (department) => {
      const response = await apiFetch(`/departments/${department.id}/usage/summary`);
      if (!response.ok) throw new Error("Unable to load department usage");
      return {
        ...department,
        summary: (await response.json()).data as UsageSummary,
      };
    }),
  );
  return {
    user,
    systemSummary: (await usageResponse.json()).data as UsageSummary,
    departments: summaries,
  };
}

export default async function UsagePage() {
  const data = await loadPage();
  if (!data) redirect("/login");

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brandMark">AI</span><span>AgentDesk</span></div>
        <p className="sidebarLabel">SUPER ADMIN</p>
        <nav aria-label="เมนูหลัก">
          <Link className="navItem" href="/">ภาพรวมระบบ</Link>
          <Link className="navItem" href="/departments">แผนกทั้งหมด</Link>
          <Link className="navItem active" href="/usage">Token และค่าใช้จ่าย</Link>
        </nav>
        <div className="sidebarFooter">
          <span className="avatar">SA</span>
          <div><strong>{data.user.display_name}</strong><small>Super Admin</small></div>
        </div>
      </aside>
      <section className="content">
        <header className="topbar">
          <span>AgentDesk / <strong>Token และค่าใช้จ่าย</strong></span>
          <div className="topbarActions"><span className="environment">Local Pilot</span><LogoutButton /></div>
        </header>
        <div className="page">
          <UsageDashboard systemSummary={data.systemSummary} departments={data.departments} />
        </div>
      </section>
    </main>
  );
}
