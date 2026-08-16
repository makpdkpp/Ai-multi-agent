"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"}/auth/local/login`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
        },
      );
      if (!response.ok) {
        setError(response.status === 429 ? "ลองเข้าสู่ระบบมากเกินไป กรุณารอสักครู่" : "อีเมลหรือรหัสผ่านไม่ถูกต้อง");
        return;
      }
      router.push("/");
      router.refresh();
    } catch {
      setError("ไม่สามารถเชื่อมต่อระบบได้ กรุณาลองอีกครั้ง");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="loginPage">
      <section className="loginPanel">
        <div className="loginBrand"><span className="brandMark">AI</span><strong>AgentDesk</strong></div>
        <p className="eyebrow">LOCAL PILOT</p>
        <h1>เข้าสู่ระบบ</h1>
        <p className="loginHint">ใช้บัญชีภายในที่ผู้ดูแลระบบสร้างให้</p>
        <form onSubmit={submit}>
          <label>อีเมล<input name="email" type="email" autoComplete="username" required /></label>
          <label>รหัสผ่าน<input name="password" type="password" autoComplete="current-password" required /></label>
          {error && <p className="formError" role="alert">{error}</p>}
          <button type="submit" disabled={loading}>{loading ? "กำลังเข้าสู่ระบบ..." : "เข้าสู่ระบบ"}</button>
        </form>
      </section>
      <aside className="loginAside">
        <p>Multi-Agent AI Q&A Platform</p>
        <h2>ข้อมูลของแต่ละแผนก<br />แยกจากกันอย่างชัดเจน</h2>
        <span>MySQL · Excel · PDF · Human Handoff</span>
      </aside>
    </main>
  );
}
