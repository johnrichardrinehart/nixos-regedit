const fs = require("fs");

if (process.argv.length !== 4) {
  console.error("usage: browser_evaluator_smoke.js EVALUATOR_JS LOADER_JS");
  process.exit(2);
}

global.window = new EventTarget();
window.dispatchEvent = () => {};
global.CustomEvent = class CustomEvent extends Event {
  constructor(type, init) {
    super(type);
    this.detail = init && init.detail;
  }
};

eval(fs.readFileSync(process.argv[2], "utf8"));
eval(fs.readFileSync(process.argv[3], "utf8"));

const cases = [
  {
    name: "single module",
    expression: '{ lib, ... }: { options.demo.enable = lib.mkEnableOption "demo"; }',
    keys: ["demo.enable"],
  },
  {
    name: "module list",
    expression: `[
      ({ lib, ... }: { options.demo.one = lib.mkEnableOption "one"; })
      ({ lib, ... }: { options.demo.two = lib.mkOption { type = lib.types.str; default = "hi"; description = "two"; }; })
    ]`,
    keys: ["demo.one", "demo.two"],
  },
  {
    name: "nixosModules attrset",
    expression: `{
      default = { lib, ... }: { options.demo.three = lib.mkEnableOption "three"; };
      extra = { lib, ... }: { options.demo.four = lib.mkEnableOption "four"; };
    }`,
    keys: ["demo.four", "demo.three"],
  },
];

(async () => {
  await window.NixOSRegeditLoadEvaluator();
  const evaluator = window.NixOSRegeditWasiEvaluator;
  for (const testCase of cases) {
    const result = await evaluator.evaluate({
      expression: testCase.expression,
      system: "x86_64-linux",
      allowFetch: false,
    });
    const actualKeys = Object.keys(result.options || {}).sort();
    const expectedKeys = testCase.keys.slice().sort();
    if (!result.ok || JSON.stringify(actualKeys) !== JSON.stringify(expectedKeys)) {
      console.error(JSON.stringify({ testCase: testCase.name, result, actualKeys, expectedKeys }, null, 2));
      process.exit(1);
    }
    console.log(`${testCase.name}: ${actualKeys.join(", ")}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
