# Work Log

---
Task ID: 1
Agent: main
Task: 存档预拆分优化 - 将44MB gamestate 按国家/物种拆分为独立小文件

Work Log:
- 分析了 gamestate 顶层结构：66个顶层块，country(244K行/67子块)、species_db(6K行/194子块)等
- 设计并实现了 save_splitter.py：
  - split_gamestate(): 扫描文本→构建行偏移表→提取子块到独立.txt文件→保存字符偏移到manifest
  - splice_into_gamestate(): O(1)字符偏移查找 + 3次字符串切片替换，并自动调整后续偏移
  - read/write_split_file(): 读写单个拆分文件
- 全面重写 server.py 集成拆分优化：
  - 上传时自动拆分(1.7s)，后续所有per-country操作基于~300KB拆分文件
  - _modify_and_splice(): 读拆分文件→修改→写回→splice到全文→更新parsed缓存，全程无44MB重解析
  - 实现 modify_flag_in_text_v2() 修复之前缺失的国旗修改功能
  - _get_country_parsed(): 优先从拆分文件解析(56ms)，带缓存
  - _cleanup_all(): 统一清理内存状态+磁盘拆分文件+临时sav
- 端到端测试通过，性能提升显著：
  - GET resources: 67ms (首次) → 2ms (缓存后)，之前需要10s全量解析
  - PUT resources: 259ms (含56ms重解析单国文件)，之前需要10s全量重解析
  - 资源修改后立即可读，无stale cache问题
  - 导出文件正确包含所有修改

Stage Summary:
- 新增 save_splitter.py (265行)
- 重写 server.py (1157行)
- 更新 save-api.ts 添加 split_info 类型
- 拆分文件命名格式: `country_0.txt`, `species_db_1.txt`
- 工作目录: `/tmp/<sav_temp_dir>/stellaris_split_<sav_name>/`
- 性能: 单国操作 2-67ms vs 之前 10000ms+