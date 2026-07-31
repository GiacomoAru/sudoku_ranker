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
let currentPhotoId = null;

const STATUS_PRESENTATION = {
  solved: {
    label: "Risolto",
    className: "status-solved",
  },
  stuck: {
    label: "Bloccato",
    className: "status-stuck",
  },
  contradiction: {
    label: "Contraddizione",
    className: "status-contradiction",
  },
  interrupted: {
    label: "Interrotto",
    className: "status-interrupted",
  },
};


function renderStatusBadge(status) {
  const badge = document.querySelector(
    "#analysis-status-badge"
  );

  if (!badge) return;

  const key = String(status || "").toLowerCase();

  const presentation = (
    STATUS_PRESENTATION[key]
    || {
      label: status || "Sconosciuto",
      className: "status-unknown",
    }
  );

  badge.className = (
    `result-label status-badge ` +
    presentation.className
  );

  badge.textContent = presentation.label;
}

function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatNumber(value, decimals = 1) {
  const number = finiteNumber(value);
  return number === null ? "—" : number.toFixed(decimals);
}

function formatMetricWithLabel(value, label, decimals = 1) {
  const number = finiteNumber(value);

  if (number === null) {
    return "—";
  }

  const formatted = number.toFixed(decimals);

  return label
    ? `${formatted} · ${label}`
    : formatted;
}

function setText(selector, value) {
  const element = document.querySelector(selector);

  if (!element) {
    console.warn(`Elemento HTML non trovato: ${selector}`);
    return;
  }

  element.textContent = value ?? "—";
}

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
    input.classList.remove("ocr-low-confidence");
    input.removeAttribute("title");
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

const metadataDetails = document.querySelector("#metadata-details");
const metadataCount = document.querySelector("#metadata-count");
const metadataInputs = Array.from(
  metadataDetails.querySelectorAll("input, textarea")
);

function optionalText(selector) {
  const value = document.querySelector(selector)?.value;
  const cleaned = String(value || "").trim();
  return cleaned || null;
}

function collectPuzzleMetadata() {
  const acquisitionMetadata = currentPhotoId
    ? {
        input_method: "photo",
        photo_id: currentPhotoId,
      }
    : {
        input_method: "manual",
      };

  const metadata = {
    title: optionalText("#puzzle-title"),
    source: optionalText("#puzzle-source"),
    source_reference: optionalText("#puzzle-source-reference"),
    stated_difficulty: optionalText("#puzzle-stated-difficulty"),
    author_or_publisher: optionalText("#puzzle-author"),
    published_at: optionalText("#puzzle-published-at"),
    notes: optionalText("#puzzle-notes"),
    entry_channel: "web",
    ...acquisitionMetadata,
  };

  return Object.fromEntries(
    Object.entries(metadata).filter(([, value]) => (
      value !== null && value !== ""
    ))
  );
}

function buildAnalysisRequest(grid) {
  const metadata = collectPuzzleMetadata();

  return {
    grid,
    name: metadata.title || null,
    metadata,
    analysis_mode: "profile",
    profile_difficulty_window: 1.5,
    photo_id: metadata.photo_id || null,
  };
}

function updateMetadataCount() {
  const count = metadataInputs.filter(
    (input) => String(input.value || "").trim()
  ).length;

  metadataCount.textContent = count === 0
    ? "Nessun dettaglio"
    : `${count} ${count === 1 ? "dettaglio" : "dettagli"}`;
  metadataCount.classList.toggle("has-values", count > 0);
}

function resetMetadata() {
  metadataInputs.forEach((input) => {
    input.value = "";
  });
  metadataDetails.open = false;
  updateMetadataCount();
}

metadataInputs.forEach((input) => {
  input.addEventListener("input", updateMetadataCount);
  input.addEventListener("change", updateMetadataCount);
});
updateMetadataCount();

document.querySelector("#clear-grid").addEventListener("click", () => {
  cells.forEach((cell) => {
    cell.value = "";
    cell.classList.remove("ocr-low-confidence");
  });
  gridStringElement.value = "";
  resetPhoto();
  resetMetadata();
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
  if (
    payload.detail &&
    typeof payload.detail === "object" &&
    typeof payload.detail.message === "string"
  ) {
    const archived = payload.detail.photo_id
      ? ` Foto archiviata con ID ${payload.detail.photo_id}.`
      : "";
    return `${payload.detail.message}${archived}`;
  }
  if (Array.isArray(payload.detail)) {
    return payload.detail.map((item) => item.msg).join("; ");
  }
  return fallback;
}

const photoInput = document.querySelector("#photo-input");
const photoStatus = document.querySelector("#photo-status");
const photoReview = document.querySelector("#photo-review");
const photoReviewNote = document.querySelector("#photo-review-note");
const clearPhotoButton = document.querySelector("#clear-photo");

function setPhotoStatus(message, isError = false) {
  photoStatus.hidden = false;
  photoStatus.textContent = message;
  photoStatus.classList.toggle("error", isError);
}

function clearOcrHighlights() {
  cells.forEach((cell) => {
    cell.classList.remove("ocr-low-confidence");
    cell.removeAttribute("title");
  });
}

function resetPhoto() {
  currentPhotoId = null;
  photoInput.value = "";
  photoStatus.hidden = true;
  photoReview.hidden = true;
  photoReviewNote.hidden = true;
  clearPhotoButton.hidden = true;
  clearOcrHighlights();
  document.querySelector("#photo-original-preview").removeAttribute("src");
  document.querySelector("#photo-rectified-preview").removeAttribute("src");
}

async function recognisePhoto(file) {
  const formData = new FormData();
  formData.append("photo", file);
  photoInput.disabled = true;
  clearOcrHighlights();
  setPhotoStatus(
    "Foto caricata. Individuo la griglia, correggo la prospettiva e leggo le cifre…"
  );

  try {
    const response = await fetch("/api/v1/photos/recognise", {
      method: "POST",
      body: formData,
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(
        readableError(payload, `Errore OCR HTTP ${response.status}`)
      );
    }

    currentPhotoId = payload.photo_id;
    updateCellsFromString(payload.grid);
    gridStringElement.value = payload.grid;
    payload.low_confidence_indices.forEach((index) => {
      cells[index]?.classList.add("ocr-low-confidence");
    });
    payload.cells.forEach((recognisedCell) => {
      if (!recognisedCell.detected) return;
      const alternatives = recognisedCell.candidates
        .map((candidate) => (
          `${candidate.digit} (${(candidate.confidence * 100).toFixed(0)}%)`
        ))
        .join(", ");
      cells[recognisedCell.index].title =
        `OCR ${(recognisedCell.confidence * 100).toFixed(0)}%` +
        (alternatives ? ` · alternative: ${alternatives}` : "");
    });

    const cacheToken = `?_=${Date.now()}`;
    document.querySelector("#photo-original-preview").src =
      `${payload.original_url}${cacheToken}`;
    document.querySelector("#photo-rectified-preview").src =
      `${payload.rectified_url}${cacheToken}`;
    photoReview.hidden = false;
    photoReviewNote.hidden = false;
    clearPhotoButton.hidden = false;

    const confidence = (payload.mean_confidence * 100).toFixed(0);
    const uncertain = payload.low_confidence_indices.length;
    const warningText = payload.warnings.length
      ? ` ${payload.warnings.join(" ")}`
      : "";
    setPhotoStatus(
      `${payload.detected_digit_count} cifre rilevate · confidenza media ` +
      `${confidence}% · ${uncertain} celle da controllare.${warningText}`
    );
    cells[payload.low_confidence_indices[0] ?? 0].focus();
  } catch (error) {
    currentPhotoId = null;
    photoReview.hidden = true;
    photoReviewNote.hidden = true;
    clearPhotoButton.hidden = true;
    setPhotoStatus(
      error.message || "Errore durante il riconoscimento della foto.",
      true
    );
  } finally {
    photoInput.disabled = false;
  }
}

photoInput.addEventListener("change", () => {
  const [file] = photoInput.files;

  if (file) recognisePhoto(file);
});

clearPhotoButton.addEventListener("click", resetPhoto);

const jsonDetailsElement = document.querySelector(".json-card");
const jsonSummaryAction = jsonDetailsElement.querySelector(".summary-action");

function updateJsonSummaryAction() {
  jsonSummaryAction.textContent = jsonDetailsElement.open
    ? "Chiudi"
    : "Apri";
}

jsonDetailsElement.addEventListener("toggle", updateJsonSummaryAction);
updateJsonSummaryAction();

const METRIC_TONE_CLASSES = [
  "tone-very-low",
  "tone-low",
  "tone-medium",
  "tone-high",
  "tone-very-high",
  "tone-extreme",
  "tone-over-limit",
  "tone-neutral",
];


function metricToneFromLabel(label) {
  const normalised = String(label || "")
    .trim()
    .toLowerCase();

  const tones = {
    "immediata": "tone-very-low",
    "molto facile": "tone-very-low",
    "molto basso": "tone-very-low",
    "molto bassa": "tone-very-low",

    "facile": "tone-low",
    "basso": "tone-low",
    "bassa": "tone-low",

    "moderata": "tone-medium",
    "moderato": "tone-medium",
    "medio": "tone-medium",
    "media": "tone-medium",

    "difficile": "tone-high",
    "alto": "tone-high",
    "alta": "tone-high",

    "molto difficile": "tone-very-high",
    "molto alto": "tone-very-high",
    "molto alta": "tone-very-high",
    "esperto": "tone-very-high",

    "diabolico": "tone-extreme",
    "estremo": "tone-extreme",
    "estrema": "tone-extreme",
    "incubo": "tone-extreme",

    "quasi obbligata": "tone-extreme",
    "oltre il limite": "tone-over-limit",
  };

  return tones[normalised] || "tone-neutral";
}

function setMetricTone(selector, label) {
  const metric = document.querySelector(selector);

  if (!metric) return;

  metric.classList.remove(...METRIC_TONE_CLASSES);
  metric.classList.add(metricToneFromLabel(label));
}

function renderResult(payload) {
  const grading = payload.analysis.grading || {};
  currentAnalysis = payload.analysis;
  currentName = payload.name || "sudoku-analysis";

  renderStatusBadge(payload.analysis.status);
  setText("#result-name", payload.name || "Analisi");
  setText(
    "#technical-difficulty",
    formatMetricWithLabel(
      grading.technical_difficulty,
      grading.technical_difficulty_label,
      1
    )
  );
  setText(
    "#resolution-load",
    formatMetricWithLabel(
      grading.resolution_load,
      grading.resolution_load_label,
      2
    )
  );
  setText(
    "#move-discovery-difficulty",
    formatMetricWithLabel(
      grading.move_discovery_difficulty,
      grading.move_discovery_difficulty_label,
      2
    )
  );
  setText(
    "#step-count",
    grading.step_count ?? payload.analysis.chain?.length ?? "—"
  );
  setText(
    "#hardest-technique",
    grading.hardest_technique || "—"
  );
  
  setMetricTone(
    "#metric-technical",
    grading.technical_difficulty_label
  );

  setMetricTone(
    "#metric-resolution-load",
    grading.resolution_load_label
  );

  setMetricTone(
    "#metric-move-discovery-difficulty",
    grading.move_discovery_difficulty_label
  );

  setMetricTone(
    "#metric-hardest-technique",
    grading.technical_difficulty_label
  );

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
      technique: (
        `${move.technique} · SE ` +
        `${formatNumber(move.technical_difficulty, 1)}` +
        (
          finiteNumber(move.resolution_load) !== null
            ? ` · carico +${formatNumber(move.resolution_load, 2)}`
            : ""
        ) +
        (
          finiteNumber(move.move_discovery_difficulty) !== null
            ? (
                ` · individuazione ` +
                `${formatNumber(move.move_discovery_difficulty, 2)}`
              )
            : ""
        )
      ),
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
      body: JSON.stringify(buildAnalysisRequest(grid)),
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
    if (currentPhotoId) {
      setPhotoStatus(
        `Foto ${currentPhotoId} confermata e collegata al Sudoku salvato.`
      );
    }
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
