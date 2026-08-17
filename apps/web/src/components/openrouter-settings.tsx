"use client";

import { FormEvent, useEffect, useState } from "react";

type OpenRouterStatus = {
  configured: boolean;
  base_url: string;
  app_title: string;
  secret_source: string;
};
type Department = { id: string; name: string };
type Provider = { id: string; name: string; provider_type: string };
type Profile = { id: string; display_name: string; model_key: string; provider_name: string | null; granted?: boolean };
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
function csrfToken() {
  const cookie = document.cookie.split("; ").find((item) => item.startsWith("agentdesk_csrf="));
  return cookie ? decodeURIComponent(cookie.split("=").slice(1).join("=")) : "";
}

export function OpenRouterSettings({ status, departments }: { status: OpenRouterStatus; departments: Department[] }) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [message, setMessage] = useState("");
  const [providerId, setProviderId] = useState("");
  const [departmentId, setDepartmentId] = useState(departments[0]?.id ?? "");
  useEffect(() => {
    Promise.all([
      fetch(`${apiUrl}/llm-profiles/providers`, { credentials: "include" }),
      fetch(`${apiUrl}/llm-profiles`, { credentials: "include" }),
    ]).then(async ([providerResponse, profileResponse]) => {
      if (providerResponse.ok) {
        const data = await providerResponse.json();
        setProviders(data.data);
        setProviderId(data.data[0]?.id ?? "");
      }
      if (profileResponse.ok) setProfiles((await profileResponse.json()).data);
    });
  }, []);
  async function createProvider(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const response = await fetch(`${apiUrl}/llm-profiles/providers`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({ name: form.get("name"), provider_type: form.get("provider_type"), base_url: form.get("base_url"), secret_ref: form.get("secret_ref") || null }),
    });
    setMessage(response.ok ? "บันทึก Provider แล้ว" : "บันทึก Provider ไม่สำเร็จ");
    if (response.ok) window.location.reload();
  }
  async function createModel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const response = await fetch(`${apiUrl}/llm-profiles/models`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({ provider_id: form.get("provider_id"), model_key: form.get("model_key"), display_name: form.get("display_name") }),
    });
    setMessage(response.ok ? "บันทึก Model แล้ว" : "บันทึก Model ไม่สำเร็จ");
    if (response.ok) window.location.reload();
  }
  async function grantModel(modelId: string) {
    const response = await fetch(`${apiUrl}/llm-profiles/departments/${departmentId}/models/${modelId}`, {
      method: "PUT", credentials: "include", headers: { "X-CSRF-Token": csrfToken() },
    });
    setMessage(response.ok ? "กำหนดสิทธิ์ให้แผนกแล้ว" : "กำหนดสิทธิ์ไม่สำเร็จ");
  }
  return (
    <>
      <div className="llmHero">
        <div>
          <span className="eyebrow">LLM CONTROL CENTER</span>
          <h1>จัดการโมเดล AI</h1>
          <p>สร้าง Provider และ Model แล้วกำหนดสิทธิ์ให้แต่ละแผนกเลือกใช้งานได้</p>
        </div>
        <div className={`llmHealth ${status.configured ? "healthy" : "warning"}`}>
          <span className="healthDot" />
          <div><strong>{status.configured ? "ระบบพร้อมใช้งาน" : "ต้องตั้งค่า API key"}</strong><small>{status.base_url}</small></div>
        </div>
      </div>

      <div className="llmSteps" aria-label="ขั้นตอนตั้งค่า LLM">
        <div className="llmStep active"><b>1</b><span><strong>Provider</strong><small>แหล่งเชื่อมต่อ</small></span></div>
        <span className="stepLine" />
        <div className="llmStep"><b>2</b><span><strong>Model Profile</strong><small>รุ่นและชื่อแสดง</small></span></div>
        <span className="stepLine" />
        <div className="llmStep"><b>3</b><span><strong>สิทธิ์แผนก</strong><small>กำหนดการมองเห็น</small></span></div>
      </div>

      <section className="settingsSection">
        <div className="sectionHeading"><div><span className="sectionNumber">01</span><div><h2>สถานะการเชื่อมต่อ</h2><p>ค่าหลักของระบบที่ใช้เป็น fallback สำหรับ Agent เดิม</p></div></div><span className={`providerBadge ${status.configured ? "active" : "missing"}`}>{status.configured ? "Configured" : "Missing API key"}</span></div>
        <div className="connectionGrid">
          <article className="connectionItem"><span>Base URL</span><strong>{status.base_url}</strong></article>
          <article className="connectionItem"><span>App title</span><strong>{status.app_title}</strong></article>
          <article className="connectionItem"><span>API key</span><strong>{status.configured ? "ตั้งค่าใน server environment" : "ยังไม่ได้ตั้งค่า"}</strong></article>
        </div>
        <details className="advancedDetails">
          <summary>ดูวิธีตั้งค่า server environment</summary>
          <p className="settingsNote">API key จะไม่ถูกบันทึกผ่านหน้าเว็บ ให้ตั้งค่าในไฟล์ `.env` แล้ว restart service</p>
          <pre className="commandBox">{`${status.secret_source}=sk-or-...
OPENROUTER_BASE_URL=${status.base_url}
OPENROUTER_APP_TITLE=${status.app_title}`}</pre>
          <pre className="commandBox">docker compose up -d --build api web</pre>
        </details>
      </section>

      <section className="settingsSection">
        <div className="sectionHeading"><div><span className="sectionNumber">02</span><div><h2>สร้าง Provider</h2><p>Provider คือปลายทางที่ใช้เรียก AI เช่น OpenRouter หรือ LM Studio</p></div></div></div>
        <div className="settingsGrid">
        <article className="settingsPanel formPanel">
          <div className="panelTitle"><span className="panelIcon">↗</span><div><h3>เพิ่มแหล่งเชื่อมต่อ</h3><p>กำหนด endpoint และชื่อตัวแปร secret</p></div></div>
          <form className="stackForm" onSubmit={createProvider}>
            <label>ชื่อ Provider<input name="name" placeholder="เช่น OpenRouter Main" required /></label>
            <label>ประเภท<select name="provider_type"><option value="openrouter">OpenRouter</option><option value="ollama">Ollama / LM Studio</option><option value="vllm">vLLM</option></select></label>
            <label>Base URL<input name="base_url" placeholder="https://openrouter.ai/api/v1" required /></label>
            <label>Secret reference <span className="fieldHint">(ไม่เก็บ API key ในฐานข้อมูล)</span><input name="secret_ref" placeholder="เช่น OPENROUTER_API_KEY" /></label>
            <button className="primaryButton" type="submit">เพิ่ม Provider</button>
          </form>
        </article>
        <article className="settingsPanel infoPanel">
          <span className="infoBadge">แนวทางแนะนำ</span>
          <h3>แยก Provider ตามสภาพแวดล้อม</h3>
          <p>สร้าง OpenRouter สำหรับงาน production และ LM Studio สำหรับการทดลองภายในเครื่องได้ในหน้าเดียว</p>
          <div className="providerExample"><span className="providerLogo">OR</span><div><strong>OpenRouter</strong><small>เรียกใช้งานผ่าน cloud</small></div></div>
          <div className="providerExample"><span className="providerLogo local">LM</span><div><strong>LM Studio</strong><small>ใช้งานโมเดลภายในองค์กร</small></div></div>
        </article>
        </div>
      </section>

      <section className="settingsSection">
        <div className="sectionHeading"><div><span className="sectionNumber">03</span><div><h2>สร้าง Model Profile</h2><p>ตั้งชื่อที่ทีมเข้าใจง่าย และระบุ model key จาก Provider</p></div></div></div>
        <article className="settingsPanel formPanel">
          <form className="profileForm" onSubmit={createModel}>
            <label>Provider<select name="provider_id" value={providerId} onChange={(event) => setProviderId(event.target.value)} required><option value="">เลือก Provider</option>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.name} ({provider.provider_type})</option>)}</select></label>
            <label>ชื่อแสดง<input name="display_name" placeholder="เช่น Qwen Local 8B" required /></label>
            <label>Model key<input name="model_key" placeholder="เช่น qwen/qwen3-vl-8b" required /></label>
            <button className="primaryButton" type="submit">เพิ่ม Model Profile</button>
          </form>
        </article>
      </section>

      <section className="settingsSection">
        <div className="sectionHeading"><div><span className="sectionNumber">04</span><div><h2>กำหนดสิทธิ์ให้แผนก</h2><p>แผนกจะเห็นเฉพาะ Model ที่ได้รับอนุญาตในหน้า Agent</p></div></div></div>
        <article className="settingsPanel permissionPanel">
          <div className="permissionToolbar"><label>เลือกแผนก<select value={departmentId} onChange={(event) => setDepartmentId(event.target.value)}>{departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label><span>{profiles.length} Model profiles</span></div>
          <div className="profileList">{profiles.length === 0 ? <p className="mutedText">ยังไม่มี Model Profile กรุณาสร้างในขั้นตอนที่ 03</p> : profiles.map((profile) => <div className="profileRow" key={profile.id}><span className="modelAvatar">AI</span><div className="profileInfo"><strong>{profile.display_name}</strong><small>{profile.provider_name} · {profile.model_key}</small></div>{profile.granted ? <span className="grantBadge">อนุญาตแล้ว</span> : <button className="secondaryButton" type="button" onClick={() => grantModel(profile.id)}>อนุญาตแผนกนี้</button>}</div>)}</div>
        </article>
      </section>
      {message && <p className="formSuccess" role="status">{message}</p>}
    </>
  );
}
