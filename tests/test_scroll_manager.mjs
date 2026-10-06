import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/main.py', import.meta.url), 'utf8');
const installer = source.match(/SCROLL_POSITION_MANAGER_INSTALLER = r"""([\s\S]*?)"""/)[1];

function setup({width = 1366, contentHeight = 400, top = 0} = {}) {
  const element = (parentElement = null, values = {}) => ({
    parentElement, scrollTop: 0, scrollLeft: 0, clientHeight: 400,
    scrollHeight: 400, overflowY: 'hidden',
    addEventListener() {}, removeEventListener() {},
    scrollBy({top}) { this.scrollTop += top; },
    scrollTo({top}) { this.scrollTop = top; },
    closest(selector) {
      if (selector === this.selector) return this;
      return this.parentElement?.closest(selector) ?? null;
    },
    ...values,
  });
  const main = element(null, {scrollTop: 300, scrollHeight: 2000});
  const sidebar = element(null, {selector: '[data-testid="stSidebar"]'});
  const history = element(sidebar, {overflowY: 'auto', scrollHeight: contentHeight, scrollTop: top});
  const message = element(history);
  const composer = element(sidebar);
  const rail = element(null, {selector: '.citrus-primary-rail'});
  const listeners = new Map();
  const document = {
    documentElement: {}, querySelector: () => main,
    addEventListener(type, callback) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(callback);
    },
    removeEventListener(type, callback) { listeners.get(type)?.delete(callback); },
  };
  const window = {
    document, innerWidth: width,
    getComputedStyle: node => ({overflowY: node.overflowY, getPropertyValue: () => '217'}),
    sessionStorage: {getItem: () => null, setItem() {}},
    requestAnimationFrame: callback => callback(),
    setTimeout, clearTimeout,
  };
  vm.runInNewContext(installer, {window});
  window.__citrusAgentInstallScrollManager();
  const wheel = (target, deltaY, options = {}) => {
    const event = {
      target, deltaY, deltaX: 0, clientX: 1200, ctrlKey: false,
      defaultPrevented: false, isTrusted: true,
      preventDefault() { this.defaultPrevented = true; }, ...options,
    };
    for (const listener of listeners.get('wheel')) listener(event);
    return event;
  };
  return {main, sidebar, history, message, composer, rail, wheel, window};
}

test('empty chat and chat boundaries never scroll the workspace', () => {
  for (const width of [1366, 768]) {
    for (const [contentHeight, top, delta] of [[400, 0, 120], [400, 0, -120], [1000, 600, 120], [1000, 0, -120]]) {
      const app = setup({width, contentHeight, top});
      assert.equal(app.wheel(app.message, delta).defaultPrevented, true);
      assert.equal(app.main.scrollTop, 300);
    }
  }
});

test('scrollable messages keep native scrolling in either direction', () => {
  const app = setup({contentHeight: 1000, top: 200});
  for (const delta of [-120, 120]) {
    assert.equal(app.wheel(app.message, delta).defaultPrevented, false);
    assert.equal(app.main.scrollTop, 300);
  }
});

test('chat header and composer never forward wheel events to the workspace', () => {
  const app = setup();
  for (const target of [app.sidebar, app.composer]) {
    assert.equal(app.wheel(target, 120).defaultPrevented, true);
    assert.equal(app.main.scrollTop, 300);
  }
});

test('workspace, desktop navigation and browser zoom retain their behavior', () => {
  const app = setup();
  assert.equal(app.wheel(app.main, 120, {clientX: 500}).defaultPrevented, false);
  assert.equal(app.main.scrollTop, 300);
  assert.equal(app.wheel(app.rail, 120, {clientX: 100}).defaultPrevented, true);
  assert.equal(app.main.scrollTop, 420);
  assert.equal(app.wheel(app.message, 120, {ctrlKey: true}).defaultPrevented, false);
  assert.equal(app.main.scrollTop, 420);
});

test('installing again does not duplicate wheel forwarding', () => {
  const app = setup();
  app.window.__citrusAgentInstallScrollManager();
  app.wheel(app.rail, 120, {clientX: 100});
  assert.equal(app.main.scrollTop, 420);
  app.wheel(app.message, 120);
  assert.equal(app.main.scrollTop, 420);
});
