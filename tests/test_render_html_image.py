# -*- coding: utf-8 -*-
"""render_html_image 只测守卫：路径拦禁、大小上限、无密钥拒绝。全程无网络。"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
import render_html_image as rhi  # noqa: E402


class RenderGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="book-render-test-")
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)
        (self.ws / "books").mkdir()
        (self.ws / ".work").mkdir()
        (self.ws / "books" / "private.md").write_text("私有书稿内容", encoding="utf-8")
        self.outside = self.ws / "outside.html"
        self.outside.write_text("<p>ok</p>", encoding="utf-8")

    def quiet(self, fn, *args, **kwargs):
        """守卫函数会向 stdout 打印拒因；收进 StringIO 保持测试输出干净。"""
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(*args, **kwargs)

    def test_banned_roots_are_books_and_work_only(self):
        self.assertTrue(rhi.banned(self.ws / "books" / "private.md", self.ws))
        self.assertTrue(rhi.banned(self.ws / ".work" / "task", self.ws))
        self.assertFalse(rhi.banned(self.outside, self.ws))
        self.assertFalse(rhi.banned(self.ws, self.ws))                      # 只拦两棵子树，不拦工作区根
        self.assertFalse(rhi.banned(self.ws / "not-exist.md", self.ws))     # 不存在=不在根下

    def test_read_text_refuses_missing_banned_and_oversize(self):
        self.assertIsNone(self.quiet(rhi.read_text, self.ws / "missing.html", self.ws, "HTML"))
        self.assertIsNone(self.quiet(rhi.read_text, self.ws / "books" / "private.md", self.ws, "HTML"))
        big = self.ws / "big.html"
        big.write_text("<p>" + "x" * rhi.MAX_BYTES + "</p>", encoding="utf-8")
        self.assertIsNone(self.quiet(rhi.read_text, big, self.ws, "HTML"))
        edge = self.ws / "edge.html"
        edge.write_text("x" * rhi.MAX_BYTES, encoding="utf-8")
        self.assertEqual(len(self.quiet(rhi.read_text, edge, self.ws, "HTML")), rhi.MAX_BYTES)

    def test_render_without_keys_refuses_before_any_request(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("HCTI_")}
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "bridge" / "render_html_image.py"),
             "--html", str(self.outside), "--out", str(self.ws / "out.png"), "--ws", str(self.ws)],
            capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("未配置", result.stdout)
        self.assertFalse((self.ws / "out.png").exists())


if __name__ == "__main__":
    unittest.main()
