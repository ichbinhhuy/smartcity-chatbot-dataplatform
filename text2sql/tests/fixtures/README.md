# tests/fixtures/

`cube_meta.json` — bản chụp response thật của Cube Meta API
(`GET {cube_api_url}/meta`), dùng làm fixture `catalog` (session-scoped) trong
`tests/conftest.py` cho toàn bộ test suite. KHÔNG viết tay — file này phải
khớp catalog thật, nếu không test sẽ pass/fail dựa trên dữ liệu không còn
đúng với hệ thống (đã từng xảy ra: fixture thiếu `districts.total_sections`,
`districts.total_records`, `city_health_index` measure mới, `smart_lighting`
measure mới — khiến `test_catalog.py`/`test_orchestrator.py` fail vì lệch số
lượng measures/dimensions so với catalog thật — xem Bug 5 trong kế hoạch fix).

## Khi nào cần regenerate

Bất kỳ khi nào sửa cube schema YAML (`data-transform/model/cubes/**/*.yml`) —
thêm/bớt/đổi tên measure hoặc dimension — PHẢI regenerate lại file này, nếu
không test sẽ chạy trên catalog cũ, không phản ánh đúng hệ thống thật.

## Cách regenerate

```bash
# Cube Core phải đang chạy và đã compile xong schema mới nhất
curl -s http://localhost:4000/cubejs-api/v1/meta -H "Authorization: <CUBE_API_TOKEN>" \
  | python3 -m json.tool > text2sql/tests/fixtures/cube_meta.json
```

(`CUBE_API_TOKEN` mặc định dev là `devsecret`, xem `text2sql/.env`.)

Sau khi regenerate, chạy lại `pytest tests/test_catalog.py tests/test_orchestrator.py
tests/test_retriever.py` để xác nhận không có test nào giả định sai số lượng
measures/dimensions cụ thể.
