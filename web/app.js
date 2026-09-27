const state = { dataset: null, sessionId: null, busy: false };

const elements = {
  connection: document.querySelector("#connectionStatus"),
  dropZone: document.querySelector("#dropZone"),
  fileInput: document.querySelector("#fileInput"),
  uploadStatus: document.querySelector("#uploadStatus"),
  datasetPanel: document.querySelector("#datasetPanel"),
  datasetName: document.querySelector("#datasetName"),
  rowCount: document.querySelector("#rowCount"),
  columnCount: document.querySelector("#columnCount"),
  columnList: document.querySelector("#columnList"),
  replaceDataset: document.querySelector("#replaceDataset"),
  statePanel: document.querySelector("#statePanel"),
  stateGoal: document.querySelector("#stateGoal"),
  stateTarget: document.querySelector("#stateTarget"),
  stateStatus: document.querySelector("#stateStatus"),
  findingList: document.querySelector("#findingList"),
  messages: document.querySelector("#messages"),
  emptyState: document.querySelector("#emptyState"),
  form: document.querySelector("#questionForm"),
  question: document.querySelector("#questionInput"),
  send: document.querySelector("#sendButton"),
  examples: document.querySelectorAll(".example-grid button"),
};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "The request failed.");
  return payload;
}

function setBusy(busy) {
  state.busy = busy;
  const enabled = Boolean(state.sessionId) && !busy;
  elements.question.disabled = !enabled;
  elements.send.disabled = !enabled;
  elements.fileInput.disabled = busy;
}

function setConnection(status, label) {
  elements.connection.className = `connection ${status}`;
  elements.connection.querySelector("span:last-child").textContent = label;
}

function addMessage(role, content, kind = "") {
  elements.emptyState.hidden = true;
  const item = document.createElement("article");
  item.className = `message ${role} ${kind}`.trim();
  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.textContent = role === "user" ? "You" : "Dataset Explorer";
  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = content;
  item.append(meta, body);
  elements.messages.append(item);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  return item;
}

function addThinking() {
  const item = addMessage("assistant", "");
  item.querySelector(".message-body").innerHTML =
    '<span class="thinking" aria-label="Analyzing"><span></span><span></span><span></span></span>';
  return item;
}

function renderDataset(dataset) {
  state.dataset = dataset;
  elements.datasetPanel.hidden = false;
  elements.statePanel.hidden = false;
  elements.datasetName.textContent = dataset.filename;
  elements.rowCount.textContent = dataset.row_count.toLocaleString();
  elements.columnCount.textContent = dataset.column_count.toLocaleString();
  elements.columnList.replaceChildren();

  for (const column of dataset.schema.column_details) {
    const chip = document.createElement("span");
    chip.className = `column-chip ${column.type === "numerical" ? "numeric" : ""}`;
    chip.textContent = column.name;
    chip.title = `${column.dtype} · ${column.unique} unique · ${column.missing} missing`;
    elements.columnList.append(chip);
  }

  elements.emptyState.querySelector("h2").textContent = "Your dataset is ready";
  elements.emptyState.querySelector("p").textContent =
    "Ask a question or choose a useful starting point below.";
  for (const button of elements.examples) button.disabled = false;
}

function renderAnalysisState(analysisState) {
  elements.stateGoal.textContent = analysisState.goal || "Waiting for your question";
  elements.stateTarget.textContent = analysisState.target || "Not selected";
  elements.stateStatus.textContent = analysisState.status || "New";
  elements.findingList.replaceChildren();

  for (const finding of analysisState.findings || []) {
    const item = document.createElement("div");
    item.className = "finding";
    item.textContent = finding.statement || finding.finding || JSON.stringify(finding);
    elements.findingList.append(item);
  }
}

async function upload(file) {
  if (!file || state.busy) return;
  setBusy(true);
  elements.uploadStatus.className = "upload-status";
  elements.uploadStatus.textContent = `Uploading ${file.name}…`;

  try {
    const formData = new FormData();
    formData.append("file", file);
    const dataset = await api("/api/datasets", { method: "POST", body: formData });
    const session = await api("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataset_id: dataset.id }),
    });
    state.sessionId = session.id;
    renderDataset(dataset);
    renderAnalysisState(session.state);
    elements.uploadStatus.textContent = "Upload complete";
    elements.question.placeholder = "Ask what you want to understand about this dataset";
    setBusy(false);
    elements.question.focus();
  } catch (error) {
    elements.uploadStatus.className = "upload-status error";
    elements.uploadStatus.textContent = error.message;
    setBusy(false);
  }
}

async function ask(question) {
  if (!question || !state.sessionId || state.busy) return;
  addMessage("user", question);
  elements.question.value = "";
  setBusy(true);
  const thinking = addThinking();

  try {
    const result = await api(`/api/sessions/${state.sessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    thinking.remove();
    addMessage("assistant", result.answer);
    renderAnalysisState(result.state);
  } catch (error) {
    thinking.remove();
    addMessage("assistant", error.message, "error");
  } finally {
    setBusy(false);
    elements.question.focus();
  }
}

elements.fileInput.addEventListener("change", event => upload(event.target.files[0]));
elements.dropZone.addEventListener("dragover", event => {
  event.preventDefault();
  elements.dropZone.classList.add("dragging");
});
elements.dropZone.addEventListener("dragleave", () => {
  elements.dropZone.classList.remove("dragging");
});
elements.dropZone.addEventListener("drop", event => {
  event.preventDefault();
  elements.dropZone.classList.remove("dragging");
  upload(event.dataTransfer.files[0]);
});
elements.replaceDataset.addEventListener("click", () => elements.fileInput.click());
elements.form.addEventListener("submit", event => {
  event.preventDefault();
  ask(elements.question.value.trim());
});
elements.question.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.form.requestSubmit();
  }
});
elements.question.addEventListener("input", () => {
  elements.question.style.height = "auto";
  elements.question.style.height = `${Math.min(elements.question.scrollHeight, 150)}px`;
});
for (const button of elements.examples) {
  button.addEventListener("click", () => ask(button.textContent.trim()));
}

api("/api/health")
  .then(() => setConnection("ready", "Service ready"))
  .catch(() => setConnection("error", "Service unavailable"));
