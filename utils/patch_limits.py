"""在线回填的资源预算；不做补丁内容预检或全 ZIP 解压。"""

from contextlib import contextmanager
import io
import json
import struct
import warnings
import zipfile

import json5
from PIL import Image

MIB = 1024 * 1024
ZIP_MAX_ENTRIES = 2048
ZIP_MAX_NAME_CHARS = 512
ZIP_MAX_DIRECTORY_BYTES = 4 * MIB
ZIP_MAX_MEMBER_BYTES = 32 * MIB
ZIP_MAX_DECLARED_BYTES = 128 * MIB
ZIP_MAX_READ_BYTES = 64 * MIB
ZIP_MAX_COMPRESSION_RATIO = 200
READ_CHUNK_BYTES = 64 * 1024
INDEX_MAX_BYTES = MIB
JSON_MAX_BYTES = 4 * MIB
JSON5_MAX_BYTES = 256 * 1024
CSV_MAX_BYTES = 4 * MIB
CSV_MAX_ROWS = 20000
CSV_MAX_COLUMNS = 32
CSV_MAX_FIELD_CHARS = 128 * 1024
JSON_MAX_DEPTH = 64
JSON_MAX_NODES = 100000
PNG_MAX_BYTES = 16 * MIB
IMAGE_MAX_SIDE = 4096
IMAGE_MAX_PIXELS = 4 * 1024 * 1024
IMAGE_MAX_TOTAL_PIXELS = 8 * 1024 * 1024


class ClientFacingError(Exception):
    """输入错误返回 400，资源预算超限返回 413。"""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = int(status)


def limit_error(message):
    return ClientFacingError(f"{message}。请只保留修改过的补丁，或使用本地工具处理。", 413)


def member_limit(name):
    name = name.replace("\\", "/").split("/")[-1].lower()
    if name == "_index.json":
        return INDEX_MAX_BYTES
    if name.endswith((".json", ".json5")):
        return JSON_MAX_BYTES
    if name.endswith(".csv"):
        return CSV_MAX_BYTES
    if name.endswith(".png"):
        return PNG_MAX_BYTES
    return ZIP_MAX_MEMBER_BYTES


@contextmanager
def open_patch_zip(path):
    # 先读至多 65557 字节的目录尾记录，避免 ZipFile 为海量条目分配元数据。
    # 在线上限不需要 ZIP64 目录或分卷包；本站正常导出不会触发 ZIP64 目录。
    with open(path, "rb") as fp:
        fp.seek(0, io.SEEK_END)
        size = fp.tell()
        fp.seek(max(0, size - 65557))
        tail = fp.read(65557)
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0 or len(tail) - pos < 22:
        raise zipfile.BadZipFile("缺少 ZIP 目录尾记录")
    _, disk, directory_disk, disk_entries, entries, directory_bytes, offset, comment = struct.unpack_from(
        "<4s4H2LH", tail, pos,
    )
    if pos + 22 + comment != len(tail):
        raise zipfile.BadZipFile("ZIP 目录尾记录损坏")
    if disk or directory_disk or disk_entries != entries:
        raise ClientFacingError("不支持分卷 ZIP，请重新打包为普通 ZIP。")
    if (entries == 65535 or directory_bytes == 0xFFFFFFFF or offset == 0xFFFFFFFF
            or (pos >= 20 and tail[pos - 20:pos - 16] == b"PK\x06\x07")):
        raise ClientFacingError("在线回填不支持 ZIP64，请缩小补丁并重新打包为普通 ZIP。")
    if entries > ZIP_MAX_ENTRIES:
        raise limit_error(f"ZIP 条目数量超过 {ZIP_MAX_ENTRIES} 个")
    if directory_bytes > ZIP_MAX_DIRECTORY_BYTES:
        raise limit_error(f"ZIP 目录元数据超过 {ZIP_MAX_DIRECTORY_BYTES // MIB} MiB")
    with zipfile.ZipFile(path, "r") as zf:
        yield BoundedZipReader(zf)


class BoundedZipReader:
    """先检查所有成员元数据；仅在业务需要时受限读取，并累计实际字节。"""

    def __init__(self, zf):
        self.zf = zf
        self.total_read = 0
        self.members = zf.infolist()
        if len(self.members) > ZIP_MAX_ENTRIES:
            raise limit_error(f"ZIP 条目数量超过 {ZIP_MAX_ENTRIES} 个")
        total = 0
        for info in self.members:
            if len(info.filename) > ZIP_MAX_NAME_CHARS:
                raise limit_error(f"ZIP 文件名超过 {ZIP_MAX_NAME_CHARS} 个字符")
            if info.file_size > min(ZIP_MAX_MEMBER_BYTES, member_limit(info.filename)):
                raise limit_error(f"ZIP 成员 [{info.filename}] 声明解压大小超过该格式上限")
            total += info.file_size
            if total > ZIP_MAX_DECLARED_BYTES:
                raise limit_error(f"ZIP 累计声明解压大小超过 {ZIP_MAX_DECLARED_BYTES // MIB} MiB")
            if info.file_size > ZIP_MAX_COMPRESSION_RATIO * info.compress_size:
                raise limit_error(f"ZIP 成员 [{info.filename}] 压缩比超过 {ZIP_MAX_COMPRESSION_RATIO}:1")
            if info.flag_bits & 1:
                raise ClientFacingError("不支持加密 ZIP，请去掉密码后重新打包。")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ClientFacingError("ZIP 请使用普通存储或 Deflate 压缩，暂不支持其他压缩算法。")

    def read(self, name):
        info = self.zf.getinfo(name)
        cap = min(ZIP_MAX_MEMBER_BYTES, member_limit(info.filename))
        if info.file_size > cap:
            raise limit_error(f"ZIP 成员 [{name}] 声明解压大小超过该格式上限")
        data = bytearray()
        with self.zf.open(info) as fp:
            while True:
                remaining = min(cap - len(data), ZIP_MAX_READ_BYTES - self.total_read)
                # 最多额外读 1 字节以区分恰好到达上限与真正超限。
                chunk = fp.read(min(READ_CHUNK_BYTES, remaining + 1))
                self.total_read += len(chunk)
                if len(data) + len(chunk) > cap:
                    raise limit_error(f"ZIP 成员 [{name}] 实际读取字节超过该格式上限")
                if self.total_read > ZIP_MAX_READ_BYTES:
                    raise limit_error(f"本次回填累计实际解压字节超过 {ZIP_MAX_READ_BYTES // MIB} MiB")
                if not chunk:
                    break
                data.extend(chunk)
        return bytes(data)


def check_json_text(text, label, *, max_bytes=None, max_depth=None, max_nodes=None):
    """解析前检查嵌套和结构标记；忽略字符串与 JSON5 注释中的括号。"""
    max_bytes = JSON_MAX_BYTES if max_bytes is None else max_bytes
    max_depth = JSON_MAX_DEPTH if max_depth is None else max_depth
    max_nodes = JSON_MAX_NODES if max_nodes is None else max_nodes
    if len(text.encode("utf-8")) > max_bytes:
        raise limit_error(f"{label} 文本超过 {max_bytes // MIB} MiB")
    depth = tokens = i = 0
    quote = None
    while i < len(text):
        char = text[i]
        if quote:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            tokens += 1
        elif text.startswith("//", i):
            end = text.find("\n", i + 2)
            i = len(text) if end < 0 else end
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
            continue
        elif char in "{[":
            depth += 1
            tokens += 1
            if depth > max_depth:
                raise limit_error(f"{label} 嵌套深度超过 {max_depth} 层")
        elif char in "}]":
            depth -= 1
        elif char in ",:":
            tokens += 1
        if tokens > 2 * max_nodes:
            raise limit_error(f"{label} 结构过于复杂")
        i += 1


def check_json_tree(tree, label):
    # 迭代遍历，不依靠 Python 递归栈；字典键也计入节点预算。
    stack = [(iter((tree,)), 0)]
    count = 0
    while stack:
        iterator, depth = stack[-1]
        try:
            node = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        count += 1
        if isinstance(node, dict):
            count += len(node)
        if count > JSON_MAX_NODES or depth > JSON_MAX_DEPTH:
            raise limit_error(f"{label} 超过 {JSON_MAX_NODES} 个节点或 {JSON_MAX_DEPTH} 层嵌套上限")
        if isinstance(node, (dict, list)):
            values = node.values() if isinstance(node, dict) else node
            stack.append((iter(values), depth + 1))


def load_patch_json(text, label):
    check_json_text(text, label)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # JSON5 是纯 Python 解析，预算更低；大文件请保存为标准 JSON。
        if len(text.encode("utf-8")) > JSON5_MAX_BYTES:
            raise limit_error(f"{label} 需要 JSON5 解析，但超过 {JSON5_MAX_BYTES // 1024} KiB；请保存为标准 JSON")
        try:
            parsed = json5.loads(text)
        except RecursionError as exc:
            raise limit_error(f"{label} JSON5 嵌套过于复杂") from exc
    check_json_tree(parsed, label)
    return parsed


def open_patch_image(raw, remaining_pixels=None):
    """PNG 文件已受字节预算限制；RGBA 解码前检查尺寸，不关闭 Pillow 保护。"""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                width, height = image.size
                if (width > IMAGE_MAX_SIDE or height > IMAGE_MAX_SIDE
                        or width * height > IMAGE_MAX_PIXELS):
                    raise limit_error(
                        f"图片尺寸超过单边 {IMAGE_MAX_SIDE} 或总计 {IMAGE_MAX_PIXELS} 像素上限"
                    )
                if remaining_pixels is not None and width * height > remaining_pixels:
                    raise limit_error(f"本次回填图片累计像素超过 {IMAGE_MAX_TOTAL_PIXELS} 上限")
                if image.format != "PNG":
                    raise ClientFacingError("PNG 补丁内容不是标准 PNG 图片，请重新导出。")
                return image.convert("RGBA")
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise limit_error("图片触发 Pillow 解压安全限制") from exc
    except ClientFacingError:
        raise
    except (OSError, ValueError) as exc:
        raise ClientFacingError(f"无法读取 PNG 图片：{exc}。请确认文件完整。") from exc
