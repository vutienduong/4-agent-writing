# Local Content Agents MVP

Python MVP cho pipeline 4 agent viết blog:

1. `Research`
2. `Outline`
3. `Writer`
4. `SEO Audit`

Mục tiêu của scaffold này là chạy local, dễ sửa prompt, tạo artifact rõ ràng và có `--mock` để test end-to-end trước khi gắn API key thật.

Phiên bản hiện tại đã có queue bền bằng SQLite theo topic, worker concurrency, retry riêng cho từng stage, manifest file cho batch hiện tại và metadata đủ chi tiết để resume batch lớn an toàn hơn.

## Cấu trúc

```text
.
├── .env.example
├── prompts/
│   ├── outline.md
│   ├── research.md
│   ├── seo.md
│   └── writer.md
├── src/content_pipeline/
│   ├── agents.py
│   ├── cli.py
│   ├── config.py
│   ├── llm.py
│   ├── models.py
│   ├── orchestrator.py
│   ├── prompting.py
│   └── queue_store.py
└── topics.csv
```

## Cài đặt

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

## Chạy thử không cần API

```bash
PYTHONPATH=src python3 -m content_pipeline.cli run --mock --limit 1
```

Lệnh này sẽ tạo output mẫu trong thư mục `output/`.

## Chạy với OpenAI API

1. Điền `OPENAI_API_KEY` vào `.env`
2. Tuỳ chọn sửa model trong `.env`
3. Chạy:

```bash
PYTHONPATH=src python3 -m content_pipeline.cli run --limit 1
```

Theo README chính thức của SDK `openai-python`, Responses API là API chính và ví dụ Python hiện dùng `client.responses.create(...)` với model như `gpt-5.2`: [openai/openai-python](https://github.com/openai/openai-python)

## Input topics

File `topics.csv` dùng các cột:

- `title`
- `primary_keyword`
- `audience`
- `angle`
- `notes`

Ví dụ:

```csv
title,primary_keyword,audience,angle,notes
Cost Optimization cho AI API,cost optimization ai api,technical founders,practical framework,focus on small team budgets
```

## Output

Mỗi topic tạo một thư mục:

```text
output/
  pipeline_state.sqlite
  queue_manifest.json
  T01-cost-optimization-cho-ai-api/
    01-research.md
    02-outline.md
    03-draft.md
    04-final.md
    metadata.json
```

`metadata.json` lưu:

- trạng thái toàn topic
- stage đang chạy
- trạng thái từng stage
- lịch sử attempt của từng stage
- thời gian chạy
- model sử dụng
- token usage nếu API trả về
- request id nếu có

`pipeline_state.sqlite` lưu:

- hàng đợi job bền qua nhiều lần chạy
- trạng thái job được worker claim
- phục hồi job đang `running` về `pending` ở lần `--resume` sau

`queue_manifest.json` lưu snapshot của batch hiện tại:

- file topics được dùng
- output dir
- queue DB path
- số worker và retry settings
- danh sách job đã chọn cho run đó

## Tuỳ chọn hữu ích

```bash
PYTHONPATH=src python3 -m content_pipeline.cli run --mock --limit 2
PYTHONPATH=src python3 -m content_pipeline.cli run --resume
PYTHONPATH=src python3 -m content_pipeline.cli run --style-guide path/to/style-guide.md
PYTHONPATH=src python3 -m content_pipeline.cli run --topic-row 3
PYTHONPATH=src python3 -m content_pipeline.cli run --workers 4 --stage-max-attempts 4 --retry-backoff-seconds 3
```

## Queue Và Retry

- Queue chạy theo `topic`, còn 4 stage bên trong mỗi topic vẫn giữ thứ tự để không vỡ handoff.
- Worker claim job trực tiếp từ `pipeline_state.sqlite`, không còn phụ thuộc vào queue chỉ sống trong RAM.
- `--workers` quyết định số topic xử lý song song.
- `--stage-max-attempts` quyết định số lần thử tối đa cho từng stage.
- `--retry-backoff-seconds` là backoff cơ sở theo exponential backoff: `base`, `2x`, `4x`, ...
- `--resume` sẽ:
  - bỏ qua topic đã có `04-final.md`
  - hoặc tái dùng các artifact stage đầu nếu topic đang dở giữa chừng
  - hoặc khôi phục các job từng bị kẹt ở trạng thái `running` sau khi process bị tắt

Ví dụ batch ổn định hơn:

```bash
PYTHONPATH=src python3 -m content_pipeline.cli run \
  --workers 4 \
  --stage-max-attempts 4 \
  --retry-backoff-seconds 3 \
  --resume
```

## Bước tiếp theo nên làm

Sau khi MVP này chạy ổn, bạn có thể nâng cấp theo thứ tự:

1. Thêm reviewer rules và scoring
2. Lưu metadata/job analytics vào Postgres
3. Thêm dashboard tiến độ và chi phí
4. Tách model riêng cho từng agent
5. Thêm scheduler định kỳ và publish hooks
