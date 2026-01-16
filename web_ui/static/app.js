const streamsList = document.getElementById("streams-list");
const mappingsList = document.getElementById("mappings-list");
const streamSelect = document.getElementById("stream-select");
const trackInput = document.getElementById("track-index");
const deviceInput = document.getElementById("device-index");
const paramInput = document.getElementById("parameter-index");
const rangeMinInput = document.getElementById("range-min");
const rangeMaxInput = document.getElementById("range-max");
const smoothingInput = document.getElementById("smoothing");
const enabledInput = document.getElementById("enabled");
const lastSelectedHint = document.getElementById("last-selected-hint");

async function fetchJson(url) {
  const res = await fetch(url);
  return res.json();
}

async function refreshStreams() {
  const data = await fetchJson("/api/streams");
  const streams = data.streams || [];
  streamsList.innerHTML = "";
  streamSelect.innerHTML = "";

  streams.forEach((stream) => {
    const name = stream.name || stream;
    const li = document.createElement("li");
    li.textContent = name;
    streamsList.appendChild(li);

    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    streamSelect.appendChild(option);
  });
}

function renderMappings(mappings) {
  if (!mappings.length) {
    mappingsList.textContent = "No mappings yet.";
    return;
  }
  const rows = mappings.map((m) => {
    const target = m.target || {};
    return `
      <div class="mapping-row">
        <div>${m.motion_stream}</div>
        <div>Track ${target.track_index} / Device ${target.device_index} / Param ${target.parameter_index}</div>
        <div>Range ${m.range?.[0]} → ${m.range?.[1]} | Smooth ${m.smoothing}</div>
        <button data-stream="${m.motion_stream}" class="delete-btn">Delete</button>
      </div>
    `;
  });
  mappingsList.innerHTML = rows.join("");

  document.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const stream = btn.getAttribute("data-stream");
      await fetch(`/api/mappings/${stream}`, { method: "DELETE" });
      await refreshMappings();
    });
  });
}

async function refreshMappings() {
  const data = await fetchJson("/api/mappings");
  renderMappings(data.mappings || []);
}

async function createMapping() {
  const payload = {
    motion_stream: streamSelect.value,
    track_index: Number(trackInput.value),
    device_index: Number(deviceInput.value),
    parameter_index: Number(paramInput.value),
    range_min: Number(rangeMinInput.value),
    range_max: Number(rangeMaxInput.value),
    smoothing: Number(smoothingInput.value),
    enabled: enabledInput.checked
  };

  const res = await fetch("/api/mappings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    const error = await res.json();
    alert(error.detail || "Failed to create mapping");
    return;
  }
  await refreshMappings();
}

async function fetchLastSelected() {
  const data = await fetchJson("/api/ableton/last-selected");
  if (data && data.type === "parameter") {
    const info = data.data || {};
    trackInput.value = info.track_index ?? "";
    deviceInput.value = info.device_index ?? "";
    paramInput.value = info.param_index ?? "";
    lastSelectedHint.textContent = `Selected: ${info.device_name || "Device"} / ${info.param_name || "Param"}`;
  } else {
    lastSelectedHint.textContent = "No parameter selection found.";
  }
}

document.getElementById("create-mapping").addEventListener("click", createMapping);
document.getElementById("fetch-last-selected").addEventListener("click", fetchLastSelected);

refreshStreams();
refreshMappings();
setInterval(refreshStreams, 1000);
setInterval(refreshMappings, 1500);
