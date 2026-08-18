"""Benchmark script cho lớp Retrieval (Qdrant RRF Hybrid Search)."""

import time
from app.server import get_catalog
from app.retrieval.retriever import CatalogRetriever

catalog = get_catalog()
retriever = CatalogRetriever(catalog)

test_questions = [
    "So sánh chỉ số đáng sống Livability 3 phân đoạn đường",
    "Chỉ số đáng sống ở Khu biệt thự hôm nay là bao nhiêu?",
    "Chất lượng không khí AQI trung bình hôm nay là bao nhiêu?",
    "Nồng độ bụi mịn PM2.5 trung bình ở Căn hộ trong 7 ngày qua thế nào?",
    "Tốc độ giao thông trung bình ở Khu biệt thự là bao nhiêu?",
    "Lưu lượng xe trung bình ở TTTM hôm qua là bao nhiêu?",
    "Tỷ lệ đỗ xe trung bình ở phân khu Căn hộ là bao nhiêu?",
    "Số chỗ đỗ xe còn trống ở TTTM là bao nhiêu?",
    "Tổng điện năng tiêu thụ chiếu sáng ở Khu biệt thự là bao nhiêu?",
    "Số lượng bóng đèn hỏng ở Căn hộ là bao nhiêu?",
]

print("======================================================================")
print("🚀 BẮT ĐẦU BENCHMARK 10 CÂU HỎI RETRIEVAL LAYER (QDRANT RRF HYBRID)")
print("======================================================================\n")

latencies = []

for i, q in enumerate(test_questions, 1):
    t0 = time.time()
    res = retriever.retrieve(q, top_k=5)
    lat = (time.time() - t0) * 1000
    latencies.append(lat)

    print(f'[{i}/10] ❓ Câu hỏi: "{q}"')
    print(f"     ⏱️  Latency  : {lat:.2f} ms")
    print(f"     📊  Measures : {res['measures']}")
    print(f"     📌  Dimensions: {res['dimensions']}")
    print(f"     🏛️  Cubes    : {res['cubes']}\n")

avg_lat = sum(latencies) / len(latencies)
print("======================================================================")
print(f"✅ HOÀN THÀNH 10 CÂU HỎI! Độ trễ trung bình (Avg Latency): {avg_lat:.2f} ms")
print("======================================================================")
