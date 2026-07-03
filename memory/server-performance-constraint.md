# Server performance constraint

- This server has limited CPU and about 1.6 GB RAM. All future automation and
  implementation work must consider resource usage before execution.
- Preserve a responsive user experience while bounding heavy work. Prefer
  on-demand services, bounded memory and targeted tests; lightweight API and
  web operations may remain concurrent.
- Avoid overlapping multiple memory-heavy Java/download/browser workloads when
  that risks exhausting the host. Use limited concurrency when it improves the
  workflow and measured headroom is sufficient.
- SoNovel must remain on demand, run only one market batch and one Java service
  at a time, and stop immediately after the batch completes or fails.
- 市场研究先走书海阁轻量精确搜索，未命中才调用 SoNovel 聚合搜索。外层
  并发按资源动态为 3/2/1：可用内存至少 850 MB 且负载低于 1.5 时为 3；
  至少 600 MB 且负载低于 2.5 时为 2；否则为 1。Java 虚拟线程载体限制为
  4/8，服务任务上限为 128；仍只运行一个 Java 服务和一个市场批次。
- 单批最多15本、目标6本：达到6本立即停止，不足6本尝试完整批；后台最长
  8分钟以覆盖资源降级时的15本尝试，但 GPT Action 每次轮询仍最多35秒。
  一批后不足3本时自动追加未尝试的官方榜单书，并带上先前成功书目复用缓存。
- Market study defaults to 6 effective samples; 3 is only the minimum gate.
  Additional batches are allowed when the evidence is conflicting or weak.
- Successful selected-chapter packets are reusable for 30 days. A daily 02:30
  timer clears failed temporary files and selected chapters unused for 90
  days, while preserving structural analysis and indexes.
