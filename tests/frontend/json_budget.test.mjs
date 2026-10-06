import test from 'node:test';
import assert from 'node:assert/strict';
import {parseBoundedJson, validateJson, readBoundedJson, JSON_LIMITS} from '../../static/js/json_budget.js';

test('normal Unicode JSON, escaped quotes and brackets remain valid', () => {
  const value = {name:'植物', x:'\\"[]{}', items:[1,true,null]};
  assert.deepEqual(parseBoundedJson(JSON.stringify(value)), value);
});
test('byte and lexical depth caps reject before parsing', () => {
  assert.throws(() => parseBoundedJson(' '.repeat(JSON_LIMITS.bytes + 1)), /256/);
  assert.throws(() => parseBoundedJson('['.repeat(33) + '1' + ']'.repeat(33)), /32/);
  assert.throws(() => parseBoundedJson(JSON.stringify('植'.repeat(90000))), /256/);
});
test('width, nodes, string length and unsafe object fields are bounded', () => {
  assert.throws(() => validateJson(new Array(2049).fill(1)), /2048/);
  assert.throws(() => validateJson('a'.repeat(4097)), /4096/);
  assert.throws(() => parseBoundedJson('{"__proto__":{}}'), /不安全/);
  assert.throws(() => validateJson(Object.fromEntries(Array.from({length:10001}, (_,i)=>[String(i),1]))), /复杂/);
});
test('oversized File is rejected without creating a worker or reading it', async () => {
  let read = false;
  await assert.rejects(readBoundedJson({size:JSON_LIMITS.bytes+1,text(){read=true;}}), /256/);
  assert.equal(read, false);
});
