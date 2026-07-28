// Client minimale: invio, stato richiesta e consultazione dei risultati.
const gridElement = document.querySelector("#sudoku-grid");
const gridStringElement = document.querySelector("#grid-string");
const formElement = document.querySelector("#analysis-form");
const submitButton = document.querySelector("#submit-button");
const requestStatus = document.querySelector("#request-status");
const resultPanel = document.querySelector("#result-panel");
const connectionStatus = document.querySelector("#connection-status");
const jsonElement = document.querySelector("#analysis-json");
let currentAnalysis = null;
let currentName = "sudoku-analysis";
let solutionStates = [];
let currentSolutionState = 0;

const cells = Array.from({ length: 81 }, (_, index) => {
  const input = document.createElement("input");
  const row = Math.floor(index / 9);
  const column = index % 9;

  input.className = "sudoku-cell";
  input.type = "text";
  input.inputMode = "numeric";
  input.maxLength = 1;
  input.autocomplete = "off";
  input.setAttribute("aria-label", `Riga ${row + 1}, colonna ${column + 1}`);

  if (column === 2 || column === 5) input.classList.add("box-right");
  if (row === 2 || row === 5) input.classList.add("box-bottom");

  input.addEventListener("input", () => {
    input.value = input.value.replace(/[^1-9]/g, "").slice(-1);
    updateStringFromCells();
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight" && index < 80) cells[index + 1].focus();
    if (event.key === "ArrowLeft" && index > 0) cells[index - 1].focus();
    if (event.key === "ArrowDown" && index < 72) cells[index + 9].focus();
    if (event.key === "ArrowUp" && index > 8) cells[index - 9].focus();
  });

  gridElement.appendChild(input);
  return input;
});

function normaliseGridText(value) {
  return value.replace(/\s/g, "").replace(/\./g, "0");
}

function updateStringFromCells() {
  gridStringElement.value = cells
    .map((cell) => cell.value || "0")
    .join("");
}

function updateCellsFromString(value) {
  const normalised = normaliseGridText(value);
  if (normalised.length > 81 || /[^0-9]/.test(normalised)) return false;

  cells.forEach((cell, index) => {
    const valueAtCell = normalised[index] || "0";
    cell.value = valueAtCell === "0" ? "" : valueAtCell;
  });
  return true;
}

gridStringElement.addEventListener("input", () => {
  updateCellsFromString(gridStringElement.value);
});

document.querySelector("#clear-grid").addEventListener("click", () => {
  cells.forEach((cell) => {
    cell.value = "";
  });
  gridStringElement.value = "";
  cells[0].focus();
});

function setRequestStatus(message, isError = false) {
  requestStatus.hidden = false;
  requestStatus.textContent = message;
  requestStatus.classList.toggle("error", isError);
}

function readableError(payload, fallback) {
  if (!payload) return fallback;
  if (typeof payload.detail === "string") return payload.detail;
  if (Array.isArray(payload.detail)) {
    return payload.detail.map((item) => item.msg).join("; ");
  }
  return fallback;
}

function renderResult(payload) {
  const grading = payload.analysis.grading || {};
  currentAnalysis = payload.analysis;
  currentName = payload.name || "sudoku-analysis";

  document.querySelector("#result-name").textContent = payload.name;
  document.querySelector("#difficulty-label").textContent =
    grading.label || "N/A";
  document.querySelector("#max-difficulty").textContent =
    grading.max_difficulty ?? "—";
  document.querySelector("#perceived-difficulty").textContent =
    Number.isFinite(grading.perceived_difficulty)
      ? grading.perceived_difficulty.toFixed(3)
      : "—";
  document.querySelector("#step-count").textContent =
    grading.n_steps ?? payload.analysis.chain?.length ?? "—";
  document.querySelector("#analysis-status").textContent =
    payload.analysis.status || "—";

  const duplicateText = payload.is_isomorphic_duplicate
    ? ` · ${payload.isomorphic_variant_count} varianti isomorfe`
    : " · variante unica nell’archivio web";
  document.querySelector("#identity-summary").textContent =
    `puzzle ${payload.puzzle_id} · canonico ${payload.canonical_id}${duplicateText}`;

  jsonElement.textContent = JSON.stringify(payload.analysis, null, 2);
  prepareSolutionPlayer(payload.analysis);

  if (payload.plots) {
    const cacheToken = `&_=${Date.now()}`;
    document.querySelector("#difficulty-plot").src =
      `${payload.plots.difficulty_chain}${cacheToken}`;
    document.querySelector("#heatmap-plot").src =
      `${payload.plots.technique_heatmap}${cacheToken}`;
  }

  resultPanel.hidden = false;
  resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

const solutionGridElement = document.querySelector("#solution-grid");
const solutionCells = Array.from({ length: 81 }, (_, index) => {
  const cell = document.createElement("div");
  const row = Math.floor(index / 9);
  const column = index % 9;
  cell.className = "solution-cell";
  if (column === 2 || column === 5) cell.classList.add("box-right");
  if (row === 2 || row === 5) cell.classList.add("box-bottom");
  solutionGridElement.appendChild(cell);
  return cell;
});

function flattenGrid(grid) {
  if (typeof grid === "string") {
    return grid.split("").map((value) => Number(value));
  }
  return grid.flat().map((value) => Number(value));
}

function cellKey(cell) {
  return `${Number(cell[0])}:${Number(cell[1])}`;
}

function moveHighlights(move) {
  const highlight = move?.highlight || {};
  const primary = new Set(
    (highlight.primary || []).map(cellKey)
  );
  const secondary = new Set(
    (highlight.secondary || []).map(cellKey)
  );

  for (const placement of move?.placements || []) {
    primary.add(cellKey(placement));
  }
  for (const elimination of move?.eliminations || []) {
    secondary.add(cellKey(elimination));
  }
  for (const key of primary) secondary.delete(key);
  return { primary, secondary };
}

function prepareSolutionPlayer(analysis) {
  const chain = analysis.chain || [];
  solutionStates = [
    {
      grid: analysis.original,
      title: "Griglia iniziale",
      technique: "Stato iniziale",
      description: "I valori originali del puzzle.",
      move: null,
    },
    ...chain.map((move) => ({
      grid: move.grid_after,
      title: `Passaggio ${move.step}`,
      technique: `${move.technique} · SE ${move.difficulty}`,
      description: move.description,
      move,
    })),
    {
      grid: analysis.solved_grid,
      title: "Soluzione",
      technique: "Griglia risolta",
      description: "Soluzione finale verificata dal motore.",
      move: null,
    },
  ];

  const slider = document.querySelector("#step-slider");
  slider.max = Math.max(solutionStates.length - 1, 0);
  slider.value = 0;
  currentSolutionState = 0;
  renderSolutionState();
}

function renderSolutionState() {
  if (!solutionStates.length) return;
  const state = solutionStates[currentSolutionState];
  const values = flattenGrid(state.grid);
  const original = flattenGrid(currentAnalysis.original);
  const { primary, secondary } = moveHighlights(state.move);

  solutionCells.forEach((cell, index) => {
    const row = Math.floor(index / 9);
    const column = index % 9;
    const key = `${row}:${column}`;
    const value = values[index];
    cell.textContent = value === 0 ? "" : value;
    cell.classList.toggle("given", original[index] !== 0);
    cell.classList.toggle(
      "solved-value",
      original[index] === 0 && value !== 0
    );
    cell.classList.toggle("primary", primary.has(key));
    cell.classList.toggle("secondary", secondary.has(key));
  });

  document.querySelector("#player-title").textContent = state.title;
  document.querySelector("#player-step").textContent =
    `${currentSolutionState} / ${solutionStates.length - 1}`;
  document.querySelector("#step-technique").textContent = state.technique;
  document.querySelector("#step-description").textContent = state.description;
  document.querySelector("#step-slider").value = currentSolutionState;
}

function setSolutionState(index) {
  currentSolutionState = Math.max(
    0,
    Math.min(Number(index), solutionStates.length - 1)
  );
  renderSolutionState();
}

document.querySelector("#first-step").addEventListener(
  "click",
  () => setSolutionState(0)
);
document.querySelector("#previous-step").addEventListener(
  "click",
  () => setSolutionState(currentSolutionState - 1)
);
document.querySelector("#next-step").addEventListener(
  "click",
  () => setSolutionState(currentSolutionState + 1)
);
document.querySelector("#last-step").addEventListener(
  "click",
  () => setSolutionState(solutionStates.length - 1)
);
document.querySelector("#step-slider").addEventListener(
  "input",
  (event) => setSolutionState(event.target.value)
);

formElement.addEventListener("submit", async (event) => {
  event.preventDefault();
  updateStringFromCells();
  const grid = normaliseGridText(gridStringElement.value);

  if (grid.length !== 81) {
    setRequestStatus("Inserisci una griglia completa di 81 celle.", true);
    return;
  }

  submitButton.disabled = true;
  setRequestStatus(
    "Analisi in corso. La richiesta resta aperta finché il motore termina…"
  );

  try {
    const response = await fetch("/api/v1/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        grid,
        provenience: document.querySelector(
          "#puzzle-provenience"
        ).value,
        tag: document.querySelector("#puzzle-tag").value,
        difficulty: document.querySelector(
          "#puzzle-difficulty"
        ).value,
        analysis_mode: "profile",
        profile_difficulty_window: 3.0,
      }),
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(readableError(payload, `Errore HTTP ${response.status}`));
    }

    const result = await waitForJob(payload.status_url);
    renderResult(result);
    setRequestStatus(
      "Analisi completata e salvata nell’archivio web separato."
    );
  } catch (error) {
    setRequestStatus(error.message || "Errore durante l’analisi.", true);
  } finally {
    submitButton.disabled = false;
  }
});

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitForJob(statusUrl) {
  while (true) {
    const response = await fetch(statusUrl, { cache: "no-store" });
    const job = await response.json();

    if (!response.ok) {
      throw new Error(readableError(job, `Errore HTTP ${response.status}`));
    }

    if (job.status === "completed") return job.result;
    if (job.status === "failed") {
      throw new Error(job.error || "Il job di analisi non è riuscito.");
    }

    setRequestStatus(
      job.status === "queued"
        ? "Analisi in coda…"
        : "Il motore logico sta analizzando il Sudoku…"
    );
    await sleep(700);
  }
}

document.querySelector("#download-json").addEventListener("click", () => {
  if (!currentAnalysis) return;

  const blob = new Blob(
    [JSON.stringify(currentAnalysis, null, 2)],
    { type: "application/json" }
  );
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${currentName.replace(/[^a-z0-9_-]+/gi, "_")}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
});

async function checkHealth() {
  try {
    const response = await fetch("/api/v1/health");
    if (!response.ok) throw new Error();
    const payload = await response.json();
    connectionStatus.classList.add("online");
    connectionStatus.querySelector("span:last-child").textContent =
      `Server LAN · archivio ${payload.archive_profile}`;
  } catch {
    connectionStatus.classList.add("offline");
    connectionStatus.querySelector("span:last-child").textContent =
      "Server non raggiungibile";
  }
}

checkHealth();
cells[0].focus();
