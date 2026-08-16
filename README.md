# AgentDesk — Multi-Agent AI Q&A Platform

ระบบ AI แบบหลาย Agent สำหรับบริษัทเดียวที่มีหลายแผนก รองรับ MySQL, Excel, PDF, internal chat, public widget, Human Handoff และการติดตาม Token/ค่าใช้จ่าย

## Quick start

1. คัดลอก `.env.example` เป็น `.env` และเปลี่ยนรหัสผ่าน/secret ทุกค่า
2. รัน `docker compose up --build`
3. เปิด Web ที่ `http://localhost:3000`
4. ตรวจ API ที่ `http://localhost:8000/docs`
5. MinIO console อยู่ที่ `http://localhost:9001`

## สร้าง Super Admin คนแรก

หลังจาก services healthy ให้รันคำสั่งแบบ interactive:

```powershell
docker compose exec api python -m agentdesk_api.cli bootstrap-admin --email admin@example.com --name "System Admin"
```

ระบบจะถามรหัสผ่านสองครั้งโดยไม่แสดงค่าบนหน้าจอ จากนั้นเข้าสู่ระบบที่ `http://localhost:3000/login`

Pilot ใช้บัญชีภายในก่อน Microsoft Entra ID/Microsoft 365 จะเพิ่มใน phase ถัดไป

## Services

- `web`: Next.js admin/internal UI
- `api`: FastAPI REST API
- `postgres`: PostgreSQL 16 + pgvector
- `redis`: cache, rate limit และ job queue
- `minio`: object storage สำหรับ PDF/Excel
- `migrate`: Alembic one-shot migration

## Development status

กำลังพัฒนา Phase 0 foundation ดูแผนทั้งหมดใน `Ai multi agent/plan` และ `Ai multi agent/Prepare`
