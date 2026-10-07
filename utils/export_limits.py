"""在线文本导出的工作预算：边处理边计数，不做一次额外的全包预检。"""

import io
import json
from .patch_limits import ClientFacingError

MIB = 1024 * 1024
MAX_OBJECTS = 10_000
MAX_BUNDLE_FILES = 256
MAX_BUNDLE_DEPTH = 16
NAME_MAX_CHARS = 512
EXPORT_MAX_FILES = 5000
TEXT_MAX_BYTES = 16 * MIB
TEXT_TOTAL_BYTES = 64 * MIB
JSON5_MAX_BYTES = 256 * 1024  # 导出解析预算独立于回填文本容量。
RAW_MAX_BYTES = 16 * MIB
RAW_TOTAL_BYTES = 64 * MIB
TREE_MAX_DEPTH = 32
TREE_MAX_NODES = 500_000
TREE_TOTAL_NODES = 2_000_000
TREE_MAX_STRING_CHARS = 2 * MIB
# card_data_5 的 TextAsset 正文约 3 MiB；展开前单独按 UTF-8 字节限制。
EMBEDDED_JSON_MAX_BYTES = 8 * MIB
EXPORT_TOTAL_BYTES = 64 * MIB
TEMP_MAX_BYTES = 384 * MIB
ZIP_MAX_BYTES = 32 * MIB


def exceeded(message):
    return ClientFacingError(f"{message}，超过在线工具处理范围，请使用本地工具。", 413)


def check_name(name):
    if not isinstance(name, str) or len(name) > NAME_MAX_CHARS:
        raise exceeded(f"对象名称或字符串长度超过 {NAME_MAX_CHARS} 字符")
    return name


def iter_objects(env):
    # Environment.objects 会先递归构造完整列表；直接走已加载的文件目录。
    files = getattr(env, "files", None)
    if not isinstance(files, dict):  # 小型 mock / 已有对象列表。
        source = iter(env.objects)
        for count, obj in enumerate(source, 1):
            if count > MAX_OBJECTS:
                raise exceeded(f"Bundle 对象数量超过 {MAX_OBJECTS} 个")
            yield obj
        return
    stack = [(iter(files.values()), 1)]
    count = file_count = 0
    while stack:
        entries, depth = stack[-1]
        try:
            item = next(entries)
        except StopIteration:
            stack.pop()
            continue
        file_count += 1
        if file_count > MAX_BUNDLE_FILES or depth > MAX_BUNDLE_DEPTH:
            raise exceeded("Bundle 文件结构过于复杂")
        objects = getattr(item, "objects", None)
        if isinstance(objects, dict) and not getattr(item, "is_dependency", False):
            if count + len(objects) > MAX_OBJECTS:
                raise exceeded(f"Bundle 对象数量超过 {MAX_OBJECTS} 个")
            count += len(objects)
            yield from objects.values()
        elif isinstance(getattr(item, "files", None), dict):
            stack.append((iter(item.files.values()), depth + 1))


class ExportBudget:
    def __init__(self):
        self.files = self.text_bytes = self.raw_bytes = self.payload_bytes = 0
        self.tree_nodes = 0
        self.disk_sizes = {}

    def reserve_source(self, obj):
        self.reserve_binary(obj.byte_size)


    def reserve_binary(self, size):
        if size < 0 or size > RAW_MAX_BYTES:
            raise exceeded(f"单对象二进制数据超过 {RAW_MAX_BYTES // MIB} MiB")
        if self.raw_bytes + size > RAW_TOTAL_BYTES:
            raise exceeded(f"累计读取二进制数据超过 {RAW_TOTAL_BYTES // MIB} MiB")
        self.raw_bytes += size

    def start_file(self):
        if self.files >= EXPORT_MAX_FILES:
            raise exceeded(f"导出文件数量超过 {EXPORT_MAX_FILES} 个")
        self.files += 1

    def add_payload(self, size, member_size):
        cap = TEXT_MAX_BYTES
        if member_size + size > cap:
            raise exceeded(f"单个文本导出内容超过 {cap // MIB} MiB")
        if self.payload_bytes + size > EXPORT_TOTAL_BYTES:
            raise exceeded(f"导出内容累计超过 {EXPORT_TOTAL_BYTES // MIB} MiB")
        if self.text_bytes + size > TEXT_TOTAL_BYTES:
            raise exceeded(f"文本导出内容累计超过 {TEXT_TOTAL_BYTES // MIB} MiB")
        self.payload_bytes += size
        self.text_bytes += size


    def set_disk_size(self, key, size):
        total = sum(self.disk_sizes.values()) - self.disk_sizes.get(key, 0) + size
        if total > TEMP_MAX_BYTES:
            raise exceeded(f"临时文件磁盘使用超过 {TEMP_MAX_BYTES // MIB} MiB")
        self.disk_sizes[key] = size


class BoundedOutput:
    """ZIP 实际文件写入前检查上限，支持 zipfile 回写头部的 seek。"""
    def __init__(self, file, budget, key, cap, label):
        self.file, self.budget, self.key = file, budget, key
        self.cap, self.label, self.size = cap, label, 0

    def write(self, data):
        size = max(self.size, self.file.tell() + len(data))
        if size > self.cap:
            raise exceeded(f"{self.label}超过 {self.cap // MIB} MiB")
        self.budget.set_disk_size(self.key, size)
        self.size = size
        return self.file.write(data)

    def __getattr__(self, name):
        return getattr(self.file, name)

    def fileno(self):
        # 所有输出必须通过 write() 检查，不能绕过预算直接写文件描述符。
        raise io.UnsupportedOperation("受限输出不提供文件描述符")


class MemberWriter:
    def __init__(self, file, budget):
        self.file, self.budget, self.size = file, budget, 0

    def write(self, text):
        data = text.encode("utf-8")
        self.budget.add_payload(len(data), self.size)
        self.size += len(data)
        self.file.write(data)
        return len(text)


def json_chunks(value, **kwargs):
    return json.JSONEncoder(ensure_ascii=False, **kwargs).iterencode(value)


def write_json_member(zf, name, value, budget):
    budget.start_file()
    with zf.open(name, "w") as file:
        writer = MemberWriter(file, budget)
        for chunk in json_chunks(value, indent=4):
            writer.write(chunk)
