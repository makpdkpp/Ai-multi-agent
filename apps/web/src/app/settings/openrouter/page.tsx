import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";

import { LogoutButton } from "@/components/logout-button";
import { OpenRouterSettings } from "@/components/openrouter-settings";

type CurrentUser = { display_name: string; system_role: string };
type OpenRouterStatus = {
  configured: boolean;
  base_url: string;
  app_title: string;
  secret_source: string;
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
  openrouter: OpenRouterStatus;
} | null> {
  const [meResponse, statusResponse] = await Promise.all([
    apiFetch("/me"),
    apiFetch("/system/openrouter/status"),
  ]);
  if (meResponse.status === 401) return null;
  const user = (await meResponse.json()).data as CurrentUser;
  if (user.system_role !== "super_admin") redirect("/");
  if (!statusResponse.ok) throw new Error("Unable to load OpenRouter status");
  return { user, openrouter: (await statusResponse.json()).data as OpenRouterStatus };
}

export default async function OpenRouterSettingsPage() {
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
          <Link className="navItem" href="/agents">Agents</Link>
          <Link className="navItem" href="/chat">Internal Chat</Link>
          <Link className="navItem" href="/usage">Token และค่าใช้จ่าย</Link>
          <Link className="navItem active" href="/settings/openrouter">ตั้งค่า OpenRouter</Link>
        </nav>
        <div className="sidebarFooter">
          <span className="avatar">SA</span>
          <div><strong>{data.user.display_name}</strong><small>Super Admin</small></div>
        </div>
      </aside>
      <section className="content">
        <header className="topbar">
          <span>AgentDesk / <strong>ตั้งค่า OpenRouter</strong></span>
          <div className="topbarActions"><span className="environment">Local Pilot</span><LogoutButton /></div>
        </header>
        <div className="page">
          <OpenRouterSettings status={data.openrouter} />
        </div>
      </section>
    </main>
  );
}
