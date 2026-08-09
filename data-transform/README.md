# Cube smart city demo — semantic layer có vừa đủ để minh họa

Project này mô phỏng một hệ thống semantic layer ở quy mô "vừa đủ" (không quá nhỏ như demo 1 bảng, không quá phức tạp như enterprise thật) — có 3 domain riêng biệt, 1 dimension dùng chung, 1 composite metric xuyên domain, và 1 ví dụ phân quyền (row-level security).

## Kiến trúc dữ liệu trong demo này

```
districts (dimension dùng chung)
   |
   +-- traffic_flow      (domain: giao thông)
   +-- grid_load         (domain: năng lượng)
   +-- air_quality       (domain: môi trường)
   |
   +-- city_health_snapshot (VIEW gộp cả 3 domain -> composite metric)
```

`city_health_snapshot` mô phỏng đúng 1 bước "transform" (trong thực tế sẽ là 1 dbt model) gộp dữ liệu từ 3 domain lại theo từng quận/ngày, trước khi Cube định nghĩa lại thành 1 metric tên `avg_city_health_index`.

## Cấu trúc file

```
cube-smartcity/
├── docker-compose.yml
├── init.sql                          # data + view gộp 3 domain
├── cube.js                           # config phân quyền (row-level security)
└── model/cubes/
    ├── shared/districts.yml          # dimension dùng chung
    ├── traffic/traffic_flow.yml      # có sẵn pre-aggregation
    ├── energy/grid_load.yml
    ├── environment/air_quality.yml
    └── composite/city_health_index.yml
```

## Cách chạy

```bash
cd cube-smartcity
docker compose up
```

Mở http://localhost:4000 sau khi container đã sẵn sàng.

## Test 1: Metric từng domain riêng lẻ

Trong Playground, thử:
- Measure `Traffic Flow Avg Congestion Index`, dimension `Districts Name`
- Measure `Grid Load Avg Renewable Pct`, dimension `Districts Name`
- Measure `Air Quality Avg Aqi`, dimension `Districts Name`

Mỗi domain hoạt động độc lập, giống 3 team khác nhau tự quản lý cube của mình.

## Test 2: Composite metric xuyên domain

Chọn measure `City Health Index Avg City Health Index`, dimension `Districts Name` — đây là một con số duy nhất gộp từ cả 3 domain, bạn không cần tự tính công thức `(traffic + energy + air) / 3` mỗi lần hỏi, vì nó đã được tính sẵn trong view và Cube chỉ expose lại.

Bấm tab SQL để xem Cube đang đọc thẳng từ view `city_health_snapshot`, không phải từ 3 bảng gốc — đây chính là điểm quan trọng: **composite metric nên được tính sẵn ở tầng transform (dbt/view), không nên nhồi công thức phức tạp trực tiếp vào semantic layer**.

## Test 3: Pre-aggregation (đã cấu hình sẵn cho traffic_flow)

Mở tab SQL sau khi query `traffic_flow` — nếu query khớp với pre-aggregation `daily_by_district` đã khai báo, Cube sẽ đọc từ bảng cache riêng thay vì quét lại bảng gốc. Thử đổi granularity/dimension khác đi để thấy khi nào Cube dùng được cache, khi nào phải quét lại.

## Test 4: Phân quyền theo vai trò (row-level security)

File `cube.js` đã cấu hình: nếu request có kèm "district" trong security context, Cube sẽ tự động lọc chỉ trả về dữ liệu của district đó.

Để test, cần tạo 1 JWT ký bằng secret `devsecret` (giống secret trong `docker-compose.yml`), với payload chứa `district`. Ví dụ dùng Node để tạo token nhanh:

```bash
node -e "
const jwt = require('jsonwebtoken');
console.log(jwt.sign({ district: 'District 2' }, 'devsecret'));
"
```

(Cần `npm install jsonwebtoken` trước khi chạy lệnh trên, hoặc dùng jwt.io để tự tạo token thủ công)

Sau đó gọi API kèm token này:

```bash
curl -H "Authorization: <token-vừa-tạo>" -G http://localhost:4000/cubejs-api/v1/load \
  --data-urlencode 'query={
    "measures": ["traffic_flow.avg_congestion_index"],
    "dimensions": ["districts.name"]
  }'
```

Kết quả sẽ **chỉ trả về District 2**, dù query không hề ghi điều kiện lọc nào — Cube tự động áp đặt filter dựa trên token, giống đúng tình huống "cán bộ phụ trách quận 2 đăng nhập vào hệ thống, chỉ được thấy dữ liệu quận mình".

## Bài tập để hiểu sâu hơn

1. Thử đổi trong `cube.js`, đổi từ lọc theo `districts.name` sang lọc theo `districts.region` — tương tự tình huống phân quyền theo miền Bắc/Nam/Trung Tâm thay vì từng quận riêng lẻ.

2. Thêm 1 domain mới (ví dụ `waste_collection`), rồi sửa lại view `city_health_snapshot` để gộp thêm domain này vào công thức composite — qua đó thấy rõ: mỗi khi thêm 1 domain mới vào "chỉ số tổng hợp", phải sửa ở tầng transform (view/dbt), không sửa trực tiếp trong Cube model.

3. Thử tắt pre-aggregation đi (xóa phần `pre_aggregations` trong `traffic_flow.yml`), so sánh tốc độ query trước/sau khi tắt.

## Dùng thử xong

```bash
docker compose down -v
```
