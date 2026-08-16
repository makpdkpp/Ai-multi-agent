import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { LogoutButton } from "@/components/logout-button";

const services = [
  { name: "API", detail: "FastAPI orchestration", state: "พร้อมเชื่อมต่อ" },
  { name: "PostgreSQL", detail: "Metadata + pgvector", state: "ตั้งค่าแล้ว" },
  { name: "Redis", detail: "Queue + rate limit", state: "ตั้งค่าแล้ว" },
  { name: "MinIO", detail: "PDF + Excel storage", state: "ตั้งค่าแล้ว" },
];

const phases = [
  "บัญชีภายในและสิทธิ์ผู้ใช้",
  "Agent และแหล่งข้อมูล",
  "Internal chat และ Public widget",
  "Human Handoff",
  "Token และค่าใช้จ่าย",
];

export default async function Home() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brandMark">AI</span>
          <span>AgentDesk</span>
        </div>
        <p className="sidebarLabel">DEVELOPMENT</p>
        <nav aria-label="เมนูหลัก">
          <a className="navItem active" href="#overview">ภาพรวมระบบ</a>
          {user.system_role === "super_admin" && <a className="navItem" href="/departments">แผนกทั้งหมด</a>}
          {(user.system_role === "super_admin" || user.memberships.length > 0) && <a className="navItem" href="/agents">Agents</a>}
          {(user.system_role === "super_admin" || user.memberships.length > 0) && <a className="navItem" href="/chat">Internal Chat</a>}
          {user.system_role === "super_admin" && <a className="navItem" href="/usage">Token และค่าใช้จ่าย</a>}
          {user.system_role === "super_admin" && <a className="navItem" href="/settings/openrouter">ตั้งค่า OpenRouter</a>}
          <a className="navItem" href="#services">สถานะ Services</a>
          <a className="navItem" href="#roadmap">ลำดับการพัฒนา</a>
        </nav>
        <div className="sidebarFooter">
          <span className="avatar">AD</span>
          <div>
            <strong>Local Pilot</strong>
            <small>Phase 0 Foundation</small>
          </div>
        </div>
      </aside>

      <section className="content">
        <header className="topbar">
          <span>AgentDesk / <strong>ภาพรวมระบบ</strong></span>
          <div className="topbarActions">
            <span className="environment">{user.display_name}</span>
            <LogoutButton />
          </div>
        </header>

        <div className="page" id="overview">
          <div className="hero">
            <div>
              <p className="eyebrow">MULTI-AGENT PLATFORM</p>
              <h1>Foundation พร้อมสำหรับเริ่มพัฒนา</h1>
              <p className="subtitle">
                โครงสร้างระบบสำหรับ 8 แผนก พร้อมแยกข้อมูลด้วย tenant boundary
                และออกแบบให้ขยายระบบได้ในอนาคต
              </p>
            </div>
            <span className="statusBadge"><i /> Phase 0 กำลังดำเนินการ</span>
          </div>

          <section id="services">
            <div className="sectionTitle">
              <div>
                <h2>Service foundation</h2>
                <p>องค์ประกอบพื้นฐานที่ทำงานผ่าน Docker Compose</p>
              </div>
            </div>
            <div className="serviceGrid">
              {services.map((service) => (
                <article className="card" key={service.name}>
                  <div className="cardIcon">{service.name.slice(0, 2)}</div>
                  <div>
                    <h3>{service.name}</h3>
                    <p>{service.detail}</p>
                  </div>
                  <span className="miniStatus">{service.state}</span>
                </article>
              ))}
            </div>
          </section>

          <section className="roadmap" id="roadmap">
            <div className="sectionTitle">
              <div>
                <h2>ลำดับงานถัดไป</h2>
                <p>พัฒนาเป็น vertical slices ที่ทดสอบได้จริงทีละส่วน</p>
              </div>
            </div>
            <ol>
              {phases.map((phase, index) => (
                <li key={phase}>
                  <span>{index + 1}</span>
                  <p>{phase}</p>
                  <small>{index === 0 ? "กำลังเริ่ม" : "รอดำเนินการ"}</small>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </section>
    </main>
  );
}

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

async function getCurrentUser(): Promise<CurrentUser | null> {
  const cookieStore = await cookies();
  const response = await fetch(`${process.env.API_INTERNAL_URL ?? "http://localhost:8000/api/v1"}/me`, {
    headers: { cookie: cookieStore.toString() },
    cache: "no-store",
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("Unable to load the current user");
  const body = await response.json();
  return body.data;
}
