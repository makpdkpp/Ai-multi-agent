"use client";

import { useRouter } from "next/navigation";

function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  const value = document.cookie.split("; ").find((item) => item.startsWith(prefix));
  return value ? decodeURIComponent(value.slice(prefix.length)) : null;
}

export function LogoutButton() {
  const router = useRouter();
  async function logout() {
    const csrfToken = readCookie("agentdesk_csrf");
    if (!csrfToken) return;
    const response = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"}/auth/local/logout`,
      {
        method: "POST",
        credentials: "include",
        headers: { "X-CSRF-Token": csrfToken },
      },
    );
    if (response.ok) {
      router.push("/login");
      router.refresh();
    }
  }

  return <button className="logoutButton" onClick={logout}>ออกจากระบบ</button>;
}
