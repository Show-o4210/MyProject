import {parentPort} from 'node:worker_threads';
globalThis.self = {postMessage: value => parentPort.postMessage(value)};
await import('../../static/js/json_worker.js');
parentPort.on('message', data => self.onmessage({data}));
