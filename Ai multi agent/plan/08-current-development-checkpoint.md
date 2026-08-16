# 08 - Current Development Checkpoint

วันที่บันทึก: 2026-08-16  
Branch: `main`  
Latest pushed commit: `5670bea feat: add excel data sources`  
Remote: `origin/main` (`https://github.com/makpdkpp/Ai-multi-agent.git`)

เอกสารนี้ใช้เป็นจุดเริ่มต้นสำหรับกลับมาพัฒนาต่อครั้งหน้า โดยไม่ต้องย้อนอ่านข้อความในแชททั้งหมด

---

## 1. สถานะระบบล่าสุด

ระบบ dev ทำงานผ่าน Docker Compose แล้ว

Services ที่ตรวจล่าสุด:

- `api` healthy ที่ `http://localhost:8000`
- `web` healthy ที่ `http://localhost:3000`
- `postgres` healthy
- `redis` healthy
- `minio` healthy

Migration ล่าสุด:

- `20260816_0010`

หน้าที่ใช้งานแล้ว:

- Login: `http://localhost:3000/login`
- Dashboard: `http://localhost:3000`
- Departments: `http://localhost:3000/departments`
- Agents: `http://localhost:3000/agents`
- Internal Chat: `http://localhost:3000/chat`
- Data Sources: `http://localhost:3000/data-sources`
- Usage / Token / Cost: `http://localhost:3000/usage`
- OpenRouter Settings: `http://localhost:3000/settings/openrouter`

---

## 2. สิ่งที่พัฒนาเสร็จแล้ว

### 2.1 Foundation / Infrastructure

- วางโครงสร้าง monorepo แยก `apps/api` และ `apps/web`
- ใช้ Docker Compose สำหรับ dev environment
- Services หลัก:
  - FastAPI API
  - Next.js Web
  - PostgreSQL + pgvector
  - Redis
  - MinIO สำหรับ object storage
- มี migration ด้วย Alembic
- มี health check ของ API/Web
- Push checkpoint ขึ้น GitHub แล้ว

### 2.2 Authentication

- รองรับ local/internal account สำหรับช่วงทดลองใช้งาน
- มี Super Admin bootstrap ผ่าน CLI
- Login ด้วย session cookie + CSRF cookie
- ใช้ role หลัก:
  - `super_admin`
  - standard internal user
- Microsoft Entra ID / Microsoft 365 ยังไม่ทำใน phase นี้ ตามการตัดสินใจให้ทำภายหลัง

### 2.3 Departments

- Super Admin จัดการหลายแผนกได้
- มี department membership
- แยกสิทธิ์ตามแผนก
- ใช้ Row Level Security แนวคิด tenant boundary ตาม `department_id`
- Department Admin / Agent Manager สามารถจัดการงานภายในแผนกได้บางส่วน

### 2.4 Agents

- สร้าง Agent ต่อแผนกได้
- Agent มี:
  - slug
  - name
  - description
  - status
  - default language
  - system prompt
  - response style
  - LLM config
  - channel permissions
- MVP บังคับให้เปิด `internal_chat`
- มี endpoint ทดสอบ Agent invoke
- แก้ปัญหา `agent not found` จาก context/RLS และ relation loading แล้ว

### 2.5 OpenRouter

- มีเมนูตั้งค่า OpenRouter
- รองรับการกำหนด API key ผ่านระบบ
- แก้ความเข้าใจเรื่อง `@preset/chat`: ในระบบนี้ควรใช้ model key จริงหรือ model/preset ที่ตั้งค่าใน OpenRouter ให้ถูกต้อง
- Chat ใช้ OpenRouter `/chat/completions`
- ส่ง headers:
  - `Authorization`
  - `HTTP-Referer`
  - `X-Title`
- มี budget guard ก่อนเรียก LLM

### 2.6 Token / Cost / Exchange Rate

- ระบบคำนวณ token และ cost ทำงานแล้ว
- รองรับ USD และ THB
- รองรับ exchange rate จาก ExchangeRate-API แผนฟรี:
  - `https://open.er-api.com/v6/latest/USD`
- มีหน้า Usage dashboard
- แสดง:
  - จำนวน request
  - input tokens
  - output tokens
  - cost USD
  - cost THB
  - exchange rate ล่าสุด
- Chat message แสดง cost ต่อคำตอบแล้ว
- แก้ bug cost หายหลัง refresh แล้ว
- แยก usage ตาม department / agent / conversation ได้ใน data model

### 2.7 Internal Chat

- มีหน้า Internal Chat
- เลือก/สร้าง conversation ได้
- ส่งข้อความไปยัง Agent ผ่าน OpenRouter ได้
- บันทึก user/assistant messages ลง DB
- บันทึก usage event ต่อ assistant message
- แสดง cost และ tokens ใต้ข้อความ AI
- แสดง usage รวมของ conversation
- แก้ปัญหา:
  - หน้า `/chat` 500
  - CORS misleading error ที่จริงเกิดจาก API 500
  - cost ไม่แสดงหลัง refresh
- เพิ่ม behavior:
  - กด `Enter` เพื่อส่งข้อความ
  - กด `Shift + Enter` เพื่อขึ้นบรรทัดใหม่

### 2.8 Excel Data Sources

เพิ่ม foundation สำหรับเชื่อม Excel เข้ากับ Agent แล้ว

Backend:

- เพิ่ม dependency:
  - `openpyxl`
  - `python-multipart`
- เพิ่ม migration `20260816_0010_data_sources.py`
- เพิ่มตาราง:
  - `data_sources`
  - `source_files`
  - `agent_data_sources`
- เพิ่ม RLS สำหรับ data source tables
- เพิ่ม API router `agentdesk_api.api.data_sources`
- รองรับ upload:
  - `.xlsx`
  - `.xlsm`
  - `.csv`
- จำกัดไฟล์ Excel upload MVP ที่ 20 MB
- Upload file เข้า MinIO
- Parse sheet/columns/preview rows
- เก็บ metadata ใน `source_files.metadata`
- Attach / detach Data Source กับ Agent ได้
- แก้ auth context สำหรับ route ที่เกี่ยวกับ Agent/Data Source เพื่อให้ไม่ชน RLS

Frontend:

- เพิ่มหน้า `/data-sources`
- เพิ่ม sidebar menu `Data Sources`
- ในหน้า Data Sources ทำได้:
  - เลือก department
  - upload Excel/CSV
  - เห็น source card
  - เห็น sheet preview
  - เลือก Agent
  - attach/detach source กับ Agent

Excel in Chat:

- เพิ่มไฟล์ `agentdesk_api/source_context.py`
- Internal Chat และ Agent invoke จะโหลด Excel Data Source ที่ attach กับ Agent แล้วใส่เป็น context ให้ LLM
- โหลดไฟล์จริงจาก MinIO ตอนตอบคำถาม
- อ่านข้อมูลได้จาก `.xlsx`, `.xlsm`, `.csv`
- จำกัด MVP:
  - สูงสุด 5 attached sources ต่อ request
  - สูงสุด 80 rows ต่อ sheet
  - สูงสุด 30 columns ต่อ sheet
  - สูงสุด 18,000 characters ของ source context
- ถ้าโหลดไฟล์เต็มไม่ได้ จะ fallback ไปใช้ preview metadata
- User ทดสอบแล้วว่า Agent ตอบคำถามจาก Excel ได้

---

## 3. Bug / Issue ที่เคยเจอและแก้แล้ว

- รัน `docker compose exec` ผิด directory แล้วขึ้น `no configuration file provided`
  - วิธีที่ถูก: ต้องรันใน `C:\laragon\www\Ai-multi-agent`
- Bootstrap admin สร้าง user ได้ แต่มี warning เรื่อง asyncpg event loop ตอนปิด connection
  - ไม่กระทบการสร้าง user ในตอนนั้น
- Super Admin สร้าง Department Admin แล้วแจ้ง user อยู่ในแผนกแล้วทั้งที่เปลี่ยนชื่อ
  - แก้ flow/logic membership แล้วในรอบก่อนหน้า
- Login บาง user แล้วเกิด Minified React error #441
  - แก้ relation/context และ refresh behavior แล้ว
- Service user มองไม่เห็น Agent
  - แก้ RLS/auth context แล้ว
- Internal Chat `/chat` 500
  - แก้ server render/data loading แล้ว
- ส่ง chat แล้ว browser แจ้ง CORS
  - root cause คือ API 500 ไม่ใช่ CORS จริง
- Cost แสดงตอนตอบ แต่หายหลัง F5
  - แก้ให้ reload usage per message แล้ว
- Agent ไม่เห็น Excel ที่ upload
  - แก้ให้ chat/invoke โหลด attached Excel source เข้า context แล้ว

---

## 4. Commit สำคัญล่าสุด

```text
5670bea feat: add excel data sources
25eaf8c feat: send chat on enter
f3e6f49 fix: set chat usage department context
9775a56 fix: load chat details for message costs
0286ecd feat: show chat message usage costs
2ffa31e fix: preload agent relations for chat messages
48cef91 fix: grant chat tables to app role
ad04a15 feat: add internal chat conversations
```

---

## 5. คำสั่งที่ใช้ตรวจล่าสุด

Backend test image:

```powershell
docker build --target test -t agentdesk-api-test ./apps/api
```

Backend lint:

```powershell
docker run --rm agentdesk-api-test ruff check .
```

Backend tests:

```powershell
docker run --rm agentdesk-api-test pytest -q
```

Frontend lint:

```powershell
cd apps/web
npm run lint
```

Deploy dev:

```powershell
docker compose up -d --build api web
```

หรือถ้าแก้เฉพาะ API:

```powershell
docker compose up -d --build api
```

เช็คสถานะ:

```powershell
docker compose ps
docker compose logs api web --no-color --tail=80
```

เช็ค migration:

```powershell
docker compose exec -T postgres psql -U agentdesk_admin -d agentdesk -c "SELECT version_num FROM alembic_version;"
```

---

## 6. สิ่งที่ควรทดสอบซ้ำหลังกลับมาทำต่อ

### Excel Data Source

1. Login เป็น Super Admin หรือ Department Admin
2. ไปที่ `/data-sources`
3. เลือก department
4. Upload `.xlsx` หรือ `.csv`
5. ตรวจว่าเห็น:
   - source name
   - file name
   - file size
   - sheet name
   - columns
   - preview rows
6. เลือก Agent ในแผนกเดียวกัน
7. Attach Data Source กับ Agent
8. Refresh หน้า แล้วตรวจว่า source ยังอยู่
9. Detach แล้วตรวจว่าถอดได้

### Internal Chat + Excel

1. ไปที่ `/chat`
2. เลือก Agent ที่ attach Excel แล้ว
3. สร้าง chat ใหม่เพื่อกัน history เก่า
4. ถาม:

```text
จากไฟล์ projecttest มีข้อมูลอะไรบ้าง
```

5. ถามต่อ:

```text
โครงการไหนใกล้หมดประกันที่สุด
```

6. ตรวจว่า:
   - AI อ้างอิงข้อมูลจาก Excel ได้
   - cost แสดงใต้ข้อความ
   - กด F5 แล้ว cost ยังอยู่

### Permission / Department Isolation

1. Login user แผนก A
2. ตรวจว่าเห็นเฉพาะ Agent/Data Source ของแผนก A
3. Login user แผนก B
4. ตรวจว่าไม่เห็น Data Source ของแผนก A

---

## 7. ข้อจำกัดปัจจุบัน

- Excel context ตอนนี้เป็นแบบ simple context injection ยังไม่ใช่ RAG/vector index เต็มรูปแบบ
- จำกัดการอ่าน 80 rows ต่อ sheet เพื่อกัน prompt ใหญ่เกิน
- ถ้า Excel ใหญ่มาก หรือมีหลาย sheet มาก อาจตอบจากข้อมูลไม่ครบ
- ยังไม่ได้ทำ semantic search / indexing / chunking สำหรับ Excel
- ยังไม่ได้ทำ PDF ingestion
- ยังไม่ได้ทำ MySQL connector
- ยังไม่ได้ทำ Human Handoff UI/API จริง
- ยังไม่ได้ทำ Microsoft Entra ID / Microsoft 365 login
- ยังไม่ได้ทำ public embed widget
- ยังไม่ได้ทำ Teams/LINE
- ยังไม่ได้ทำหน้า config ลึก ๆ สำหรับ Data Source เช่น mapping column, refresh schedule, access policy

---

## 8. งานถัดไปที่แนะนำ

ลำดับที่แนะนำหลัง checkpoint นี้:

1. ทำ Excel indexing รุ่นแรก
   - สร้างตาราง `source_chunks` หรือ `source_rows`
   - แตก Excel เป็น row/chunk
   - ทำ keyword search หรือ vector search ด้วย pgvector
   - ให้ Agent ดึงเฉพาะ rows ที่เกี่ยวข้องแทนการส่ง 80 rows ทุกครั้ง

2. เพิ่ม UI แสดงสถานะการ index
   - uploaded
   - processing
   - ready
   - failed
   - จำนวน rows/chunks

3. เพิ่ม source citation ในคำตอบ
   - ระบุ source name
   - sheet
   - row number

4. เพิ่ม Data Source test panel
   - ให้ admin ทดสอบ query กับ source โดยไม่ต้องเข้า chat

5. เริ่ม PDF connector
   - upload PDF
   - extract text
   - chunk/index
   - attach กับ Agent

6. เริ่ม MySQL connector
   - config connection
   - allow schema/table/column
   - test connection
   - query policy

7. เริ่ม Human Handoff
   - department inbox
   - case lifecycle
   - live/offline mode
   - SLA
   - AI draft reply

---

## 9. ไฟล์สำคัญที่เพิ่ม/แก้ล่าสุด

Backend:

- `apps/api/pyproject.toml`
- `apps/api/src/agentdesk_api/main.py`
- `apps/api/src/agentdesk_api/db/models.py`
- `apps/api/src/agentdesk_api/api/data_sources.py`
- `apps/api/src/agentdesk_api/source_context.py`
- `apps/api/src/agentdesk_api/api/chat.py`
- `apps/api/src/agentdesk_api/api/agents.py`
- `apps/api/migrations/versions/20260816_0010_data_sources.py`

Frontend:

- `apps/web/src/app/data-sources/page.tsx`
- `apps/web/src/components/data-source-manager.tsx`
- `apps/web/src/app/globals.css`
- Sidebar/nav links in:
  - `apps/web/src/app/page.tsx`
  - `apps/web/src/app/agents/page.tsx`
  - `apps/web/src/app/chat/page.tsx`
  - `apps/web/src/app/departments/page.tsx`
  - `apps/web/src/app/usage/page.tsx`
  - `apps/web/src/app/settings/openrouter/page.tsx`

---

## 10. หมายเหตุสำหรับรอบถัดไป

ก่อนเริ่มทำต่อ ให้ทำตามนี้:

```powershell
cd C:\laragon\www\Ai-multi-agent
git status
git pull
docker compose ps
```

ถ้า services ไม่ขึ้น:

```powershell
docker compose up -d
```

ถ้าเพิ่ง pull migration ใหม่:

```powershell
docker compose up -d --build api web
```

จากนั้นเริ่มงานถัดไปจากหัวข้อ `8. งานถัดไปที่แนะนำ`

