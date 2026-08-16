# Capacity Sizing และ Traffic Baseline — MVP 40 Users

## 1. ข้อสรุป

สำหรับผู้ใช้ภายใน 40 คนใน 8 แผนก และใช้ OpenRouter เป็น LLM หลัก ระบบยังไม่ต้องใช้ GPU และยังไม่จำเป็นต้องใช้ Kubernetes จุดเริ่มต้นที่เหมาะสมคือ Docker Compose บน production server ภายในองค์กรที่มี CPU 16 physical/logical cores ระดับ server, RAM 64 GB และ NVMe แบบ mirror พร้อม backup แยกเครื่อง

ข้อจำกัดสำคัญ: server เดียวไม่ใช่ high availability หากเครื่องหรือ storage เสีย ระบบจะหยุดทั้งระบบ จึงเหมาะกับ Pilot/MVP production ที่ยอมรับ downtime ได้ เมื่อระบบกลายเป็นงานสำคัญควรแยกอย่างน้อย 2 application nodes และ 1 database/storage node

## 2. สมมติฐานในการคำนวณ

| ตัวแปร | Baseline | Design target |
|---|---:|---:|
| ผู้ใช้ภายในทั้งหมด | 40 | 100 โดยไม่เปลี่ยนสถาปัตยกรรม |
| ผู้ใช้ภายในพร้อมกัน | 10 (25%) | 25 |
| Public widget sessions พร้อมกัน | 20 | 75 |
| SSE connections พร้อมกัน | 30 | 100 |
| ข้อความขาเข้าสูงสุด | 30 ข้อความ/นาที | 60 ข้อความ/นาที |
| LLM calls เฉลี่ยต่อข้อความ | 2.5 | สูงสุดควบคุมที่ 5 |
| Outbound LLM calls | 75 ครั้ง/นาที | 150 ครั้ง/นาที sustained, burst 300 |
| งาน index พร้อมกัน | 2 | 4 worker slots |
| Conversation retention | 90 วัน | configurable |

ค่าดังกล่าวเป็น capacity envelope สำหรับเริ่มทดสอบ ไม่ใช่การคาดการณ์ว่าผู้ใช้จะใช้งานสูงเท่านี้จริง ต้องปรับจาก metric หลัง Pilot 2-4 สัปดาห์

## 3. Production Server เริ่มต้น

### แบบแนะนำสำหรับ MVP/Pilot

| Resource | ขนาดแนะนำ | เหตุผล |
|---|---:|---|
| CPU | 16 cores | API, PostgreSQL, parsing และ worker indexing ใช้ร่วมกัน |
| RAM | 64 GB ECC ถ้าเป็นไปได้ | Postgres 16 GB, workers 16 GB, services/cache และ OS headroom |
| Storage | 2 × 2 TB enterprise NVMe, RAID1 | DB, pgvector และไฟล์ทำงาน; usable ประมาณ 2 TB |
| Backup | NAS/object storage อีกเครื่องอย่างน้อย 4 TB | ห้ามนับ RAID เป็น backup |
| Network | 1 Gbps LAN, outbound HTTPS เสถียร | เชื่อม MySQL แต่ละแผนกและ OpenRouter |
| Power | UPS + graceful shutdown | ป้องกัน DB/storage corruption |
| GPU | ไม่ต้องมีในระยะแรก | OpenRouter ทำ inference ภายนอก |
| OS | Ubuntu Server 24.04 LTS | ตรงกับแผน infrastructure |

หาก server ที่มีอยู่มีเพียง 12 cores/48 GB RAM ยังใช้ Pilot ได้ แต่ต้องจำกัดงาน index พร้อมกันไม่เกิน 2 และติดตาม memory pressure อย่างใกล้ชิด

### Resource allocation เริ่มต้น

| Service | Replica | CPU limit รวม | RAM limit รวม |
|---|---:|---:|---:|
| Reverse proxy | 1 | 1 core | 1 GB |
| Next.js web | 2 | 2 cores | 4 GB |
| FastAPI | 2 | 4 cores | 8 GB |
| Background workers | 2-4 processes | 6 cores | 16 GB |
| PostgreSQL + pgvector | 1 | 6 cores | 16 GB |
| Redis | 1 | 1 core | 2 GB |
| MinIO | 1 | 2 cores | 4 GB |
| Monitoring/logging | 1 set | 2 cores | 6 GB |

CPU limits สามารถ overcommit ได้เพราะไม่ได้ใช้สูงสุดพร้อมกัน แต่ RAM limits รวมกับ OS/page cache ต้องไม่เกินประมาณ 80-85% ของเครื่อง

## 4. Storage Model

เนื่องจากยังไม่ทราบจำนวนและขนาดไฟล์ ให้เริ่มด้วย quota แบบปรับได้:

- 20 GB ต่อแผนก รวม 160 GB สำหรับไฟล์ต้นฉบับ
- 10 GB ต่อแผนกสำหรับ index/chunks/temporary artifacts
- 200 GB สำหรับ PostgreSQL, audit, messages และ usage ในปีแรก
- 300 GB สำหรับ logs, staging uploads และ processing headroom
- รักษาพื้นที่ว่างอย่างน้อย 25%

จุดเริ่มต้น upload policy สำหรับ Pilot:

| ชนิด | จำกัดต่อไฟล์ | หมายเหตุ |
|---|---:|---|
| PDF | 50 MB หรือ 500 หน้า | ตรวจ MIME/hash/malware; ยังไม่รับประกัน OCR |
| Excel | 25 MB | จำกัด 100,000 แถวต่อ sheet ในรอบแรก |
| จำนวนไฟล์ต่อ batch | 20 | enqueue และแสดง progress |

หากพบ PDF ที่ไม่มี text layer ให้ mark `ocr_required` ไม่ควรทำ OCR แบบเงียบ ๆ จนกว่าจะ benchmark ตัวอย่างจริง เพราะ OCR เปลี่ยน CPU/RAM/storage sizing อย่างมาก

## 5. Database และ Connection Pools

- FastAPI แต่ละ replica: pool 10 connections + overflow 5
- Worker: pool 5 connections ต่อ worker group ไม่ใช่ต่อ process
- PostgreSQL `max_connections` เริ่ม 100 และพิจารณา PgBouncer เมื่อ app replicas เพิ่ม
- MySQL แยก connection ต่อแผนก ใช้ pool เล็ก 2-5 connections ต่อ active source
- MySQL query timeout เริ่ม 15 วินาที, row limit 1,000 และ result payload cap 5 MB
- ห้ามเปิด pool ค้างให้ data source ที่ไม่มี traffic ทุกตัว; ใช้ lazy connection + idle eviction

## 6. Rate Limit เริ่มต้น

ค่าทั้งหมดต้อง configurable และ monitor rejection rate:

### Internal chat

- 6 messages/minute/user, burst 10
- 120 messages/hour/user
- 10 concurrent runs ต่อแผนก
- 2 concurrent runs ต่อ user

### Public widget

- 5 messages/minute/IP hash, burst 8
- 10 messages/10 minutes/session ก่อนเพิ่ม delay
- 30 messages/minute/widget
- 60 messages/minute/department
- 120 messages/minute ทั้งระบบในช่วง Pilot
- 2 concurrent runs ต่อ anonymous session

Human messages หลัง handoff ไม่ใช้ LLM rate limit แต่ยังใช้ abuse/rate limit ของ chat ส่วน AI draft ของเจ้าหน้าที่ยังผ่าน budget guard

### File/indexing

- 2 indexing jobs พร้อมกันบน server เริ่มต้น
- 1 active indexing job ต่อแผนก
- queue depth warning 50 jobs, critical 200 jobs

## 7. Performance Objectives

| Metric | เป้าหมาย MVP |
|---|---:|
| API p95 ที่ไม่เรียก LLM | < 300 ms |
| Inbox/message retrieval p95 | < 500 ms |
| Time to first SSE event | < 1 วินาที |
| Time to first LLM token p95 | < 5 วินาที โดยขึ้นกับ provider |
| Public bootstrap p95 | < 300 ms จาก LAN/เว็บไซต์ใกล้เคียง |
| Availability เป้าหมาย Pilot | 99.5% ไม่รวม maintenance ที่ประกาศ |
| Queue wait p95 | < 2 วินาทีสำหรับ chat, < 5 นาทีสำหรับ indexing |

## 8. OpenRouter Capacity และ Cost Telemetry

- ใช้ paid models/credits สำหรับ production; free models ไม่ควรเป็น production dependency
- เก็บ usage object จาก response สุดท้ายของ stream หรือ response ปกติ ซึ่งมี prompt/completion/cached/reasoning tokens และ cost
- จำกัด child LLM calls ต่อคำถามเริ่มต้นไม่เกิน 5 และมี timeout/retry budget กลาง
- Retry เฉพาะ error ที่ retryable พร้อม exponential backoff + jitter และเคารพ `Retry-After`
- ห้าม retry หลังเริ่ม stream แบบอัตโนมัติโดยไม่ตรวจ provider error เพราะอาจเสียค่าใช้จ่ายซ้ำ
- ตั้ง OpenRouter credit alert และตรวจ remaining credit เป็น operational alert แยกจาก budget ภายในแผนก

## 9. Exchange Rate Job

- Source: `https://open.er-api.com/v6/latest/USD`
- ดึงตาม `time_next_update_unix` บวก jitter 5-15 นาที และไม่ถี่กว่าวันละครั้ง
- Cache และเก็บ last-known-good ใน PostgreSQL
- Alert เมื่อเก่ากว่า 48 ชั่วโมง
- Manual fallback โดย Super Admin
- Dashboard แสดง attribution `Rates By Exchange Rate API`
- ใช้เพื่อรายงาน ไม่ใช่อัตราสำหรับ settlement/การเงินทางบัญชี

## 10. Scaling Triggers

### Scale application ก่อน

แยกเป็น 2 application nodes เมื่อเกิดอย่างใดอย่างหนึ่ง:

- CPU > 70% ต่อเนื่อง 15 นาทีในช่วง peak
- API p95 > 500 ms โดยไม่รวม LLM
- concurrent SSE > 100
- chat queue wait p95 > 2 วินาที
- ต้องการ deploy โดยไม่หยุดบริการ

### Scale database/storage

- PostgreSQL RAM working set เกิน 16 GB ต่อเนื่อง
- DB CPU > 60% หรือ query p95 เกินเป้าหมาย
- vector index โตจน vacuum/index maintenance กระทบ chat
- usable storage เกิน 65%
- backup/restore ไม่ผ่าน RTO ที่กำหนด

### เพิ่ม local GPU ภายหลัง

พิจารณาเมื่อมี usage จริงอย่างน้อย 1-3 เดือนและพบว่า:

- OpenRouter cost ต่อเดือนสูงกว่าค่า amortized GPU + operation อย่างมีนัยสำคัญ
- มีข้อกำหนดข้อมูลห้ามส่งออกนอกองค์กร
- ต้องควบคุม latency/model availability เอง

GPU sizing ต้องเลือกจาก model, quantization, context length และ concurrency จริง ไม่ควรซื้อจากจำนวน user เพียงอย่างเดียว

## 11. Production Topology เมื่อระบบโต

```text
Load Balancer
├── App Node A: Nginx, Next.js, FastAPI, workers
└── App Node B: Nginx, Next.js, FastAPI, workers

Data Node
├── PostgreSQL/pgvector
├── Redis
└── MinIO

Backup Target (คนละเครื่อง/คนละ storage failure domain)
```

เมื่อเกินประมาณ 100-150 concurrent sessions หรือจำเป็นต้อง autoscale หลาย service จึงค่อยประเมิน Kubernetes ไม่ควรนำมาเพิ่มภาระการดูแลตั้งแต่ 40 users

## 12. Pilot Measurement Plan

Pilot 2-4 สัปดาห์ต้องเก็บอย่างน้อย:

- active/concurrent users แยก internal/public
- messages per minute และ concurrent SSE
- LLM calls, input/output/cached/reasoning tokens ต่อข้อความ
- OpenRouter latency/error/retry/cost ต่อ model
- PDF pages, extraction time, chunk count และ scanned-page ratio
- Excel rows/sheets, parse time และ peak memory
- MySQL query latency/result size ต่อแผนก
- queue depth/wait time
- DB size growth, vector search p95 และ backup/restore time

นำ p95/p99 และ growth rate จริงมาปรับ quota, worker concurrency, storage forecast และงบประมาณ ไม่ใช้ค่าเฉลี่ยเพียงอย่างเดียว

