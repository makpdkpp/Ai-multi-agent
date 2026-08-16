"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

type Department = { id: string; code: string; name: string };
type AgentRecord = { id: string; department_id: string; name: string; slug: string; status: string };
type SheetPreview = {
  name: string;
  row_count: number;
  column_count: number;
  columns: string[];
  preview_rows: Record<string, unknown>[];
};
type SourceFile = {
  id: string;
  original_name: string;
  size_bytes: number;
  status: string;
  version: number;
  metadata: { sheets?: SheetPreview[] };
  indexed_at: string | null;
};
export type DataSourceRecord = {
  id: string;
  department_id: string;
  name: string;
  source_type: "excel" | "mysql" | "pdf";
  status: string;
  files: SourceFile[];
  created_at: string;
  updated_at: string;
};
type AgentSource = {
  id: string;
  agent_id: string;
  data_source_id: string;
  data_source_name: string | null;
  source_type: string | null;
  status: string | null;
  access_scope: string;
  priority: number;
  enabled: boolean;
};

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

function csrfToken(): string {
  const cookie = document.cookie.split("; ").find((item) => item.startsWith("agentdesk_csrf="));
  return cookie ? decodeURIComponent(cookie.split("=").slice(1).join("=")) : "";
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function DataSourceManager({
  departments,
  agents,
  initialSources,
  canManageSources,
}: {
  departments: Department[];
  agents: AgentRecord[];
  initialSources: DataSourceRecord[];
  canManageSources: boolean;
}) {
  const router = useRouter();
  const [departmentId, setDepartmentId] = useState(departments[0]?.id ?? "");
  const [sources, setSources] = useState(initialSources);
  const departmentAgents = useMemo(
    () => agents.filter((agent) => agent.department_id === departmentId),
    [agents, departmentId],
  );
  const [agentId, setAgentId] = useState(departmentAgents[0]?.id ?? "");
  const [agentSources, setAgentSources] = useState<AgentSource[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const visibleSources = sources.filter((source) => source.department_id === departmentId);

  useEffect(() => {
    if (!agentId) return;
    let ignore = false;
    async function loadAgentSources() {
      const response = await fetch(`${apiUrl}/agents/${agentId}/data-sources`, {
        credentials: "include",
      });
      const body = await response.json().catch(() => null);
      if (!ignore && response.ok) setAgentSources(body.data);
    }
    loadAgentSources();
    return () => {
      ignore = true;
    };
  }, [agentId]);

  function selectDepartment(nextDepartmentId: string) {
    const nextAgent = agents.find((agent) => agent.department_id === nextDepartmentId);
    setDepartmentId(nextDepartmentId);
    setAgentId(nextAgent?.id ?? "");
    setAgentSources([]);
    setError("");
    setNotice("");
  }

  function selectAgent(nextAgentId: string) {
    setAgentId(nextAgentId);
    setAgentSources([]);
    setError("");
    setNotice("");
  }

  async function uploadExcel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("upload");
    setError("");
    setNotice("");
    const form = new FormData(event.currentTarget);
    const response = await fetch(`${apiUrl}/departments/${departmentId}/data-sources/excel`, {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": csrfToken() },
      body: form,
    });
    const body = await response.json().catch(() => null);
    if (response.ok) {
      setSources((current) => [body.data, ...current.filter((source) => source.id !== body.data.id)]);
      setNotice("อัปโหลดและอ่านโครงสร้าง Excel สำเร็จ");
      event.currentTarget.reset();
      router.refresh();
    } else {
      setError(body?.detail ?? "อัปโหลด Excel ไม่สำเร็จ");
    }
    setBusy(null);
  }

  async function attachSource(source: DataSourceRecord) {
    if (!agentId) {
      setError("กรุณาเลือก Agent ก่อน attach source");
      return;
    }
    setBusy(`attach-${source.id}`);
    setError("");
    setNotice("");
    const response = await fetch(`${apiUrl}/agents/${agentId}/data-sources`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({
        data_source_id: source.id,
        access_scope: "internal_only",
        priority: 100,
        enabled: true,
      }),
    });
    const body = await response.json().catch(() => null);
    if (response.ok) {
      setAgentSources((current) => [body.data, ...current]);
      setNotice(`เชื่อม ${source.name} เข้ากับ Agent แล้ว`);
    } else {
      setError(response.status === 409 ? "Source นี้เชื่อมกับ Agent อยู่แล้ว" : body?.detail ?? "Attach source ไม่สำเร็จ");
    }
    setBusy(null);
  }

  async function detachSource(link: AgentSource) {
    setBusy(`detach-${link.data_source_id}`);
    setError("");
    setNotice("");
    const response = await fetch(`${apiUrl}/agents/${agentId}/data-sources/${link.data_source_id}`, {
      method: "DELETE",
      credentials: "include",
      headers: { "X-CSRF-Token": csrfToken() },
    });
    if (response.ok) {
      setAgentSources((current) => current.filter((item) => item.id !== link.id));
      setNotice("ถอด source ออกจาก Agent แล้ว");
    } else {
      setError("Detach source ไม่สำเร็จ");
    }
    setBusy(null);
  }

  return (
    <>
      <div className="departmentToolbar">
        <div>
          <h1>Data Sources</h1>
          <p>เริ่มจาก Excel: upload workbook, อ่าน sheet/columns และเชื่อมเข้ากับ Agent</p>
        </div>
        <select className="toolbarSelect" value={departmentId} onChange={(event) => selectDepartment(event.target.value)}>
          {departments.map((department) => (
            <option key={department.id} value={department.id}>{department.name}</option>
          ))}
        </select>
      </div>

      {error && <p className="formError" role="alert">{error}</p>}
      {notice && <p className="formSuccess" role="status">{notice}</p>}

      {canManageSources && (
        <form className="agentForm" onSubmit={uploadExcel}>
          <div className="agentFormGrid">
            <label>
              ชื่อ Excel Source
              <input name="name" placeholder="Sales workbook" required />
            </label>
            <label>
              ไฟล์ Excel
              <input name="file" type="file" accept=".xlsx,.xlsm,.csv" required />
            </label>
          </div>
          <button className="primaryButton" type="submit" disabled={busy === "upload"}>
            {busy === "upload" ? "กำลังอัปโหลด..." : "อัปโหลด Excel"}
          </button>
        </form>
      )}

      <section className="dataSourceAttachBar">
        <label>
          เลือก Agent เพื่อเชื่อม Data Source
          <select value={agentId} onChange={(event) => selectAgent(event.target.value)}>
            {departmentAgents.map((agent) => (
              <option key={agent.id} value={agent.id}>{agent.name} ({agent.slug})</option>
            ))}
          </select>
        </label>
        <div>
          <strong>{agentSources.length}</strong>
          <span> source attached</span>
        </div>
      </section>

      <section className="dataSourceGrid">
        {visibleSources.length === 0 ? (
          <div className="emptyState"><strong>ยังไม่มี Excel source</strong><p>อัปโหลดไฟล์แรกเพื่อเริ่มเชื่อมข้อมูลให้ Agent</p></div>
        ) : visibleSources.map((source) => {
          const file = source.files[0];
          const sheets = file?.metadata?.sheets ?? [];
          const attachedLink = agentSources.find((link) => link.data_source_id === source.id);
          return (
            <article className="dataSourceCard" key={source.id}>
              <div className="dataSourceHeader">
                <div>
                  <span className={`departmentStatus ${source.status}`}>{source.status}</span>
                  <h2>{source.name}</h2>
                  <p>{file?.original_name ?? "No file"} · {file ? formatBytes(file.size_bytes) : "0 B"}</p>
                </div>
                {attachedLink ? (
                  <button className="secondaryButton" type="button" disabled={busy === `detach-${source.id}`} onClick={() => detachSource(attachedLink)}>
                    ถอดจาก Agent
                  </button>
                ) : (
                  <button className="primaryButton" type="button" disabled={!agentId || busy === `attach-${source.id}`} onClick={() => attachSource(source)}>
                    เชื่อมกับ Agent
                  </button>
                )}
              </div>
              <div className="sheetPreviewList">
                {sheets.length === 0 ? (
                  <p className="mutedText">ยังไม่มี preview หรืออ่านไฟล์ไม่สำเร็จ</p>
                ) : sheets.map((sheet) => (
                  <details key={sheet.name} open={sheets.length === 1}>
                    <summary>{sheet.name} · {sheet.row_count} rows · {sheet.column_count} columns</summary>
                    <p className="mutedText">{sheet.columns.join(", ")}</p>
                    {sheet.preview_rows.length > 0 && (
                      <div className="previewTableWrap">
                        <table className="departmentTable">
                          <thead>
                            <tr>{sheet.columns.slice(0, 6).map((column) => <th key={column}>{column}</th>)}</tr>
                          </thead>
                          <tbody>
                            {sheet.preview_rows.map((row, rowIndex) => (
                              <tr key={rowIndex}>
                                {sheet.columns.slice(0, 6).map((column) => (
                                  <td key={column}>{String(row[column] ?? "")}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </details>
                ))}
              </div>
            </article>
          );
        })}
      </section>
    </>
  );
}
