**在每一次完成一个模块的逻辑后就做一次 git commit 和 push 并在提交信息中表明这一次所做的修改**

## 执行细则（随工程演进补充，出现问题时同步更新本文件）

1. **提交粒度**：按模块提交，提交信息使用 `feat/fix/test/docs/chore: 说明` 前缀，说明本次改了什么、为什么。
2. **推送范围**：`src/`、`tests` 之外的工程文件、文档、配置需要 `git push` 到 `origin/main`。
3. **测试代码不推送**：`tests/` 只在本地存在（已加入 `.git/info/exclude`），可以本地 `commit` 不 `push`；为保证 `git add -A` 不会误提交，测试目录不进入版本库。
4. **提交前必须自检**：`python -m pytest` 全绿 + `python -c "import mailmind"` 无报错，否则不提交。
5. **出现问题先修文档**：实现中若发现 exp.md 的假设不成立（依赖不可用、方案成本过高、接口对不上），先更新 exp.md 的“附录 C 实现决策与偏差记录”，再改代码，最后提交。
6. **禁止提交**：`.venv/`、`var/`、`*.db`、`.env`、任何真实邮箱凭据。
7. **安全底线**：邮箱密码/token 不得明文入库；自动回复必须默认走人工审核（`MAILMIND_AUTO_REPLY_SEND_MODE=review`）。
8. **文档规范**：所有面向用户的命令块**不得包含 `#` 注释**（行内或整行）。macOS 默认 zsh 未开启 `interactive_comments`，粘贴后 `#` 及其后内容会被当成参数，报 `unrecognized arguments`。说明文字放在代码块外。
