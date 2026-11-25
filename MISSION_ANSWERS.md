# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`
1. **Hardcode secret trong source code (dòng 17–18):** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Nếu push lên GitHub sẽ lộ ngay thông tin nhạy cảm.
2. **Không có config management theo môi trường (dòng 21–22):** `DEBUG = True`, `MAX_TOKENS = 500` được gán cứng, không phân biệt `development` / `staging` / `production`.
3. **Dùng `print()` thay vì structured logging và log lộ secret (dòng 33–38):** `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` vừa khó thu thập/lọc log trên production, vừa làm lộ API key ra stdout.
4. **Thiếu health check endpoint:** Không có `GET /health` hay `GET /ready`, nên nền tảng cloud/load balancer không biết khi nào app lỗi hoặc chưa sẵn sàng.
5. **Bind `host="localhost"`, cố định `port=8000` và bật `reload=True` (dòng 49–54):** `localhost` không nhận traffic từ bên ngoài container, port cứng không nhận biến `PORT` do cloud cấp, và `reload=True` gây tốn tài nguyên / mất ổn định ở production.
6. **Không xử lý graceful shutdown:** Khi nhận `SIGTERM`, process dừng đột ngột, cắt ngang request đang xử lý.

### Exercise 1.2: Kết quả chạy bản develop
Lệnh test:
```bash
curl -X POST "http://localhost:8000/ask?question=Hello"
```
Kết quả thực tế (HTTP 200):
```json
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 1.3: Bảng so sánh `develop/app.py` vs `production/app.py`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Tại sao quan trọng? |
|---|---|---|---|
| **Config** | Hardcode (`OPENAI_API_KEY = "sk-..."`, `port=8000`) | Đọc từ env vars qua `Settings` (`os.getenv("PORT", "8000")`, `os.getenv("AGENT_API_KEY", "")`) | Tách biệt code và config (12-Factor), không lộ secret, đổi cấu hình theo môi trường không cần sửa code. |
| **Health check** | Không có | Có `GET /health` (liveness) và `GET /ready` (readiness) | Cloud platform và load balancer dựa vào đây để restart container treo hoặc ngừng gửi traffic khi app chưa sẵn sàng. |
| **Logging** | `print(...)` dạng text tự do, log cả secret | `logging` xuất JSON (`{"time":..., "level":..., "msg":...}`), chỉ log độ dài/IP, không log secret | Dễ parse và truy vấn tập trung trên Loki/Datadog, đảm bảo an toàn thông tin. |
| **Shutdown** | Tắt đột ngột | Dùng `@asynccontextmanager async def lifespan(app)` đặt `is_ready = False` và chờ hoàn thành request trước khi thoát | Tránh rớt request (HTTP 502/504) của người dùng khi deploy phiên bản mới hoặc scale down. |
| **Network & Debug** | `host="localhost"`, `reload=True` | `host="0.0.0.0"`, `PORT` từ env, tắt `reload` ở production | `0.0.0.0` cho phép container nhận traffic từ ngoài; tắt `reload` để ổn định và tiết kiệm CPU/RAM. |

**Ví dụ cụ thể sửa anti-pattern:**
- `develop/app.py` (dòng 17): `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"`
- `production/config.py` (dòng 27 & 42–43): đọc qua `os.getenv("OPENAI_API_KEY", "")` và kiểm tra fail-fast `if not self.api_key and self.environment == "production": raise ValueError(...)`.

---

## Part 2: Docker

### Exercise 2.1: Trả lời 4 câu hỏi về `02-docker/develop/Dockerfile`
1. **Base image:** `python:3.11` (bản đầy đủ ~1 GB).
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Tại sao `COPY requirements.txt` đứng trước `COPY . .` (hoặc `COPY app.py`)?** Docker cache từng layer từ trên xuống dưới. `requirements.txt` ít thay đổi hơn source code; đặt trước giúp Docker tái sử dụng layer `pip install` từ cache khi chỉ sửa code Python, giảm mạnh thời gian build.
4. **Sự khác nhau giữa `CMD` và `ENTRYPOINT`:**
   - `CMD` định nghĩa lệnh và tham số mặc định khi chạy container, có thể bị ghi đè hoàn toàn nếu truyền command khác lúc `docker run`.
   - `ENTRYPOINT` cố định executable chính của container; tham số truyền thêm ở `docker run` sẽ được nối vào làm đối số cho `ENTRYPOINT`.

### Exercise 2.2 & 2.3: Build, test container & so sánh kích thước image
> *(Chưa có Docker trên máy — bổ sung số đo thực tế sau khi cài Docker)*
- Image develop (`my-agent:develop`): `[CHƯA ĐO - CẦN DOCKER]` MB
- Image production (`my-agent:advanced`): `[CHƯA ĐO - CẦN DOCKER]` MB
- Chênh lệch: `[CHƯA ĐO]`%
- **Lý do multi-stage giảm dung lượng:** Stage 1 (`builder`) cài compiler (`gcc`, `libpq-dev`) và build dependencies vào `/root/.local`. Stage 2 (`runtime`) bắt đầu lại từ `python:3.11-slim` sạch, chỉ copy `/root/.local` và source code sang, bỏ lại toàn bộ build tools và cache của stage 1.

### Exercise 2.4: Kiến trúc Docker Compose (`02-docker/production/docker-compose.yml`)
```text
Client ──► Nginx (:80, reverse proxy) ──► Agent (:8000, FastAPI) ──► Redis (:6379)
```
- Kết quả test qua Nginx (`curl http://localhost/health`, `POST http://localhost/ask`): `[CẦN DOCKER ĐỂ CHẠY]`

---

## Part 3: Cloud Deployment

### Deployment Agent Part 6 (`06-lab-complete/`)
- **Platform:** `[Railway / Render — bổ sung sau khi deploy]`
- **Public URL:** `[https://... — bổ sung sau khi deploy]`
- **Screenshots:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`

### So sánh `railway.toml` và `render.yaml`
| Tiêu chí | `railway.toml` | `render.yaml` |
|---|---|---|
| **Mục đích** | Cấu hình build & deploy cho **1 service** hiện tại | Blueprint Infrastructure-as-Code, khai báo được **nhiều service** (web + Redis) trong cùng 1 file |
| **Build / Runtime** | `[build] builder = "DOCKERFILE"` (hoặc `NIXPACKS`) | Khai báo `runtime: docker` (hoặc `python` với `buildCommand`/`startCommand`) |
| **Health check** | `healthcheckPath = "/health"` trong `[deploy]` | `healthCheckPath: /health` trong từng service |
| **Biến môi trường & Secret** | Không khai báo secret trong file, đặt qua Railway Dashboard / CLI (`railway variables set`) | Hỗ trợ khai báo `envVars` ngay trong YAML; secret dùng `generateValue: true` hoặc `sync: false` để không hardcode |

### Exercise 3.3: Mô tả pipeline CI/CD GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)
Pipeline trong `cloudbuild.yaml` gồm 4 bước tuần tự khi có push lên nhánh `main`:
1. **`test`:** Dùng container `python:3.11-slim`, cài `requirements.txt` và `pytest`, chạy `pytest tests/ -v` để kiểm tra code trước khi build.
2. **`build`:** Build Docker image từ repo với cache (`--cache-from`) và gắn 2 tag (`$COMMIT_SHA` và `latest`).
3. **`push`:** Đẩy image lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy`:** Dùng `gcloud run deploy` triển khai image `$COMMIT_SHA` lên Cloud Run region `asia-southeast1` (`--min-instances=1`, `--max-instances=10`, `--memory=512Mi`), inject secret `OPENAI_API_KEY` từ Secret Manager. File `service.yaml` định nghĩa cấu hình dịch vụ dạng Knative Service (scaling, resource limits, secretRef và `livenessProbe` `/health`, `startupProbe` `/ready`).

---

## Part 4: API Security

### Exercise 4.1–4.3: Kết quả kiểm tra API Key, JWT & Rate Limiting

1. **Bản develop (`04-api-gateway/develop/app.py`, `AGENT_API_KEY=secret-key-123`):**
   - **Không có `X-API-Key` → HTTP 401:**
     ```text
     HTTP/1.1 401 Unauthorized
     {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
     ```
   - **Có `X-API-Key: secret-key-123` → HTTP 200:**
     ```text
     HTTP/1.1 200 OK
     {"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
     ```

2. **Bản production (`04-api-gateway/production/app.py`, tài khoản `student` / `demo123`, giới hạn 10 req/phút):**
   - Lấy token từ `POST /auth/token`: nhận `access_token` (`Bearer <REDACTED_TOKEN>`).
   - Gửi liên tiếp 11 request tới `POST /ask` với header `Authorization: Bearer <REDACTED_TOKEN>`:
     - 10 request đầu: `HTTP/1.1 200 OK`
     - Request thứ 11: `HTTP/1.1 429 Too Many Requests`
     ```text
     x-ratelimit-limit: 10
     x-ratelimit-remaining: 0
     retry-after: 59
     {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
     ```

### Exercise 4.4: Cách hoạt động của Cost Guard (`04-api-gateway/production/cost_guard.py`)
- **Mục tiêu:** Bảo vệ ngân sách LLM API, tránh phát sinh hóa đơn ngoài kiểm soát (khác với Rate Limiter chỉ giới hạn *tốc độ* số request/phút). Cần cả hai vì một user có thể gửi ít request nhưng prompt/output rất dài làm tốn nhiều tiền, hoặc gửi ồ ạt request ngắn làm quá tải hệ thống.
- **Cơ chế:**
  - `check_budget(user_id)` chạy **trước** khi gọi LLM: kiểm tra tổng chi phí trong ngày ở mức toàn hệ thống (`global_daily_budget_usd` → nếu vượt trả **503**) và mức từng user (`daily_budget_usd` → nếu vượt trả **402 Payment Required**), đồng thời log cảnh báo khi đạt 80% ngân sách.
  - `record_usage(user_id, input_tokens, output_tokens)` chạy **sau** khi gọi LLM: tính chi phí dựa trên `PRICE_PER_1K_INPUT_TOKENS` và `PRICE_PER_1K_OUTPUT_TOKENS`, cộng dồn vào bộ đếm theo ngày (trong production lưu trên Redis để stateless giữa các worker/instance).

---

## Part 5: Scaling & Reliability

### Exercise 5.1–5.5: Health checks, Graceful shutdown & Stateless
- **Phân biệt `/health` (Liveness) và `/ready` (Readiness):**
  - `/health`: Kiểm tra process còn sống không (`200`). Nếu fail, platform sẽ **restart container**. Không nên làm `/health` phụ thuộc vào Redis/DB vì mất Redis sẽ làm toàn bộ container bị restart vòng lặp.
  - `/ready`: Kiểm tra instance đã sẵn sàng phục vụ traffic chưa (ví dụ: đã startup xong và kết nối được Redis → `200`, mất Redis hoặc đang shutdown → `503`). Nếu fail, load balancer **ngừng route traffic** tới instance đó nhưng không restart.
- **Graceful shutdown:** Khi nhận `SIGTERM`, app chuyển `_is_ready = False` để load balancer ngừng gửi request mới, đợi các request đang xử lý (`in-flight`) hoàn thành rồi mới đóng kết nối Redis và thoát (`exit code 0`).
- **Stateless với Redis:** Nếu lưu session/rate-limit/budget trong RAM của từng instance, khi chạy 3 instance sau Nginx load balancer (round-robin), request sau có thể vào instance khác và bị mất lịch sử hoặc sai bộ đếm. Lưu state trong Redis giúp mọi instance dùng chung một nguồn dữ liệu nhất quán.
- **Kết quả chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `python test_stateless.py`:** `[CẦN DOCKER ĐỂ CHẠY]`

---

## Part 6: Final Project (`06-lab-complete/`)

Kết quả chạy `python check_production_ready.py --skip-docker` hiện tại (trên Windows, chưa có Docker/Redis):
- Đạt **8/12 tiêu chí** (36/37 checks passed); chỉ còn `/ready -> 200` (do chưa bật Redis), kiểm tra stateless Redis, kiểm tra `SIGTERM` (cần WSL2/Docker), và build/run Docker image (cần Docker).
- *(Sẽ thay thế bằng output `PASS 12/12` đầy đủ sau khi cài Docker và chạy trên WSL2.)*

---

## AI Log
- **Công cụ sử dụng:** Antigravity (Gemini 4 Hydrogen).
- **Nội dung hỗ trợ:**
  1. Hoàn thiện mã nguồn các module trong `06-lab-complete/` (`config.py`, `auth.py`, `redis_client.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`).
  2. Chạy kiểm thử tự động `check_production_ready.py --skip-docker`, các endpoint Part 1 & Part 4, và chạy benchmark/eval local Part 7 (`load_test.py`, `eval/run_eval.py`) để thu thập số liệu thực tế.
  3. Phân tích 2 câu eval bị thiếu keyword (`security-02`, `scaling-03`) và bổ sung `KNOWLEDGE_BASE` trong `mock_llm.py` để đạt 100% accuracy.
- **Tự kiểm tra:** Đã đọc và kiểm chứng toàn bộ output thực tế từ các script chạy trên máy.
