import test from 'node:test';
import assert from 'node:assert/strict';
import {Worker as NodeWorker} from 'node:worker_threads';
import {readBoundedJson} from '../../static/js/json_budget.js';
import {loadCard, saveCard} from '../../static/js/phantom/card_storage.js';
import {STORAGE_KEY} from '../../static/js/phantom/state.js';

let terminated = 0;
class BrowserWorker {
  constructor(url) {
    assert.match(String(url), /json_worker\.js$/);
    this.worker = new NodeWorker(new URL('./worker_harness.mjs', import.meta.url));
    this.worker.on('message', data => this.onmessage?.({data}));
    this.worker.on('error', error => this.onerror?.(error));
  }
  postMessage(data) { this.worker.postMessage(data); }
  terminate() { terminated++; this.worker.terminate(); }
}
globalThis.Worker = BrowserWorker;

test('actual worker parses text and Blob, terminates after success and failure', async () => {
  assert.deepEqual(await readBoundedJson('{"Id":"Level"}'), {Id:'Level'});
  assert.deepEqual(await readBoundedJson(new Blob(['{"value":1}'])), {value:1});
  await assert.rejects(readBoundedJson('{bad json}'));
  assert.equal(terminated,3);
});
test('invalid stored draft recovers before mounting and is cleared', async () => {
  const values = new Map([[STORAGE_KEY, '['.repeat(33)+'1'+']'.repeat(33)]]);
  let recovered = false;
  globalThis.localStorage = {getItem:key=>values.get(key),removeItem:key=>values.delete(key),setItem:(key,val)=>values.set(key,val)};
  globalThis.document = {getElementById:()=>({removeAttribute(){recovered=true;}})};
  const warn = console.warn; console.warn = ()=>{};
  try {
    const card = await loadCard();
    assert.ok(card.localId);
    assert.equal(values.has(STORAGE_KEY),false);
    assert.equal(recovered,true);
    assert.throws(()=>saveCard({name:'a'.repeat(4097)}));
    assert.equal(values.has(STORAGE_KEY),false);
  } finally { console.warn=warn; }
});
