# Runtime memory

长期记忆的权威数据保存在运行状态 `state.json` 的 `memory` 分区。本目录
只保存架构说明，不保存任何生产用户历史。运行时上下文读取长期摘要、稳定
偏好、共同经历、未完成事项和少量 recent history，不读取完整 history.jsonl。
