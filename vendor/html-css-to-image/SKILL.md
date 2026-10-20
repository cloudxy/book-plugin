---
name: html-css-to-image
description: 可选地把一份本地 HTML/CSS 渲成栅格图。仅当操作者明确要求出 PNG/JPEG，且环境里已经有 HCTI_API_ID 与 HCTI_API_KEY 时使用。不用于书稿、引文、审计池，不抓取网页，也不替代 svg-diagram 的图件闸。
metadata:
  html-css-to-image.version: "0.3.0"
  html-css-to-image.license: MIT
  html-css-to-image.install: vendor/html-css-to-image/dist/html_css_to_image-0.3.0-py3-none-any.whl
---

# html-css-to-image — 可选栅格出图

上游是 HTML/CSS to Image 的官方 Python 客户端 0.3.0（MIT）。本目录的 `src/`、`tests/`、`LICENSE`、`README.md`、`pyproject.toml` 与 `dist/` 里的 wheel 是该版本的快照，不改其源码。本文件只说明 book-workflow 怎么调用它。

## 它做什么

`HtmlCssToImageClient.from_env()` 读取 `HCTI_API_ID` 与 `HCTI_API_KEY`。缺任一变量时上游自己抛出 `ValueError`。真正出图是 `POST https://hcti.io/v1/image`，会把你交给它的 HTML/CSS 发到该服务。

book-workflow 只暴露本地 HTML/CSS 这一条：

```bash
$WS/.venv/bin/python $PLUGIN/bridge/render_html_image.py \
  --html /path/to/card.html --css /path/to/card.css \
  --out /Users/xuyun/Documents/grok-files/card.png --ws $WS
```

脚本在密钥齐全时调用 `CreateHtmlCssImageRequest`，把返回的图片存到 `--out`，并再复制一份到 `/Users/xuyun/Documents/grok-files/`。不提供 URL 截图、模板拉取或删除接口。

## 什么时候不要用

- 没有明确的出图请求。
- 环境里没有 `HCTI_API_ID` 或 `HCTI_API_KEY`。此时 `--check` 仍应成功，并说明远程出图跳过；不要写死密钥，也不要为了体检去申请密钥。
- 输入落在 `books/` 或 `.work/`。书稿、引文、审计池留在本地。
- 想替代房规 SVG。图件闸只认书树里的 SVG 与 svg-lint。本客户端的栅格图不进四闸，也不作为能力卡的 `resources:`。

## 体检

```bash
$WS/.venv/bin/python $PLUGIN/bridge/render_html_image.py --check
```

`--check` 只确认已安装的客户端版本是 0.3.0，并报告两个环境变量是否都有值。它不打印密钥，不发起 HTTP 请求。
