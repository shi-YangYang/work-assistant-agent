# 返工

- 历史停用账号清理事务先获取 `app.security.locks.company_lock`，再按原顺序锁 Company／Member 并重查条件，与 HTTP／worker 使用一致的锁顺序。增加受控并发用例验证等待及锁释放后重查，不重复已通过的 Web／浏览器流程。
- 还原 `tests/server/test_company.py` 中无关工作更新的状态码断言，不能允许 HTTP 响应为 `None`。
- 返工后由新的独立 Agent 验收；其余已通过范围沿用现有证据。
