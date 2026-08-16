"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export type UsageSummary = {
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  requests: number;
  provider_cost_usd: string;
  infrastructure_cost_usd: string;
  display_cost_usd: string;
  display_cost_thb: string;
  exchange_rate: {
    rate: string;
    source: string;
    effective_at: string;
    status: string;
  };
  budget: DepartmentBudget | null;
};

export type DepartmentUsage = {
  id: string;
  name: string;
  code: string;
  summary: UsageSummary;
};

export type DepartmentBudget = {
  currency: "USD" | "THB";
  limit_amount: string;
  spent_amount: string;
  percent_used: string;
  period_type: "monthly";
  period_start_day: number;
  action_on_exceed: "notify_only" | "pause_public_widget" | "pause_all_llm";
  warning_thresholds: number[];
  enabled: boolean;
};

function csrfToken(): string {
  const cookie = document.cookie.split("; ").find((item) => item.startsWith("agentdesk_csrf="));
  return cookie ? decodeURIComponent(cookie.split("=").slice(1).join("=")) : "";
}

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

function money(value: string, currency: "USD" | "THB") {
  return new Intl.NumberFormat("th-TH", {
    style: "currency",
    currency,
    maximumFractionDigits: currency === "USD" ? 4 : 2,
  }).format(Number(value));
}

function number(value: number) {
  return new Intl.NumberFormat("th-TH").format(value);
}

function actionLabel(action: DepartmentBudget["action_on_exceed"]) {
  if (action === "pause_public_widget") return "หยุด public widget";
  if (action === "pause_all_llm") return "หยุด LLM ทั้งหมด";
  return "แจ้งเตือนอย่างเดียว";
}

export function UsageDashboard({
  systemSummary,
  departments,
}: {
  systemSummary: UsageSummary;
  departments: DepartmentUsage[];
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function syncRate() {
    setBusy("rate");
    setError("");
    const response = await fetch(`${apiUrl}/system/exchange-rates/sync`, {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": csrfToken() },
    });
    if (response.ok) {
      router.refresh();
    } else {
      setError("อัปเดตอัตราแลกเปลี่ยนไม่สำเร็จ ระบบจะใช้ค่า fallback ล่าสุดต่อไป");
    }
    setBusy(null);
  }

  async function saveBudget(event: FormEvent<HTMLFormElement>, departmentId: string) {
    event.preventDefault();
    setBusy(departmentId);
    setError("");
    const form = new FormData(event.currentTarget);
    const response = await fetch(`${apiUrl}/departments/${departmentId}/budget`, {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({
        currency: form.get("currency"),
        limit_amount: form.get("limit_amount"),
        period_type: "monthly",
        period_start_day: Number(form.get("period_start_day")),
        action_on_exceed: form.get("action_on_exceed"),
        warning_thresholds: String(form.get("warning_thresholds"))
          .split(",")
          .map((item) => Number(item.trim()))
          .filter(Boolean),
        enabled: form.get("enabled") === "on",
      }),
    });
    if (response.ok) {
      router.refresh();
    } else {
      setError("บันทึก budget ไม่สำเร็จ กรุณาตรวจตัวเลขและลองอีกครั้ง");
    }
    setBusy(null);
  }

  return (
    <>
      <div className="departmentToolbar">
        <div>
          <h1>Token และค่าใช้จ่าย</h1>
          <p>ติดตาม usage แยกแผนก พร้อมคำนวณ USD/THB จากอัตราแลกเปลี่ยนที่เก็บเป็น snapshot</p>
        </div>
        <button className="primaryButton" type="button" disabled={busy === "rate"} onClick={syncRate}>
          {busy === "rate" ? "กำลังอัปเดต..." : "อัปเดต USD/THB"}
        </button>
      </div>

      {error && <p className="formError" role="alert">{error}</p>}

      <section className="usageHero">
        <article>
          <span>ค่าใช้จ่ายรวม</span>
          <strong>{money(systemSummary.display_cost_thb, "THB")}</strong>
          <small>{money(systemSummary.display_cost_usd, "USD")}</small>
        </article>
        <article>
          <span>Token รวม</span>
          <strong>{number(systemSummary.input_tokens + systemSummary.output_tokens)}</strong>
          <small>{number(systemSummary.requests)} requests</small>
        </article>
        <article>
          <span>USD/THB</span>
          <strong>{Number(systemSummary.exchange_rate.rate).toFixed(4)}</strong>
          <small>{systemSummary.exchange_rate.source} · {systemSummary.exchange_rate.status}</small>
        </article>
      </section>

      <section className="usageTableWrap">
        <table className="departmentTable">
          <thead>
            <tr>
              <th>แผนก</th>
              <th>Token</th>
              <th>Cost</th>
              <th>Budget</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {departments.map((department) => (
              <tr key={department.id}>
                <td>
                  <strong>{department.name}</strong>
                  <small>{department.code}</small>
                </td>
                <td>
                  {number(department.summary.input_tokens + department.summary.output_tokens)}
                  <small>{number(department.summary.requests)} requests</small>
                </td>
                <td>
                  {money(department.summary.display_cost_thb, "THB")}
                  <small>{money(department.summary.display_cost_usd, "USD")}</small>
                </td>
                <td>
                  {department.summary.budget ? (
                    <>
                      <strong>{Number(department.summary.budget.percent_used).toFixed(2)}%</strong>
                      <small>
                        {money(department.summary.budget.spent_amount, department.summary.budget.currency)}
                        {" / "}
                        {money(department.summary.budget.limit_amount, department.summary.budget.currency)}
                      </small>
                    </>
                  ) : (
                    <span className="mutedText">ยังไม่ตั้ง budget</span>
                  )}
                </td>
                <td>
                  <form className="budgetForm" onSubmit={(event) => saveBudget(event, department.id)}>
                    <input
                      name="limit_amount"
                      type="number"
                      min="0"
                      step="0.01"
                      defaultValue={department.summary.budget?.limit_amount ?? "5000.00"}
                      aria-label="วงเงิน"
                    />
                    <select name="currency" defaultValue={department.summary.budget?.currency ?? "THB"} aria-label="สกุลเงิน">
                      <option value="THB">THB</option>
                      <option value="USD">USD</option>
                    </select>
                    <select
                      name="action_on_exceed"
                      defaultValue={department.summary.budget?.action_on_exceed ?? "notify_only"}
                      aria-label="การทำงานเมื่อเกินงบ"
                    >
                      <option value="notify_only">{actionLabel("notify_only")}</option>
                      <option value="pause_public_widget">{actionLabel("pause_public_widget")}</option>
                      <option value="pause_all_llm">{actionLabel("pause_all_llm")}</option>
                    </select>
                    <input
                      name="warning_thresholds"
                      defaultValue={department.summary.budget?.warning_thresholds.join(",") ?? "70,90,100"}
                      aria-label="จุดแจ้งเตือน"
                    />
                    <input
                      name="period_start_day"
                      type="number"
                      min="1"
                      max="28"
                      defaultValue={department.summary.budget?.period_start_day ?? 1}
                      aria-label="วันเริ่มรอบเดือน"
                    />
                    <label className="budgetToggle">
                      <input name="enabled" type="checkbox" defaultChecked={department.summary.budget?.enabled ?? true} />
                      เปิดใช้
                    </label>
                    <button className="secondaryButton" type="submit" disabled={busy === department.id}>
                      {busy === department.id ? "บันทึก..." : "บันทึก"}
                    </button>
                  </form>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
