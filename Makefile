PY := .venv/bin/python
CANGJIE := vendor/cangjie-skill/scripts/cangjie.py
SVG_LINT := vendor/svg-diagram/tools/svg-lint/bin/svg-lint.mjs

.PHONY: doctor gates-selftest e2e thinking-test bridge audit compile thinking-audit candidate eval-report publish lint-svg new-book clean

doctor: gates-selftest
	@$(PY) $(CANGJIE) doctor
	@echo "—— svg-diagram（图件闸依赖）——"
	@if command -v node >/dev/null 2>&1; then \
		node --version; \
		node $(SVG_LINT) vendor/svg-diagram/gallery/01-architecture-skill-loading.svg; \
	else echo "▲ node 缺失：图件闸 svg-lint 判不适用（引用完整性检查不受影响）"; fi
	@echo "—— dsh 安装态 ——"
	@$(PY) tools/check_install_state.py || true
	@echo "—— html-css-to-image（可选出图，无密钥不调用）——"
	@$(PY) bridge/render_html_image.py --check

gates-selftest:
	@$(PY) tools/_bandid.py
	@$(PY) tools/check_pool_coverage.py --selftest
	@$(PY) tools/check_anchor_consistency.py --selftest
	@$(PY) tools/check_evidence_closure.py --selftest

e2e:
	@$(PY) tests/e2e_test.py
	@$(PY) -B tests/thinking_test.py
	@$(PY) -B tests/persona_test.py

thinking-test:
	@$(PY) -B tests/thinking_test.py
	@$(PY) -B tests/persona_test.py

bridge:
	@test -n "$(BOOK)" && test -n "$(SRC)" || (echo "用法: make bridge BOOK=books/<slug> SRC=<原文.txt|md|pdf> [TASK=<slug>]"; exit 2)
	@$(PY) bridge/cangjie_to_dsh.py --book-dir "$(BOOK)" --source "$(SRC)" --ws "$(CURDIR)" $(if $(TASK),--task "$(TASK)")

audit:
	@test -n "$(TASK)" || (echo "用法: make audit TASK=<slug>"; exit 2)
	@$(PY) bridge/run_audit.py --task "$(TASK)" --ws "$(CURDIR)"

compile:
	@test -n "$(BOOK)" && test -n "$(OUT)" || (echo "用法: make compile BOOK=books/<slug> OUT=<安装目标>  # 仅判态全绿后使用"; exit 2)
	@$(PY) bridge/build_book_skill.py procedures --book-dir "$(BOOK)" --ws "$(CURDIR)" --out "$(OUT)" --output "$(if $(OUTPUT),$(OUTPUT),auto)" $(if $(TASK),--task "$(TASK)") $(if $(SRC),--source "$(SRC)")

thinking-audit:
	@test -n "$(BOOK)" && test -n "$(SRC)" || (echo "用法: make thinking-audit BOOK=books/<slug> SRC=<原文> [REVIEW=<独立评审.json>]"; exit 2)
	@$(PY) bridge/thinking_audit.py --book-dir "$(BOOK)" --source "$(SRC)" --ws "$(CURDIR)" $(if $(REVIEW),--review "$(REVIEW)")

candidate:
	@test -n "$(BOOK)" && test -n "$(SRC)" || (echo "用法: make candidate BOOK=books/<slug> SRC=<原文> [REVIEW=<独立评审.json>]"; exit 2)
	@$(PY) bridge/build_book_skill.py candidate --book-dir "$(BOOK)" --source "$(SRC)" --ws "$(CURDIR)" $(if $(REVIEW),--review "$(REVIEW)") $(if $(TASK),--task "$(TASK)")

eval-report:
	@test -n "$(RUN)" || (echo "用法: make eval-report RUN=<评测目录>"; exit 2)
	@$(PY) bridge/eval_book_skill.py report --run-dir "$(RUN)"

publish:
	@test -n "$(CANDIDATE)" && test -n "$(ACCEPTANCE)" && test -n "$(OUT)" || (echo "用法: make publish CANDIDATE=<候选> ACCEPTANCE=<验收记录> OUT=<安装目标>"; exit 2)
	@$(PY) bridge/build_book_skill.py publish --candidate "$(CANDIDATE)" --acceptance "$(ACCEPTANCE)" --out "$(OUT)"

lint-svg:
	@test -n "$(FILE)" || (echo "用法: make lint-svg FILE=<路径.svg>（可多文件）"; exit 2)
	@node $(SVG_LINT) $(FILE)

new-book:
	@test -n "$(BOOK)" || (echo "用法: make new-book BOOK=<slug> [TITLE=<书名>]"; exit 2)
	@mkdir -p books/$(BOOK)
	@if [ ! -f books/$(BOOK)/PIPELINE_STATE.md ]; then \
		printf '# PIPELINE_STATE\n\n当前阶段: 0（Adler 整书理解，未开始）\n已完成: （无）\n书名: $(TITLE)\n' \
			> books/$(BOOK)/PIPELINE_STATE.md; \
		echo "已建 books/$(BOOK)/（PIPELINE_STATE.md 就绪，阶段 0 待开始）"; \
	else echo "books/$(BOOK)/ 已存在，跳过（不覆盖断点续跑状态）"; fi

clean:
	rm -rf .work/demo-book .work/demo-tamper
