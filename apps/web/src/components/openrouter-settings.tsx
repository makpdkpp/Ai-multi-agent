"use client";

type OpenRouterStatus = {
  configured: boolean;
  base_url: string;
  app_title: string;
  secret_source: string;
};

export function OpenRouterSettings({ status }: { status: OpenRouterStatus }) {
  return (
    <>
      <div className="departmentToolbar">
        <div>
          <h1>ตั้งค่า OpenRouter</h1>
          <p>ตรวจสถานะการเชื่อมต่อ LLM provider หลักสำหรับ Agent gateway</p>
        </div>
        <span className={`providerBadge ${status.configured ? "active" : "missing"}`}>
          {status.configured ? "Configured" : "Missing API key"}
        </span>
      </div>

      <section className="settingsGrid">
        <article className="settingsPanel">
          <h2>Connection</h2>
          <dl>
            <div>
              <dt>Base URL</dt>
              <dd>{status.base_url}</dd>
            </div>
            <div>
              <dt>App title</dt>
              <dd>{status.app_title}</dd>
            </div>
            <div>
              <dt>API key</dt>
              <dd>{status.configured ? "ตั้งค่าแล้วใน server environment" : "ยังไม่ได้ตั้งค่า"}</dd>
            </div>
          </dl>
        </article>

        <article className="settingsPanel">
          <h2>Server environment</h2>
          <p className="settingsNote">
            เพื่อความปลอดภัย ระบบจะไม่แสดงหรือบันทึก API key ผ่านหน้าเว็บในช่วง local pilot
            ให้ตั้งค่าในไฟล์ `.env` ของ server แล้ว restart service
          </p>
          <pre className="commandBox">{`${status.secret_source}=sk-or-...
OPENROUTER_BASE_URL=${status.base_url}
OPENROUTER_APP_TITLE=${status.app_title}`}</pre>
          <pre className="commandBox">docker compose up -d --build api web</pre>
        </article>
      </section>
    </>
  );
}
