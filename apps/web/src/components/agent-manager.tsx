"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

type Department = {
  id: string;
  code: string;
  name: string;
};

export type AgentPermission = {
  channel: "email" | "internal_chat" | "public_widget";
  enabled: boolean;
  allow_anonymous: boolean;
};

export type AgentRecord = {
  id: string;
  department_id: string;
  slug: string;
  name: string;
  description: string | null;
  status: "draft" | "active" | "paused" | "disabled";
  default_language: string;
  handoff_enabled: boolean;
  confidence_threshold: string;
  system_prompt: string;
  response_style: string | null;
  llm_config: {
    model_key: string;
    temperature: string;
    top_p: string;
    max_output_tokens: number;
  };
  permissions: AgentPermission[];
};

function csrfToken(): string {
  const cookie = document.cookie.split("; ").find((item) => item.startsWith("agentdesk_csrf="));
  return cookie ? decodeURIComponent(cookie.split("=").slice(1).join("=")) : "";
}

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

function channelEnabled(agent: AgentRecord, channel: AgentPermission["channel"]) {
  return agent.permissions.find((permission) => permission.channel === channel)?.enabled ?? false;
}

export function AgentManager({
  departments,
  initialAgents,
}: {
  departments: Department[];
  initialAgents: AgentRecord[];
}) {
  const router = useRouter();
  const [agents, setAgents] = useState(initialAgents);
  const [departmentId, setDepartmentId] = useState(departments[0]?.id ?? "");
  const [editingAgent, setEditingAgent] = useState<AgentRecord | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const selectedAgents = useMemo(
    () => agents.filter((agent) => agent.department_id === departmentId),
    [agents, departmentId],
  );

  function openEdit(agent: AgentRecord) {
    setError("");
    setEditingAgent(agent);
    setDepartmentId(agent.department_id);
  }

  function resetForm(form?: HTMLFormElement) {
    setEditingAgent(null);
    form?.reset();
  }

  async function saveAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("save-agent");
    setError("");
    const form = new FormData(event.currentTarget);
    const payload = {
      slug: form.get("slug"),
      name: form.get("name"),
      description: form.get("description") || null,
      status: form.get("status"),
      default_language: "th",
      handoff_enabled: form.get("handoff_enabled") === "on",
      confidence_threshold: form.get("confidence_threshold"),
      system_prompt: form.get("system_prompt"),
      response_style: form.get("response_style") || null,
      llm_config: {
        model_key: form.get("model_key"),
        temperature: form.get("temperature"),
        top_p: form.get("top_p"),
        max_output_tokens: Number(form.get("max_output_tokens")),
      },
      permissions: [
        { channel: "internal_chat", enabled: true, allow_anonymous: false },
        {
          channel: "public_widget",
          enabled: form.get("public_widget") === "on",
          allow_anonymous: form.get("public_anonymous") === "on",
        },
        { channel: "email", enabled: form.get("email") === "on", allow_anonymous: false },
      ],
    };
    const endpoint = editingAgent
      ? `${apiUrl}/agents/${editingAgent.id}`
      : `${apiUrl}/departments/${departmentId}/agents`;
    const response = await fetch(endpoint, {
      method: editingAgent ? "PATCH" : "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify(editingAgent ? { ...payload, slug: undefined } : payload),
    });
    if (response.ok) {
      const body = await response.json();
      setAgents((current) => {
        const next = editingAgent
          ? current.map((agent) => agent.id === body.data.id ? body.data : agent)
          : [...current, body.data];
        return next.sort((a, b) => a.name.localeCompare(b.name, "th"));
      });
      resetForm(event.currentTarget);
      router.refresh();
    } else {
      const body = await response.json().catch(() => null);
      setError(response.status === 409 ? "slug นี้ถูกใช้ในแผนกแล้ว" : body?.detail ?? "บันทึก Agent ไม่สำเร็จ");
    }
    setBusy(null);
  }

  async function changeStatus(agent: AgentRecord, status: AgentRecord["status"]) {
    setBusy(agent.id);
    setError("");
    const response = await fetch(`${apiUrl}/agents/${agent.id}`, {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({ status }),
    });
    if (response.ok) {
      const body = await response.json();
      setAgents((current) => current.map((item) => item.id === agent.id ? body.data : item));
      router.refresh();
    } else {
      setError("เปลี่ยนสถานะ Agent ไม่สำเร็จ");
    }
    setBusy(null);
  }

  return (
    <>
      <div className="departmentToolbar">
        <div>
          <h1>Agents</h1>
          <p>กำหนด Agent แยกตามแผนก พร้อม prompt, channel และ LLM config</p>
        </div>
        <select className="toolbarSelect" value={departmentId} onChange={(event) => setDepartmentId(event.target.value)}>
          {departments.map((department) => (
            <option key={department.id} value={department.id}>{department.name}</option>
          ))}
        </select>
      </div>

      {error && <p className="formError" role="alert">{error}</p>}

      <form className="agentForm" key={editingAgent?.id ?? "new-agent"} onSubmit={saveAgent}>
        <div className="agentFormGrid">
          <label>
            Slug
            <input name="slug" placeholder="sales-support" defaultValue={editingAgent?.slug ?? ""} disabled={Boolean(editingAgent)} required />
          </label>
          <label>
            ชื่อ Agent
            <input name="name" placeholder="Sales Support Agent" defaultValue={editingAgent?.name ?? ""} required />
          </label>
          <label>
            สถานะ
            <select name="status" defaultValue={editingAgent?.status ?? "draft"}>
              <option value="draft">Draft</option>
              <option value="active">Active</option>
              <option value="paused">Paused</option>
              <option value="disabled">Disabled</option>
            </select>
          </label>
          <label>
            Model
            <input name="model_key" defaultValue={editingAgent?.llm_config.model_key ?? "openai/gpt-4o-mini"} required />
          </label>
          <label>
            Temperature
            <input name="temperature" type="number" min="0" max="2" step="0.01" defaultValue={editingAgent?.llm_config.temperature ?? "0.20"} required />
          </label>
          <label>
            Max output
            <input name="max_output_tokens" type="number" min="1" max="200000" defaultValue={editingAgent?.llm_config.max_output_tokens ?? 1024} required />
          </label>
        </div>
        <input name="top_p" type="hidden" value={editingAgent?.llm_config.top_p ?? "1.00"} />
        <label>
          คำอธิบาย
          <input name="description" placeholder="ใช้ตอบคำถามงานขายภายใน" defaultValue={editingAgent?.description ?? ""} />
        </label>
        <label>
          System prompt
          <textarea name="system_prompt" rows={5} defaultValue={editingAgent?.system_prompt ?? ""} required />
        </label>
        <label>
          Response style
          <textarea name="response_style" rows={3} defaultValue={editingAgent?.response_style ?? ""} />
        </label>
        <div className="agentToggles">
          <label><input name="handoff_enabled" type="checkbox" defaultChecked={editingAgent?.handoff_enabled ?? true} /> Human handoff</label>
          <label><input name="public_widget" type="checkbox" defaultChecked={editingAgent ? channelEnabled(editingAgent, "public_widget") : false} /> Public widget</label>
          <label><input name="public_anonymous" type="checkbox" defaultChecked /> Anonymous public</label>
          <label><input name="email" type="checkbox" defaultChecked={editingAgent ? channelEnabled(editingAgent, "email") : false} /> Email</label>
          <label>
            Confidence
            <input name="confidence_threshold" type="number" min="0" max="1" step="0.01" defaultValue={editingAgent?.confidence_threshold ?? "0.60"} />
          </label>
        </div>
        <div className="formActions">
          <button className="primaryButton" type="submit" disabled={busy === "save-agent"}>
            {busy === "save-agent" ? "กำลังบันทึก..." : editingAgent ? "บันทึก Agent" : "สร้าง Agent"}
          </button>
          {editingAgent && <button className="secondaryButton" type="button" onClick={() => resetForm()}>ยกเลิกแก้ไข</button>}
        </div>
      </form>

      <section className="departmentTableWrap">
        {selectedAgents.length === 0 ? (
          <div className="emptyState"><strong>ยังไม่มี Agent ในแผนกนี้</strong><p>สร้าง Agent แรกเพื่อเตรียมต่อ OpenRouter และ data sources</p></div>
        ) : (
          <table className="departmentTable">
            <thead><tr><th>Agent</th><th>Model</th><th>Channels</th><th>Handoff</th><th>สถานะ</th><th /></tr></thead>
            <tbody>{selectedAgents.map((agent) => (
              <tr key={agent.id}>
                <td><strong>{agent.name}</strong><small>{agent.slug}</small></td>
                <td><code>{agent.llm_config.model_key}</code><small>temp {agent.llm_config.temperature}</small></td>
                <td>
                  {agent.permissions.filter((permission) => permission.enabled).map((permission) => permission.channel).join(", ")}
                </td>
                <td>{agent.handoff_enabled ? `เปิด · ${Number(agent.confidence_threshold).toFixed(2)}` : "ปิด"}</td>
                <td><span className={`departmentStatus ${agent.status}`}>{agent.status}</span></td>
                <td className="departmentActions">
                  <button className="secondaryButton" type="button" onClick={() => openEdit(agent)}>แก้ไข</button>
                  <button className="secondaryButton" type="button" disabled={busy === agent.id} onClick={() => changeStatus(agent, agent.status === "active" ? "paused" : "active")}>
                    {agent.status === "active" ? "พัก" : "เปิดใช้"}
                  </button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </section>
    </>
  );
}
