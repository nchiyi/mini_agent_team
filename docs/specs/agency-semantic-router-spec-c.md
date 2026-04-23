# Spec C: Semantic Router Spike (Final)

## 1. 範圍
- 語義匹配索引 (Indexing)
- 信心門檻與 Fallback 鏈
- 檔案導航約束

## 2. 實作要點
- **Spike 驗證**: 使用既有 `sentence-transformers` 進行匹配測試。
- **Fallback**: Semantic Match (Top-1) -> Heuristic Fast Path -> LLM Routing。
- **File Scan**: 限制在 `cwd` 深度 2 內，僅匹配關鍵檔案。

## 3. 完成標準
- 不阻塞 A/B 開發。
- 提供匹配率與延遲的 Benchmark 報告。