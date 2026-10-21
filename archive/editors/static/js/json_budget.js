// Shared import limits; validation always precedes reactive state and persistence.
export const JSON_LIMITS = Object.freeze({bytes: 256 * 1024, depth: 32, nodes: 20000, array: 2048, string: 4096});
const encoder = new TextEncoder();
export function checkText(text) {
  if (typeof text !== 'string' || text.length > JSON_LIMITS.bytes || encoder.encode(text).length > JSON_LIMITS.bytes) {
    throw new Error('JSON 不能超过 256 KiB');
  }
  // Bound nesting BEFORE JSON.parse, including for existing stored drafts.
  let depth = 0, quoted = false, escaped = false;
  for (const ch of text) {
    if (quoted) {
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === '"') quoted = false;
    } else if (ch === '"') quoted = true;
    else if (ch === '{' || ch === '[') {
      if (++depth > JSON_LIMITS.depth) throw new Error('JSON 嵌套不能超过 32 层');
    } else if (ch === '}' || ch === ']') depth--;
  }
}
export function validateJson(value) {
  // Iterator frames stay bounded by depth, even for wide objects.
  const stack = [{it: [value][Symbol.iterator](), depth: 1}];
  let nodes = 0;
  while (stack.length) {
    const frame = stack[stack.length - 1], next = frame.it.next();
    if (next.done) { stack.pop(); continue; }
    const item = next.value;
    if (++nodes > JSON_LIMITS.nodes || frame.depth > JSON_LIMITS.depth) throw new Error('JSON 结构过于复杂');
    if (typeof item === 'string' && item.length > JSON_LIMITS.string) throw new Error('JSON 单个字符串不能超过 4096 字符');
    if (Array.isArray(item)) {
      if (item.length > JSON_LIMITS.array) throw new Error('JSON 数组不能超过 2048 项');
      stack.push({it: item[Symbol.iterator](), depth: frame.depth + 1});
    } else if (item && typeof item === 'object') {
      function* children() {
        for (const key of Object.keys(item)) {
          if (['__proto__', 'constructor', 'prototype'].includes(key)) throw new Error('JSON 包含不安全字段');
          yield key; yield item[key];
        }
      }
      stack.push({it: children(), depth: frame.depth + 1});
    } else if (typeof item === 'number' && !Number.isFinite(item)) throw new Error('JSON 数值无效');
  }
  return value;
}
export function parseBoundedJson(text) {
  checkText(text);
  return validateJson(JSON.parse(text));
}
export function readBoundedJson(input) {
  // Check File.size BEFORE any read; reject text before posting/allocating a Worker.
  if (typeof input === 'string') checkText(input);
  else if (!input || input.size > JSON_LIMITS.bytes) return Promise.reject(new Error('JSON 文件不能超过 256 KiB'));
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('./json_worker.js', import.meta.url), {type: 'module'});
    let timer;
    const done = (error, value) => { clearTimeout(timer); worker.terminate(); error ? reject(error) : resolve(value); };
    timer = setTimeout(() => done(new Error('JSON 解析超时，请简化文件')), 3000);
    worker.onmessage = ({data}) => done(data.error ? new Error(data.error) : null, data.value);
    worker.onerror = () => done(new Error('JSON 解析失败'));
    worker.postMessage(input);
  });
}
