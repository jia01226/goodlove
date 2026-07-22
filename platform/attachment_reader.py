"""把聊天附件转换成模型能读的文字。

图片由 chat_ai 作为视觉输入发送；这里负责常见文本、PDF 与 Office 文档。
解析失败必须明确返回原因，不能只告诉模型“有个文件”后让它假装看过。
"""
import html
import os
import re
import zipfile
from xml.etree import ElementTree as ET

from constants import DOC_EXT, MODEL_FILE_TEXT_MAX, TEXT_EXT, UPLOAD_DIR


def _safe_path(rel):
    name = os.path.basename((rel or "").split("?")[0])
    path = os.path.join(UPLOAD_DIR, name)
    return (path, name) if name and os.path.isfile(path) else ("", name)


def _clip(text):
    text = re.sub(r"\x00+", "", text or "").strip()
    if len(text) <= MODEL_FILE_TEXT_MAX:
        return text, False
    return text[:MODEL_FILE_TEXT_MAX].rstrip() + "\n\n（文件较长，以上为前段内容）", True


def _decode_text(path):
    with open(path, "rb") as handle:
        raw = handle.read(min(os.path.getsize(path), 4 * 1024 * 1024))
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _tag(element):
    return element.tag.rsplit("}", 1)[-1]


def _docx_text(path):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    lines = []
    for paragraph in (node for node in root.iter() if _tag(node) == "p"):
        text = "".join((node.text or "") for node in paragraph.iter() if _tag(node) == "t")
        if text.strip():
            lines.append(text.strip())
    return "\n".join(lines)


def _xlsx_text(path):
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in (node for node in root.iter() if _tag(node) == "si"):
                shared.append("".join((n.text or "") for n in item.iter() if _tag(n) == "t"))
        sheets = sorted(
            (name for name in archive.namelist()
             if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)),
            key=lambda name: int(re.search(r"(\d+)", name.rsplit("/", 1)[-1]).group(1)),
        )
        output = []
        for index, name in enumerate(sheets, 1):
            root = ET.fromstring(archive.read(name))
            rows = []
            for row in (node for node in root.iter() if _tag(node) == "row"):
                values = []
                for cell in (node for node in row if _tag(node) == "c"):
                    kind = cell.attrib.get("t", "")
                    raw = next(((n.text or "") for n in cell.iter() if _tag(n) == "v"), "")
                    if kind == "s" and raw.isdigit() and int(raw) < len(shared):
                        raw = shared[int(raw)]
                    elif kind == "inlineStr":
                        raw = "".join((n.text or "") for n in cell.iter() if _tag(n) == "t")
                    values.append(raw)
                if any(value for value in values):
                    rows.append("\t".join(values))
            if rows:
                output.append(f"【工作表 {index}】\n" + "\n".join(rows))
        return "\n\n".join(output)


def _pptx_text(path):
    with zipfile.ZipFile(path) as archive:
        slides = sorted(
            (name for name in archive.namelist()
             if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=lambda name: int(re.search(r"(\d+)", name.rsplit("/", 1)[-1]).group(1)),
        )
        output = []
        for index, name in enumerate(slides, 1):
            root = ET.fromstring(archive.read(name))
            bits = [(node.text or "").strip() for node in root.iter() if _tag(node) == "t"]
            bits = [bit for bit in bits if bit]
            if bits:
                output.append(f"【第 {index} 页】\n" + "\n".join(bits))
        return "\n\n".join(output)


def _pdf_text(path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("服务器尚未安装 PDF 阅读组件") from exc
    reader = PdfReader(path)
    pages = []
    for index, page in enumerate(reader.pages[:80], 1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(f"【第 {index} 页】\n{text}")
        if sum(len(item) for item in pages) >= MODEL_FILE_TEXT_MAX:
            break
    return "\n\n".join(pages)


def extract_text(rel, original_name=""):
    """返回 {ok,text,name,error,truncated}；不支持或读取失败时 ok=False。"""
    path, stored_name = _safe_path(rel)
    display_name = os.path.basename(original_name or stored_name or "附件")
    ext = os.path.splitext(display_name)[1].lower() or os.path.splitext(stored_name)[1].lower()
    if not path:
        return {"ok": False, "text": "", "name": display_name, "error": "文件已经不存在", "truncated": False}
    try:
        if ext in TEXT_EXT:
            text = _decode_text(path)
        elif ext == ".docx":
            text = _docx_text(path)
        elif ext == ".xlsx":
            text = _xlsx_text(path)
        elif ext == ".pptx":
            text = _pptx_text(path)
        elif ext == ".pdf":
            text = _pdf_text(path)
        elif ext in DOC_EXT:
            text = ""
        else:
            return {"ok": False, "text": "", "name": display_name,
                    "error": "暂不支持读取这种文件格式", "truncated": False}
        text = html.unescape(text or "").strip()
        if not text:
            return {"ok": False, "text": "", "name": display_name,
                    "error": "没有提取到可读文字，可能是扫描件或空文件", "truncated": False}
        text, truncated = _clip(text)
        return {"ok": True, "text": text, "name": display_name, "error": "", "truncated": truncated}
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError, RuntimeError) as exc:
        return {"ok": False, "text": "", "name": display_name,
                "error": str(exc) or "文件解析失败", "truncated": False}
