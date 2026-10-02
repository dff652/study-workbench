# 组件与字体来源

核对日期：2026-10-03（Asia/Shanghai）。版本及许可来自 `.venv` 已安装发行包元数据／许可文件及字体包版权文件；运行依赖固定在 [requirements.txt](../requirements.txt)。这份记录说明 A2 及 B1 验证使用的组件，不替代后续发布镜像的完整第三方清单。

| 组件 | 当前版本 | 许可／用途 | 上游依据 |
| --- | --- | --- | --- |
| ReportLab | 5.0.1 | BSD；PDF、向量公式及地图 | [官方 FAQ](https://docs.reportlab.com/developerfaqs/)／发行包 license.txt |
| python-docx | 1.2.0 | MIT；Word 与 OMML 载体 | [官方文档](https://python-docx.readthedocs.io/en/latest/)／发行包许可 |
| fontTools | 4.66.1 | MIT；字体子集、CFF 转二次曲线及字符覆盖检查 | [官方 subset 文档](https://fonttools.readthedocs.io/en/latest/subset/)／发行包许可 |
| lxml | 6.1.3 | BSD-3-Clause；Word XML 及验收解析 | 已安装发行包 License-Expression／许可 |
| Pillow | 12.3.0 | MIT-CMU；已有图像依赖，解码公式 PNG 与本地预览 | 已安装发行包 License-Expression／许可 |
| charset-normalizer | 3.5.2 | MIT；ReportLab 依赖 | 已安装发行包 License-Expression／许可 |

A1b 的 Django、psycopg 及既有依赖继续按原固定版本使用，本轮没有改变数据库或服务器选型。PyMuPDF 不进入新项目渲染依赖；地图 PNG 及预览由本机已有 Poppler 工具生成。

## B1 开发验证依赖

以下仅固定在 [requirements-dev.txt](../requirements-dev.txt)，没有增加运行依赖或发布浏览器镜像：

| 组件 | 已安装版本 | 许可／用途 |
| --- | --- | --- |
| Playwright | 1.58.0 | Apache-2.0；手机宽度浏览器验收 |
| pyee | 13.0.1 | MIT；Playwright 事件依赖 |
| greenlet | 3.5.6 | MIT AND PSF-2.0；Playwright 同步接口依赖 |

许可名称来自本机发行包 `License-Expression` 或 `License` 字段。Chromium 145.0.7632.6／Playwright build 1208 仅下载到临时缓存，未修改系统浏览器，也未放入源码或服务交付；后续若分发浏览器，须另记录其发行清单与声明。

## 字体

| 实际来源 | 本轮处理与许可留存 |
| --- | --- |
| `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`、`NotoSansCJK-Bold.ttc`；本机 fonts-noto-cjk `1:20230817+repack1-3` | 选择 face 2，核对字体族为 Noto Sans CJK SC；按真实内容取子集，CFF 转 glyf 并改名为 Study Workbench Sans SC；SIL OFL 1.1 的版权／许可原文保留于 [Noto-OFL.txt](../licenses/Noto-OFL.txt)，随私有字体包保存 |
| `/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf`；fonts-dejavu-core `2.37-8` | 字节原样复制；Bitstream Vera／DejaVu 相关声明及本机完整版权说明保留于 [DejaVu-fonts.txt](../licenses/DejaVu-fonts.txt)；[上游许可](https://github.com/dejavu-fonts/dejavu-fonts/blob/master/LICENSE) |

字体输入、输出及许可文件 SHA 保存在 packet.json 的字体配置中；未修改系统文件，没有将字体二进制提交源码。许可文件来自已有系统包，本轮没有下载第三方字体。Word 使用 Noto Sans CJK SC 字体族声明，完整字体并未嵌入 Word。

本机 Poppler 为 `24.02.0-1ubuntu9.9`，仅调用已有工具；没有把工具或系统包复制进项目。后续 D1 若分发镜像，需记录实际软件包和许可证、保留要求的声明，并确认字体／工具构建方式。候选应用的代码和图片均未复制，Smart Wrong Notebook 的授权未证实状态仍保留。


## 容器与 Word 重排环境

运行镜像另外固定 [Gunicorn 26.2.0](https://pypi.org/project/gunicorn/26.2.0/) 与 [WhiteNoise 6.12.0](https://pypi.org/project/whitenoise/6.12.0/)，两者发行元数据均为 MIT；安装包自带许可文件留在镜像 dist-info。容器 Debian Noto `1:20220127+repack1-1`／DejaVu `2.37-6` 与上列宿主包修订不同，构建时另复制实际包版权文件到 `/app/licenses/*-Debian-container.txt`，导出快照记录实际字体哈希。Python 基础镜像和 PostgreSQL 镜像固定 digest，完整实际包清单可由容器内 `dpkg-query -W`／`pip freeze` 复核；未发布镜像。

可选 [Word 验收镜像](../Dockerfile.word-verifier) 固定 LibreOffice Writer＋[Math `4:7.4.7-1+deb12u14`](https://packages.debian.org/bookworm/libreoffice-math)、同版 Debian 字体及其系统版权文件，仅在网络关闭的验收容器中运行。没有向宿主机安装 LibreOffice，也不将其纳入 Web 服务镜像。它的包及传递依赖许可保留于镜像 `/usr/share/doc/*/copyright`，不把 LibreOffice 的结果等同于 Microsoft Word 兼容性。
