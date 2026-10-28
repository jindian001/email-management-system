PY := .venv/bin/python
PIP := uv pip install --python .venv/bin/python

.PHONY: help venv install migrate web test lint fmt demo serve train clean

help:
	@echo "make install  - 创建 venv 并安装依赖"
	@echo "make web      - 构建前端（React + Vite → src/mailmind/static）"
	@echo "make migrate  - 执行数据库迁移 (alembic upgrade head)"
	@echo "make test     - 运行全部测试"
	@echo "make lint     - ruff + mypy"
	@echo "make demo     - 生成演示数据（SQLite）"
	@echo "make serve    - 启动服务  http://127.0.0.1:8080/ui/"
	@echo "make train    - 用反馈数据重训模型"

venv:
	@test -d .venv || uv venv .venv

install: venv
	$(PIP) -e ".[dev]"

migrate:
	PYTHONPATH=src $(PY) -m alembic upgrade head

web:
	cd web && pnpm install && pnpm build

test:
	PYTHONPATH=src $(PY) -m pytest -q

lint:
	PYTHONPATH=src $(PY) -m ruff check src
	PYTHONPATH=src $(PY) -m mypy src

demo:
	PYTHONPATH=src $(PY) -m mailmind.cli demo

serve:
	PYTHONPATH=src $(PY) -m mailmind.cli serve --port 8080

train:
	PYTHONPATH=src $(PY) -m mailmind.cli train

clean:
	rm -rf var .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
