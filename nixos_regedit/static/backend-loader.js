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

  async function postJsonStream(path, payload, onDebugLog) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.body || typeof response.body.getReader !== "function") {
      return responsePayload(response);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalPayload = null;

    const handleLine = (line) => {
      if (!line.trim()) return;
      let event;
      try {
        event = JSON.parse(line);
      } catch (error) {
        return;
      }
      if (event.type === "debug" && event.entry && typeof onDebugLog === "function") {
        onDebugLog(event.entry);
      } else if (event.type === "result") {
        finalPayload = event.payload || {};
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || "";
      lines.forEach(handleLine);
      if (done) break;
    }
    handleLine(buffer);
    return finalPayload || { ok: false, error: "stream ended without an evaluation result" };
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
      const { onDebugLog, ...request } = payload || {};
      return postJsonStream("/api/evaluate-stream", request, onDebugLog);
    },
  };

  window.dispatchEvent(new CustomEvent("nixos-regedit-evaluator-ready"));
})();
