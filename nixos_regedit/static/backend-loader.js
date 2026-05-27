(function () {
  async function responsePayload(response) {
    const text = await response.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch (error) {
      return { ok: false, error: text };
    }
  }

  async function postJson(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return responsePayload(response);
  }

  window.NixOSRegeditEvaluator = {
    async currentSystem() {
      const response = await fetch("/api/health");
      const payload = await responsePayload(response);
      return payload.system || "x86_64-linux";
    },

    resolve(payload) {
      return postJson("/api/resolve", payload);
    },

    evaluate(payload) {
      return postJson("/api/evaluate", payload);
    },
  };

  window.dispatchEvent(new CustomEvent("nixos-regedit-evaluator-ready"));
})();
