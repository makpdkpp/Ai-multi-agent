import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Department, DepartmentManager } from "@/components/department-manager";
import { LogoutButton } from "@/components/logout-button";

type CurrentUser = { display_name: string; system_role: string };
const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000/api/v1";

async function loadPage(): Promise<{ user: CurrentUser; departments: Department[] } | null> {
  const cookieStore = await cookies();
  const headers = { cookie: cookieStore.toString() };
  const [meResponse, departmentsResponse] = await Promise.all([
    fetch(`${apiUrl}/me`, { headers, cache: "no-store" }),
    fetch(`${apiUrl}/departments`, { headers, cache: "no-store" }),
  ]);
  if (meResponse.status === 401) return null;
  const user = (await meResponse.json()).data as CurrentUser;
  if (user.system_role !== "super_admin") redirect("/");
  if (!departmentsResponse.ok) throw new Error("Unable to load departments");
  return { user, departments: (await departmentsResponse.json()).data };
}

export default async function DepartmentsPage() {
  const data = await loadPage();
  if (!data) redirect("/login");

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brandMark">AI</span><span>AgentDesk</span></div>
        <p className="sidebarLabel">SUPER ADMIN</p>
        <nav aria-label="เมนูหลัก">
          <Link className="navItem" href="/">ภาพรวมระบบ</Link>
          <Link className="navItem active" href="/departments">แผนกทั้งหมด</Link>
          <Link className="navItem" href="/agents">Agents</Link>
          <Link className="navItem" href="/usage">Token และค่าใช้จ่าย</Link>
          <Link className="navItem" href="/settings/openrouter">ตั้งค่า OpenRouter</Link>
        </nav>
        <div className="sidebarFooter"><span className="avatar">SA</span><div><strong>{data.user.display_name}</strong><small>Super Admin</small></div></div>
      </aside>
      <section className="content">
        <header className="topbar"><span>AgentDesk / <strong>แผนกทั้งหมด</strong></span><div className="topbarActions"><span className="environment">Local Pilot</span><LogoutButton /></div></header>
        <div className="page"><DepartmentManager initialDepartments={data.departments} /></div>
      </section>
    </main>
  );
}
