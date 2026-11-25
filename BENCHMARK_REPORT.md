# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được lấy trực tiếp từ các file JSON trong `reports/` (chạy thật trên máy). Các mục Phần 4 & 5 cần Docker Compose sẽ bổ sung sau khi cài Docker.

**Họ tên:** Kiều Văn Thắng
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows (Python 3.14.10) — chạy local `develop/` (chưa có Docker)

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | 95% người dùng nhận được phản hồi dưới 0.5 giây, đảm bảo trải nghiệm mượt khi có thêm bước retrieval (~20ms) và LLM (~120–180ms). |
| Error rate `/ask` | < 2.0 % | Chấp nhận một tỉ lệ nhỏ lỗi upstream tạm thời (~1% từ `MOCK_ERROR_RATE`), nhưng chặn khi lỗi tăng bất thường. |
| Accuracy trên golden dataset | ≥ 85 % (mục tiêu sau sửa KB: 100%) | Đảm bảo agent trả lời đúng kiến thức cốt lõi trước khi deploy và không bị regression so với phiên bản trước. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.9 | 202.1 | 237.4 | 1711.8 | 0.67% | PASS |
| 10 | 35.84 | 203.3 | 500.9 | 1731.0 | 0.67% | FAIL (p95 > 500ms) |
| 50 | 95.45 | 218.7 | 563.2 | 1743.3 | 1.00% | FAIL (p95 > 500ms) |
| 100 | 57.44 | 574.8 | 3389.2 | 3580.3 | 2.00% | FAIL (p95 > 500ms) |

**Nhận xét:** RPS **không** tăng tuyến tính theo concurrency. Từ c=1 lên c=10 và c=50, RPS tăng mạnh (3.9 → 35.84 → 95.45 req/s) nhờ async I/O xử lý đồng thời; nhưng đến c=100, RPS **giảm xuống 57.44 req/s** và p50/p95 tăng vọt (p50 = 574.8 ms, p95 = 3389.2 ms) do quá tải event loop / kết nối đồng thời trên 1 process uvicorn (saturation).

### 2.2 Tail latency (`--requests 300 --concurrency 20`)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 223.2 | 493.3 | 529.7 |
| 0.03 (mặc định) | 309.3 | 1681.6 | 1722.7 |
| 0.1 | 344.2 | 1695.5 | 1716.5 |

**Nhận xét:** `p95` và `p99` nhạy nhất với các request chậm bất thường: chỉ với 3% request chậm (`MOCK_SLOW_RATE=0.03`), `avg` chỉ tăng từ 223.2ms lên 309.3ms (vẫn dưới 500ms), trong khi `p95` nhảy vọt từ 493.3ms lên **1681.6ms** (vi phạm SLO). Vì vậy không nên đặt SLO theo `average` vì trung bình che giấu trải nghiệm tệ của nhóm người dùng ở đuôi phân phối (tail latency).

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 56.8 | 109.3 | 112.7 |
| Tổng cost (USD) | $0.000400 | $0.000764 | $0.000782 |
| Cost / câu đúng (USD) | $0.00040035 | $0.00003639 | $0.00003400 |
| Quality gate | FAIL | PASS (min 80%) | PASS (min 100%) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry `(["jwt", "api key"], ...)` vào `KNOWLEDGE_BASE` trong `mock_llm.py` giải thích JWT có chữ ký số và thời gian hết hạn. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry `(["kubernetes", "hpa"], ...)` vào `KNOWLEDGE_BASE` trong `mock_llm.py` giải thích HPA scale theo CPU, memory hoặc custom metrics. |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- Agent v2 (có retrieval) tốn gần gấp đôi số token/câu (109.3–112.7 so với 56.8) và tổng chi phí ($0.000782 so với $0.000400), đồng thời latency p95 tăng thêm ~33ms (199.8ms → 233.0ms).
- Tuy nhiên, accuracy tăng từ **4.3% lên 100.0%**, kéo **cost / câu đúng** giảm hơn **11 lần** (từ `$0.00040035` xuống `$0.00003400`), chứng minh việc thêm bước retrieval là hoàn toàn xứng đáng.
- **Tích hợp CI/CD Quality Gate:** Chạy `python eval/run_eval.py --min-accuracy 0.85 --baseline reports/eval_v2.json`; script trả về **exit code `1`** nếu accuracy thấp hơn ngưỡng hoặc có bất kỳ câu nào bị regression so với baseline, giúp GitHub Actions tự động chặn merge/deploy.

---

## 4. Observability stack (production — cần Docker)

### 4.1 Screenshot
- [ ] Dashboard Grafana khi đang có tải (`screenshots/grafana-dashboard.png`)
- [ ] Một trace chậm trong Jaeger (`screenshots/jaeger-slow-trace.png`)
- [ ] Một trace lỗi trong Jaeger (`screenshots/jaeger-error-trace.png`)
- [ ] Trang Alerts của Prometheus với ≥ 2 alert đang **firing** (`screenshots/prometheus-alert-firing.png`)

### 4.2 Thí nghiệm "phá hệ thống"
*(Bổ sung sau khi cài Docker và chạy stack `06-lab-complete/benchmark-observability/production/`)*

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**
Chạy eval tự động (`run_eval.py`) trên golden dataset trong pipeline CI/CD trước khi deploy (quality gate), kết hợp theo dõi user feedback (thumbs up/down) hoặc LLM-as-judge sampling trên production traffic.

### 4.3 Debug bằng trace
*(Bổ sung `trace_id`, span chậm nhất và dòng log JSON sau khi chạy Jaeger trên Docker)*

---

## 5. Benchmark scaling (production, Locust headless — cần Docker)
*(Bổ sung từ `scale_1_stats.csv` và `scale_3_stats.csv` sau khi chạy Locust trên Docker)*

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. Không dùng latency trung bình (`avg`) làm SLO vì tail latency (`p95`/`p99`) phản ánh trải nghiệm thực tế của người dùng bị chậm.
  2. So sánh hai phiên bản agent cần nhìn vào **cost / câu đúng** thay vì chỉ nhìn tổng chi phí hay token thô.
  3. Cần kết hợp cả 3 trụ cột Metrics – Traces – Logs (liên kết qua `trace_id`) và eval chất lượng trong CI/CD vì hạ tầng khỏe (metrics xanh) không đảm bảo câu trả lời đúng.
- Nếu đưa agent này lên production thật, nên thêm metric/alert về: Redis latency / connection pool saturation, tỉ lệ `429`/`402` theo từng client, và drift chất lượng (eval định kỳ).
