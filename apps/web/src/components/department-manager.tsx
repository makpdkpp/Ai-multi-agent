"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export type Department = {
  id: string;
  code: string;
  name: string;
  timezone: string;
  status: "active" | "suspended" | "disabled";
  retention_days: number;
  member_count: number;
};

type DepartmentMember = {
  id: string;
  user_id: string;
  email: string;
  display_name: string;
  role: "department_admin" | "agent_manager" | "staff" | "viewer";
  status: "active" | "suspended";
  user_status: "active" | "invited";
};

function csrfToken(): string {
  const cookie = document.cookie.split("; ").find((item) => item.startsWith("agentdesk_csrf="));
  return cookie ? decodeURIComponent(cookie.split("=").slice(1).join("=")) : "";
}

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export function DepartmentManager({ initialDepartments }: { initialDepartments: Department[] }) {
  const router = useRouter();
  const [departments, setDepartments] = useState(initialDepartments);
  const [formMode, setFormMode] = useState<"create" | "edit" | null>(null);
  const [editingDepartment, setEditingDepartment] = useState<Department | null>(null);
  const [selectedDepartment, setSelectedDepartment] = useState<Department | null>(null);
  const [members, setMembers] = useState<DepartmentMember[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  function openCreateForm() {
    setError("");
    setEditingDepartment(null);
    setFormMode("create");
  }

  function openEditForm(department: Department) {
    setError("");
    setEditingDepartment(department);
    setFormMode("edit");
  }

  function closeForm() {
    setError("");
    setEditingDepartment(null);
    setFormMode(null);
  }

  async function submitDepartment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const mode = formMode;
    if (mode == null) return;
    setBusy(mode);
    setError("");
    const form = new FormData(event.currentTarget);
    const payload = {
      code: form.get("code"),
      name: form.get("name"),
      timezone: form.get("timezone"),
      retention_days: Number(form.get("retention_days")),
    };
    const endpoint =
      mode === "create"
        ? `${apiUrl}/departments`
        : `${apiUrl}/departments/${editingDepartment?.id}`;
    const response = await fetch(endpoint, {
      method: mode === "create" ? "POST" : "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify(
        mode === "create"
          ? payload
          : {
              name: payload.name,
              timezone: payload.timezone,
              retention_days: payload.retention_days,
            },
      ),
    });
    if (response.ok) {
      const body = await response.json();
      setDepartments((current) => {
        const next =
          mode === "create"
            ? [...current, body.data]
            : current.map((item) => (item.id === body.data.id ? body.data : item));
        return next.sort((a, b) => a.name.localeCompare(b.name, "th"));
      });
      closeForm();
      event.currentTarget.reset();
      router.refresh();
    } else {
      const body = await response.json().catch(() => null);
      setError(
        response.status === 409
          ? "รหัสแผนกนี้ถูกใช้งานแล้ว"
          : body?.detail ?? (mode === "create" ? "ไม่สามารถสร้างแผนกได้" : "ไม่สามารถบันทึกการแก้ไขได้"),
      );
    }
    setBusy(null);
  }

  async function toggleStatus(department: Department) {
    const action = department.status === "active" ? "suspend" : "resume";
    setBusy(department.id);
    setError("");
    const response = await fetch(`${apiUrl}/departments/${department.id}/${action}`, {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": csrfToken() },
    });
    if (response.ok) {
      const body = await response.json();
      setDepartments((current) => current.map((item) => item.id === department.id ? body.data : item));
      router.refresh();
    } else {
      setError("ไม่สามารถเปลี่ยนสถานะแผนกได้");
    }
    setBusy(null);
  }

  async function openMembers(department: Department) {
    setSelectedDepartment(department);
    setBusy(`members-${department.id}`);
    setError("");
    const response = await fetch(`${apiUrl}/departments/${department.id}/members`, {
      credentials: "include",
    });
    if (response.ok) {
      const body = await response.json();
      setMembers(body.data);
    } else {
      setError("ไม่สามารถโหลดสมาชิกแผนกได้");
    }
    setBusy(null);
  }

  async function addMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedDepartment) return;
    setBusy("add-member");
    setError("");
    const form = new FormData(event.currentTarget);
    const response = await fetch(`${apiUrl}/departments/${selectedDepartment.id}/members`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({
        email: form.get("email"),
        display_name: form.get("display_name"),
        role: form.get("role"),
        password: form.get("password") || null,
      }),
    });
    if (response.ok) {
      const body = await response.json();
      setMembers((current) => [...current, body.data].sort((a, b) => a.display_name.localeCompare(b.display_name, "th")));
      setDepartments((current) =>
        current.map((department) =>
          department.id === selectedDepartment.id
            ? { ...department, member_count: department.member_count + 1 }
            : department,
        ),
      );
      event.currentTarget.reset();
      router.refresh();
    } else {
      const body = await response.json().catch(() => null);
      setError(response.status === 409 ? "ผู้ใช้นี้อยู่ในแผนกแล้ว" : body?.detail ?? "เพิ่มสมาชิกไม่สำเร็จ");
    }
    setBusy(null);
  }

  async function updateMember(member: DepartmentMember, status: DepartmentMember["status"]) {
    if (!selectedDepartment) return;
    setBusy(member.id);
    setError("");
    const response = await fetch(`${apiUrl}/departments/${selectedDepartment.id}/members/${member.id}`, {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({ status }),
    });
    if (response.ok) {
      const body = await response.json();
      setMembers((current) => current.map((item) => item.id === member.id ? body.data : item));
    } else {
      setError("เปลี่ยนสถานะสมาชิกไม่สำเร็จ");
    }
    setBusy(null);
  }

  return (
    <>
      <div className="departmentToolbar">
        <div>
          <h1>แผนกทั้งหมด</h1>
          <p>จัดการขอบเขตข้อมูลและสถานะการใช้งานของแต่ละแผนก</p>
        </div>
        <button className="primaryButton" type="button" onClick={() => (formMode ? closeForm() : openCreateForm())}>
          {formMode ? "ยกเลิก" : "+ เพิ่มแผนก"}
        </button>
      </div>

      {formMode && (
        <form className="departmentForm" onSubmit={submitDepartment}>
          <label>
            รหัสแผนก
            <input
              name="code"
              placeholder="เช่น sales"
              pattern="[a-z][a-z0-9-]{1,49}"
              defaultValue={editingDepartment?.code ?? ""}
              disabled={formMode === "edit"}
              required
            />
          </label>
          <label>
            ชื่อแผนก
            <input name="name" placeholder="เช่น ฝ่ายขาย" maxLength={200} defaultValue={editingDepartment?.name ?? ""} required />
          </label>
          <label>
            เขตเวลา
            <select name="timezone" defaultValue={editingDepartment?.timezone ?? "Asia/Bangkok"}>
              <option value="Asia/Bangkok">Asia/Bangkok</option>
              <option value="UTC">UTC</option>
            </select>
          </label>
          <label>
            เก็บข้อมูล (วัน)
            <input
              name="retention_days"
              type="number"
              min="1"
              max="3650"
              defaultValue={editingDepartment?.retention_days ?? 90}
              required
            />
          </label>
          <button className="primaryButton" type="submit" disabled={busy === formMode}>
            {busy === formMode ? "กำลังบันทึก..." : formMode === "create" ? "สร้างแผนก" : "บันทึกการแก้ไข"}
          </button>
        </form>
      )}

      {error && <p className="formError" role="alert">{error}</p>}

      <section className="departmentSummary" aria-label="สรุปแผนก">
        <article><span>แผนกทั้งหมด</span><strong>{departments.length}</strong></article>
        <article><span>เปิดใช้งาน</span><strong>{departments.filter((item) => item.status === "active").length}</strong></article>
        <article><span>ระงับชั่วคราว</span><strong>{departments.filter((item) => item.status === "suspended").length}</strong></article>
      </section>

      <section className="departmentTableWrap">
        {departments.length === 0 ? (
          <div className="emptyState"><strong>ยังไม่มีแผนก</strong><p>สร้างแผนกแรกเพื่อเริ่มกำหนดสมาชิกและแหล่งข้อมูล</p></div>
        ) : (
          <table className="departmentTable">
            <thead><tr><th>แผนก</th><th>รหัส</th><th>สมาชิก</th><th>เก็บข้อมูล</th><th>สถานะ</th><th /></tr></thead>
            <tbody>{departments.map((department) => (
              <tr key={department.id}>
                <td><strong>{department.name}</strong><small>{department.timezone}</small></td>
                <td><code>{department.code}</code></td>
                <td>{department.member_count} คน</td>
                <td>{department.retention_days} วัน</td>
                <td><span className={`departmentStatus ${department.status}`}>{department.status === "active" ? "เปิดใช้งาน" : "ระงับ"}</span></td>
                <td className="departmentActions">
                  <button className="secondaryButton" type="button" disabled={busy === department.id} onClick={() => openEditForm(department)}>
                    แก้ไข
                  </button>
                  <button className="secondaryButton" type="button" disabled={busy === `members-${department.id}`} onClick={() => openMembers(department)}>
                    สมาชิก
                  </button>
                  <button className="secondaryButton" type="button" disabled={busy === department.id} onClick={() => toggleStatus(department)}>
                    {department.status === "active" ? "ระงับ" : "เปิดใช้งาน"}
                  </button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </section>

      {selectedDepartment && (
        <section className="memberPanel">
          <div className="sectionTitle">
            <div>
              <h2>สมาชิกแผนก {selectedDepartment.name}</h2>
              <p>เพิ่มบัญชีภายในสำหรับทดลองใช้งาน และกำหนด role ในแผนก</p>
            </div>
            <button className="secondaryButton" type="button" onClick={() => setSelectedDepartment(null)}>
              ปิด
            </button>
          </div>
          <form className="memberForm" onSubmit={addMember}>
            <input name="email" type="email" placeholder="user@company.local" required />
            <input name="display_name" placeholder="ชื่อผู้ใช้" required />
            <select name="role" defaultValue="staff">
              <option value="department_admin">Department Admin</option>
              <option value="agent_manager">Agent Manager</option>
              <option value="staff">Staff</option>
              <option value="viewer">Viewer</option>
            </select>
            <input name="password" type="password" minLength={8} placeholder="password ชั่วคราว (ถ้ามี)" />
            <button className="primaryButton" type="submit" disabled={busy === "add-member"}>
              {busy === "add-member" ? "กำลังเพิ่ม..." : "เพิ่มสมาชิก"}
            </button>
          </form>
          <div className="departmentTableWrap">
            <table className="departmentTable">
              <thead><tr><th>ผู้ใช้</th><th>Role</th><th>บัญชี</th><th>สถานะในแผนก</th><th /></tr></thead>
              <tbody>{members.map((member) => (
                <tr key={member.id}>
                  <td><strong>{member.display_name}</strong><small>{member.email}</small></td>
                  <td>{member.role}</td>
                  <td>{member.user_status === "active" ? "เปิดใช้งาน" : "รอ activation"}</td>
                  <td><span className={`departmentStatus ${member.status}`}>{member.status === "active" ? "เปิดใช้งาน" : "ระงับ"}</span></td>
                  <td className="departmentActions">
                    <button
                      className="secondaryButton"
                      type="button"
                      disabled={busy === member.id}
                      onClick={() => updateMember(member, member.status === "active" ? "suspended" : "active")}
                    >
                      {member.status === "active" ? "ระงับ" : "เปิดใช้งาน"}
                    </button>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
