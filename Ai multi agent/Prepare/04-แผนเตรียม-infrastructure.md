# แผนเตรียม Infrastructure — Multi-Agent AI Q&A Platform

## 1. หลักการเลือก Infrastructure

ระบบนี้มี 3 ส่วนที่ต้องการทรัพยากรต่างกันชัดเจน: (1) API/orchestration layer เบา ใช้ CPU ปกติ (2) LLM local inference ต้องการ GPU ถ้าจะรันโมเดลใหญ่ (3) งาน background เช่น index PDF/Excel เป็นงานที่ใช้เวลานาน ควรแยกออกจาก request-response หลัก — ออกแบบให้แยก scale แต่ละส่วนได้อิสระจากกัน

## 2. Operating System

- **Ubuntu Server 24.04 LTS** สำหรับทุก host (application server, worker, database) — เลือกเพราะ LTS ระยะ support ยาว, รองรับ NVIDIA driver/CUDA สำหรับ GPU inference ได้ดี, ecosystem Docker/Kubernetes เสถียร
- ถ้าใช้ managed cloud (AWS/GCP/Azure) ให้ใช้ image Ubuntu LTS เดียวกันเพื่อความสอดคล้องระหว่าง dev/staging/prod

## 3. Containerization

- **Docker + Docker Compose** สำหรับ local development และ staging ขนาดเล็ก
- **Kubernetes (K8s)** สำหรับ production เมื่อ traffic เริ่มสูงหรือมีหลายแผนกพร้อมกันจำนวนมาก — เหตุผลหลักคือ autoscaling ของ agent worker และ rolling deployment โดยไม่ downtime
- **ข้อกำหนดสำหรับ MVP 40 users:** เริ่ม production ด้วย Docker Compose บน server ภายในองค์กร ไม่ใช้ Kubernetes จนกว่า traffic/concurrency หรือข้อกำหนด high availability จะถึง trigger ที่กำหนดใน `Prepare/06-capacity-sizing-and-baseline.md`
- แยก image ต่อ service: `api` (FastAPI), `worker` (background indexing PDF/Excel), `web` (Next.js admin panel), `embed-widget` (static JS bundle)
- ใช้ `.dockerignore` และ multi-stage build ลดขนาด image, scan image หา vulnerability ก่อน push (เช่น Trivy) ทุกครั้งใน CI

## 4. ฐานข้อมูลและ Storage

| องค์ประกอบ | เทคโนโลยีที่แนะนำ | หมายเหตุ |
|---|---|---|
| Metadata DB (users, agents, permissions, usage_logs) | PostgreSQL 16+ | เปิด extension `pgvector` ในตัวเดียวกัน ลดจำนวนระบบที่ต้องดูแล |
| Vector store (PDF chunks) | pgvector (ใน Postgres เดียวกัน) หรือ Qdrant แยกถ้า scale ใหญ่ | เริ่มจาก pgvector ก่อน ค่อยแยกเมื่อ query ช้า |
| Cache / job queue | Redis | ใช้เป็น broker สำหรับงาน background (index PDF, sync Excel) ผ่าน Celery หรือ RQ |
| Object storage | S3-compatible (AWS S3 หรือ MinIO self-host) | เก็บไฟล์ Excel/PDF ที่ admin อัปโหลด ไม่เก็บใน filesystem ของ container |
| Customer MySQL | **ไม่ได้อยู่ใน infra ของเรา** — เป็นฐานข้อมูลของแต่ละแผนก/ลูกค้าที่ agent ต่อออกไปอ่านอย่างเดียว | ต้องมั่นใจว่า network เข้าถึงได้แบบปลอดภัย (VPN/private link) ไม่เปิด public |

## 5. LLM Serving (Local Model)

- **Ollama** สำหรับเริ่มต้น/ทดสอบ หรือทีมเล็กที่อยากตั้งค่าเร็ว
- **vLLM** สำหรับ production ที่ต้องการ throughput สูงและรองรับ concurrent request หลาย agent พร้อมกัน
- **GPU requirement:** ขึ้นกับขนาดโมเดล — โมเดล 7-8B รันได้บน GPU 1 ตัว (เช่น RTX 4090/L4, VRAM ~16-24GB) ส่วนโมเดล 70B ต้องการ GPU หลายตัวหรือ VRAM รวม ~140GB+ (เช่น A100/H100 หลายใบ หรือใช้ quantization ลดขนาดลง)
- ถ้าไม่มี GPUในองค์กร ให้เริ่มจาก **OpenRouter อย่างเดียวก่อน** แล้วค่อยเพิ่ม local model ทีหลังเมื่อ volume การใช้งานสูงพอที่จะคุ้มค่า GPU

## 6. Networking & Security Layer

- **Reverse proxy:** Nginx หรือ Traefik — จัดการ TLS termination, routing ไปยัง service ต่าง ๆ, rate limiting ระดับ network สำหรับ embed widget
- **Secret management:** HashiCorp Vault หรือ cloud KMS (AWS KMS/GCP Secret Manager) — เก็บ credential ของ MySQL/API key ต่าง ๆ ตามแผนความปลอดภัยที่วางไว้
- **Firewall/Security group:** จำกัด inbound เฉพาะ port ที่จำเป็น (443 สำหรับ public, จำกัด internal service ให้เข้าถึงกันเองในวง private network เท่านั้น)
- **VPN/Private link:** สำหรับเชื่อมต่อไปยัง MySQL ของแต่ละแผนกที่อาจอยู่คนละ network

## 7. Monitoring & Observability

- **Metrics:** Prometheus + Grafana — ติดตาม latency ของแต่ละ agent, จำนวน token/cost แบบ real-time, การใช้ GPU
- **Logging:** Loki หรือ ELK stack — รวม log จากทุก service, ต้องมั่นใจว่าไม่มี credential/PII หลุดใน log (ตามแผนความปลอดภัย)
- **Alerting:** ตั้ง alert เมื่อ error rate สูงผิดปกติ, GPU/CPU เต็ม, budget การใช้ LLM ใกล้เกินที่ตั้งไว้
- **Tracing:** OpenTelemetry สำหรับ trace request ข้าม coordinator → agent ย่อย → data source ช่วย debug ปัญหา latency

## 8. Environment แยกตามระดับ

| Environment | วัตถุประสงค์ | ขนาด infra |
|---|---|---|
| Development | ทีมพัฒนาทดสอบ local | Docker Compose บนเครื่อง dev, mock data source |
| Staging | ทดสอบก่อน release, UAT | Kubernetes cluster ขนาดเล็ก, ข้อมูลจำลอง ไม่ใช่ข้อมูลจริงของลูกค้า |
| Production | ใช้งานจริง | Kubernetes cluster ที่ scale ได้, แยก network zone ตาม security plan |

## 9. Sizing เบื้องต้น (จุดเริ่มต้น ปรับตาม traffic จริง)

- **API/orchestration:** 2-4 vCPU, 8GB RAM ต่อ instance, เริ่ม 2 instance สำหรับ high availability
- **Worker (background indexing):** 2 vCPU, 4GB RAM, scale ตามคิวงาน
- **Postgres:** 4 vCPU, 16GB RAM, SSD storage, ตั้ง read replica เมื่อ traffic การอ่าน dashboard สูง
- **Redis:** 1-2 vCPU, 2GB RAM เพียงพอสำหรับ queue ขนาดกลาง
- **GPU node (ถ้าใช้ local LLM):** อย่างน้อย 1 node แยกจาก API node เพื่อไม่ให้แย่ง resource กัน

สำหรับขนาดที่ล็อกตาม MVP 40 users, quota, rate limit และ scaling trigger ให้ยึด `Prepare/06-capacity-sizing-and-baseline.md` เป็นรายละเอียดล่าสุด โดยระยะแรกใช้ OpenRouter เป็นหลักและยังไม่จัดหา GPU

## 10. Backup & Disaster Recovery

- Postgres: automated daily backup + point-in-time recovery, ทดสอบ restore จริงอย่างน้อยไตรมาสละครั้ง
- Object storage (Excel/PDF): เปิด versioning, replicate ข้ามพื้นที่ (cross-region) ถ้างบประมาณอนุญาต
- เก็บ Infrastructure-as-Code (Terraform) ไว้ให้ rebuild environment ทั้งหมดได้จาก config โดยไม่ต้องตั้งมือ
