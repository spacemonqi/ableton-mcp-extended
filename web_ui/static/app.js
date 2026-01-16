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

// Chart setup
const chartCanvas = document.getElementById("stream-chart");
const MAX_DATA_POINTS = 150;
const STREAM_COLORS = [
  '#2f6df6', '#f62f6d', '#6df62f', '#f6d62f', '#d62ff6', 
  '#2ff6d6', '#f6962f', '#6d2ff6', '#2ff696', '#f62f96'
];

const selectedStreams = new Set();
const streamDataHistory = {}; // {streamName: [values]}

const chartData = {
  labels: [],
  datasets: []
};

const chart = new Chart(chartCanvas, {
  type: 'line',
  data: chartData,
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    scales: {
      x: { display: false },
      y: {
        min: 0,
        max: 1,
        grid: { color: '#2a2f3a' },
        ticks: { color: '#9aa3b2' }
      }
    },
    plugins: {
      legend: { 
        display: true,
        labels: { color: '#f2f2f2' }
      }
    }
  }
});

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
    
    // Clickable list item for visualization
    const li = document.createElement("li");
    li.textContent = name;
    li.dataset.stream = name;
    if (selectedStreams.has(name)) {
      li.classList.add("selected");
    }
    li.addEventListener("click", () => toggleStreamSelection(name));
    streamsList.appendChild(li);

    // Dropdown for mapping creation
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    streamSelect.appendChild(option);
  });
}

function toggleStreamSelection(streamName) {
  if (selectedStreams.has(streamName)) {
    selectedStreams.delete(streamName);
    delete streamDataHistory[streamName];
  } else {
    selectedStreams.add(streamName);
    streamDataHistory[streamName] = [];
  }
  
  // Update UI
  document.querySelectorAll('.streams-list-selectable li').forEach(li => {
    if (li.dataset.stream === streamName) {
      li.classList.toggle('selected');
    }
  });
  
  // Rebuild chart datasets
  rebuildChartDatasets();
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

function rebuildChartDatasets() {
  chartData.datasets = [];
  
  Array.from(selectedStreams).forEach((streamName, index) => {
    const color = STREAM_COLORS[index % STREAM_COLORS.length];
    chartData.datasets.push({
      label: streamName,
      data: streamDataHistory[streamName] || [],
      borderColor: color,
      backgroundColor: color.replace(')', ', 0.1)').replace('rgb', 'rgba'),
      borderWidth: 2,
      tension: 0.4,
      fill: false,
      pointRadius: 0
    });
  });
  
  chart.update();
}

async function updateChart() {
  if (selectedStreams.size === 0) return;

  try {
    const data = await fetchJson("/api/stream-values");
    const values = data.values || {};

    // Update time labels
    if (chartData.labels.length === 0 || chartData.labels.length < MAX_DATA_POINTS) {
      chartData.labels.push('');
    }

    // Update each selected stream's data
    selectedStreams.forEach((streamName) => {
      const value = values[streamName];
      if (value !== undefined) {
        if (!streamDataHistory[streamName]) {
          streamDataHistory[streamName] = [];
        }
        streamDataHistory[streamName].push(value);

        // Keep only last MAX_DATA_POINTS
        if (streamDataHistory[streamName].length > MAX_DATA_POINTS) {
          streamDataHistory[streamName].shift();
        }
      }
    });

    // Trim labels to match data
    if (chartData.labels.length > MAX_DATA_POINTS) {
      chartData.labels.shift();
    }

    // Update chart datasets with new data
    chartData.datasets.forEach((dataset) => {
      dataset.data = streamDataHistory[dataset.label] || [];
    });

    chart.update('none'); // 'none' mode = no animation for better performance
  } catch (e) {
    // Ignore errors (router might not be running)
  }
}
document.getElementById("create-mapping").addEventListener("click", createMapping);
document.getElementById("fetch-last-selected").addEventListener("click", fetchLastSelected);

refreshStreams();
refreshMappings();
setInterval(refreshStreams, 1000);
setInterval(refreshMappings, 1500);
setInterval(updateChart, 50); // 20Hz update rate
