const port = process.argv[2] || "9224";

const cases = [
  {
    name: "single module",
    expression: '{ lib, ... }: { options.demo.enable = lib.mkEnableOption "demo"; }',
    expected: "demo.enable",
  },
  {
    name: "module list",
    expression: `[
      ({ lib, ... }: { options.demo.one = lib.mkEnableOption "one"; })
      ({ lib, ... }: { options.demo.two = lib.mkOption { type = lib.types.str; default = "hi"; description = "two"; }; })
    ]`,
    expected: "demo.one",
  },
  {
    name: "nixosModules attrset",
    expression: `{
      default = { lib, ... }: { options.demo.three = lib.mkEnableOption "three"; };
      extra = { lib, ... }: { options.demo.four = lib.mkEnableOption "four"; };
    }`,
    expected: "demo.four",
  },
];

class Cdp {
  constructor(url) {
    this.nextId = 1;
    this.pending = new Map();
    this.ws = new WebSocket(url);
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id) return;
      const callbacks = this.pending.get(message.id);
      if (!callbacks) return;
      this.pending.delete(message.id);
      if (message.error) callbacks.reject(new Error(JSON.stringify(message.error)));
      else callbacks.resolve(message.result);
    });
  }

  async open() {
    await new Promise((resolve, reject) => {
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", reject, { once: true });
    });
  }

  call(method, params = {}) {
    const id = this.nextId;
    this.nextId += 1;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }
}

async function main() {
  const tabs = await fetch(`http://127.0.0.1:${port}/json`).then((response) => response.json());
  const page = tabs.find((tab) => tab.type === "page");
  if (!page) throw new Error("No CDP page target found");

  const cdp = new Cdp(page.webSocketDebuggerUrl);
  await cdp.open();
  await cdp.call("Runtime.enable");
  await cdp.call("Page.enable");

  const storageResult = await cdp.call("Runtime.evaluate", {
    awaitPromise: true,
    returnByValue: true,
    expression: `new Promise((resolve) => {
      const started = Date.now();
      const timer = setInterval(() => {
        const evaluator = window.NixOSRegeditWasiEvaluator;
        if (evaluator && evaluator.storage) {
          clearInterval(timer);
          resolve(evaluator.storage);
        }
        if (Date.now() - started > 20000) {
          clearInterval(timer);
          resolve(null);
        }
      }, 100);
    })`,
  });
  const storage = storageResult.result.value;
  if (
    !storage ||
    storage.enabled !== true ||
    storage.backend !== "IDBFS" ||
    storage.cacheHome !== "/persist/cache" ||
    storage.nixCacheHome !== "/persist/cache/nix" ||
    storage.stateHome !== "/persist/state" ||
    storage.stateDir !== "/persist/state/nix/var/nix"
  ) {
    console.error(JSON.stringify({ storage }, null, 2));
    process.exit(1);
  }
  console.log(`persistent storage: ${storage.backend} at ${storage.mountPoint} (${storage.cacheHome}, ${storage.stateDir})`);

  for (const testCase of cases) {
    const result = await cdp.call("Runtime.evaluate", {
      awaitPromise: true,
      returnByValue: true,
      expression: `new Promise((resolve) => {
        const expression = ${JSON.stringify(testCase.expression)};
        const input = document.getElementById("expressionInput");
        input.value = expression;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        document.getElementById("evaluateButton").click();
        const started = Date.now();
        const timer = setInterval(() => {
          const status = document.getElementById("statusText").textContent;
          const count = document.getElementById("countText").textContent;
          const details = document.getElementById("optionDetails").textContent;
          const diagnostics = document.getElementById("diagnostics").textContent;
          const contentVisible = !document.getElementById("content").hidden;
          if (contentVisible && details.includes(${JSON.stringify(testCase.expected)})) {
            clearInterval(timer);
            resolve({ ok: true, status, count, details, diagnostics });
          }
          if (Date.now() - started > 20000) {
            clearInterval(timer);
            resolve({ ok: false, status, count, details, diagnostics });
          }
        }, 100);
      })`,
    });
    const value = result.result.value;
    if (!value || !value.ok) {
      console.error(JSON.stringify({ testCase: testCase.name, value }, null, 2));
      process.exit(1);
    }
    console.log(`${testCase.name}: ${value.count} (${value.status})`);
  }
  cdp.ws.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
