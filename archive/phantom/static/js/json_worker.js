import {parseBoundedJson} from './json_budget.js';
self.onmessage = async ({data}) => {
  try {
    const text = typeof data === 'string' ? data : await data.text();
    self.postMessage({value: parseBoundedJson(text)});
  } catch (error) {
    self.postMessage({error: error.message || 'JSON 格式错误'});
  }
};
