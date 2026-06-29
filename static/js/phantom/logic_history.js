/** 技能树撤销 / 重做（PC LogicHistoryManager 简化版）。 */

import { parseNodeToSnapshot, restoreTreeFromSnapshot } from './logic_engine.js';

const MAX_STACK = 50;

export function createLogicHistory() {
  return {
    historyStack: [],
    redoStack: [],
    isRestoring: false
  };
}

export function snapshotFromRoots(roots = []) {
  return (roots || []).map(node => parseNodeToSnapshot(node));
}

export function saveHistorySnapshot(history, roots = []) {
  if (history.isRestoring) return;
  const snap = snapshotFromRoots(roots);
  const prev = history.historyStack[history.historyStack.length - 1];
  if (prev && JSON.stringify(prev) === JSON.stringify(snap)) return;
  history.historyStack.push(snap);
  if (history.historyStack.length > MAX_STACK) history.historyStack.shift();
  history.redoStack = [];
}

export function canUndo(history) {
  return history.historyStack.length > 1;
}

export function canRedo(history) {
  return history.redoStack.length > 0;
}

export function undoHistory(history) {
  if (!canUndo(history)) return null;
  history.isRestoring = true;
  history.redoStack.push(history.historyStack.pop());
  const restored = restoreTreeFromSnapshot(history.historyStack[history.historyStack.length - 1]);
  history.isRestoring = false;
  return restored;
}

export function redoHistory(history) {
  if (!canRedo(history)) return null;
  history.isRestoring = true;
  const snap = history.redoStack.pop();
  history.historyStack.push(snap);
  const restored = restoreTreeFromSnapshot(snap);
  history.isRestoring = false;
  return restored;
}

export function clearHistory(history) {
  history.historyStack = [];
  history.redoStack = [];
  history.isRestoring = false;
}