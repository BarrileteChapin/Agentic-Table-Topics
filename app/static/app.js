const topicEl = document.querySelector("#topic");
const minutesEl = document.querySelector("#minutes");
const bandEl = document.querySelector("#band");
const clockEl = document.querySelector("#clock");
const speechEl = document.querySelector("#speech");
const spokenEl = document.querySelector("#spoken");
const evaluateBtn = document.querySelector("#evaluate-text");
const recordBtn = document.querySelector("#record");
const statusEl = document.querySelector("#status");
const transcriptEl = document.querySelector("#transcript");
const sheetEl = document.querySelector("#sheet");
const categoriesEl = document.querySelector("#categories");
const closingEl = document.querySelector("#closing");
const errorEl = document.querySelector("#error");
const newTopicBtn = document.querySelector("#new-topic");
const modelEl = document.querySelector("#model");
const downloadBtn = document.querySelector("#download");
const newRoundBtn = document.querySelector("#new-round");
const openSheetBtn = document.querySelector("#open-sheet");
const closeSheetBtn = document.querySelector("#close-sheet");
const sheetBackdrop = document.querySelector("#sheet-backdrop");

const session = {
  model: "",
  topic: "",
  transcript: "",
  elapsed: 0,
  target: 0,
  pace: null,
  seats: [],
  sheet: null,
};

const seats = new Map(
  [...document.querySelectorAll(".seats li")].map((seat) => [seat.dataset.agent, seat])
);

let recorder = null;
let chunks = [];
let startedAt = 0;
let tick = 0;
let locked = false;

function targetSeconds() {
  const minutes = Number(minutesEl.value);
  return Math.max(1, Number.isFinite(minutes) ? minutes : 2) * 60;
}

function formatClock(seconds) {
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function bandStatus(elapsed, target) {
  if (target <= 0) return "green";
  const ratio = elapsed / target;
  if (ratio < 0.75) return "short";
  if (ratio <= 1) return "green";
  if (ratio <= 1.1) return "yellow";
  return "over";
}

function paintBand() {
  const target = targetSeconds();
  const green = target * 0.75;
  const yellow = target * 1.1;
  bandEl.textContent =
    `Short under ${formatClock(green)} · Green ${formatClock(green)}–${formatClock(target)} · ` +
    `Yellow to ${formatClock(yellow)} · Over after that`;
}

function paintClock(elapsed) {
  const status = bandStatus(elapsed, targetSeconds());
  clockEl.textContent = formatClock(elapsed);
  clockEl.className = `clock ${status}`;
}

function spokenSeconds() {
  const minutes = Number(spokenEl.value);
  return Math.max(1, Number.isFinite(minutes) ? minutes : 2) * 60;
}

function setLocked(next) {
  locked = next;
  topicEl.disabled = next;
  minutesEl.disabled = next;
  spokenEl.disabled = next;
  speechEl.disabled = next;
  newTopicBtn.disabled = next;
  evaluateBtn.disabled = next;
  modelEl.disabled = next;
  newRoundBtn.disabled = next;
}

function setPose(seat, active) {
  const portrait = seat.querySelector(".portrait");
  if (!portrait) return;
  portrait.src = active ? portrait.dataset.active : portrait.dataset.rest;
}

function setSheetOpen(open) {
  sheetEl.classList.toggle("open", open);
  sheetBackdrop.classList.toggle("open", open);
  sheetEl.setAttribute("aria-hidden", open ? "false" : "true");
}

function resetSeats() {
  for (const seat of seats.values()) {
    seat.classList.remove("active", "done");
    setPose(seat, false);
    const note = seat.querySelector(".note");
    note.hidden = false;
    note.textContent = "Waiting";
    const lines = seat.querySelector(".lines");
    if (lines) lines.remove();
  }
  setSheetOpen(false);
  openSheetBtn.hidden = true;
  categoriesEl.replaceChildren();
  closingEl.replaceChildren();
  transcriptEl.hidden = true;
  transcriptEl.replaceChildren();
  errorEl.hidden = true;
}

function newRound() {
  if (locked) return;
  resetSeats();
  speechEl.value = "";
  paintClock(0);
  statusEl.textContent = "Paste a speech, or record one.";
  session.transcript = "";
  session.elapsed = 0;
  session.pace = null;
  session.seats = [];
  session.sheet = null;
}

function showSeat(seat, report) {
  const note = seat.querySelector(".note");
  const previous = seat.querySelector(".lines");
  if (previous) previous.remove();
  if (!report.lines?.length) {
    note.hidden = false;
    note.textContent = seatNote(report);
    return;
  }
  note.hidden = true;
  const list = document.createElement("ul");
  list.className = "lines";
  for (const line of report.lines) {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.className = "k";
    label.textContent = line.label;
    const value = document.createElement("span");
    value.className = "v";
    value.textContent = line.text;
    item.append(label, value);
    list.append(item);
  }
  seat.append(list);
}

function showTranscript(text) {
  const speech = (text || "").trim();
  transcriptEl.hidden = false;
  transcriptEl.replaceChildren();
  if (speech.length <= 420) {
    transcriptEl.textContent = speech || "No words were heard.";
    return;
  }
  const preview = document.createElement("span");
  const cut = speech.slice(0, 280).replace(/\s+\S*$/, "");
  preview.textContent = `${cut}…`;
  const words = speech.split(/\s+/).length;
  const more = document.createElement("button");
  more.type = "button";
  more.className = "text-btn";
  more.textContent = `Show full speech (${words} words)`;
  more.addEventListener("click", () => {
    transcriptEl.textContent = speech;
  });
  transcriptEl.append(preview, more);
}

function beginSession() {
  session.model = modelEl.selectedOptions[0]?.textContent || modelEl.value;
  session.topic = topicEl.value.trim();
  session.target = targetSeconds();
  session.transcript = "";
  session.elapsed = 0;
  session.pace = null;
  session.seats = [];
  session.sheet = null;
}

function scoreText(category) {
  if (category.score) return `${category.score} ${category.label}`;
  return /not observed/i.test(category.comment || "") ? "Not observed" : "Unscored";
}

function reportText() {
  const lines = [
    "Table Topics",
    `Model: ${session.model}`,
    `Topic: ${session.topic}`,
    `Target: ${formatClock(session.target)}`,
    `Spoken: ${formatClock(session.elapsed)}`,
  ];
  if (session.pace) {
    lines.push(`Pace: ${session.pace.words} words, ${session.pace.wpm} per minute.`);
  }
  lines.push("", "Speech", session.transcript || "", "", "Club");
  for (const seat of session.seats) {
    lines.push("", seat.name);
    if (seat.lines?.length) {
      for (const line of seat.lines) lines.push(`${line.label}: ${line.text}`);
    } else if (seat.note) {
      lines.push(seat.note);
    }
  }
  const sheet = session.sheet;
  if (sheet) {
    lines.push("", "Evaluation");
    for (const category of sheet.categories || []) {
      lines.push("", `${category.name} — ${scoreText(category)}`);
      if (category.comment) lines.push(category.comment);
    }
    lines.push(
      "",
      `You excelled at: ${sheet.excelled_at || ""}`,
      `Work on: ${sheet.work_on || ""}`,
      `Challenge: ${sheet.challenge || ""}`,
    );
  }
  return `${lines.join("\n")}\n`;
}

function downloadReport() {
  const blob = new Blob([reportText()], { type: "text/plain;charset=utf-8" });
  const link = document.createElement("a");
  const day = new Date().toISOString().slice(0, 10);
  link.href = URL.createObjectURL(blob);
  link.download = `table-topics-${day}.txt`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function seatNote(report) {
  if (report.note) return report.note;
  if (Array.isArray(report.strengths) || Array.isArray(report.issues)) {
    const strengths = report.strengths?.length ? `Good: ${report.strengths.join("; ")}` : "";
    const issues = report.issues?.length ? `Watch: ${report.issues.join("; ")}` : "";
    return [strengths, issues].filter(Boolean).join(" ") || "No wording notes.";
  }
  if (report.summary) return report.summary;
  if (report.categories) return "Sheet is on the podium.";
  return "Noted.";
}

function showSheet(report) {
  categoriesEl.replaceChildren();
  for (const category of report.categories || []) {
    const item = document.createElement("li");
    const head = document.createElement("div");
    head.className = "cat-head";
    const name = document.createElement("span");
    name.textContent = category.name;
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = scoreText(category);
    head.append(name, score);
    const comment = document.createElement("p");
    comment.textContent = category.comment || "";
    item.append(head, comment);
    categoriesEl.append(item);
  }
  closingEl.replaceChildren();
  for (const [label, key] of [
    ["You excelled at", "excelled_at"],
    ["Work on", "work_on"],
    ["Challenge", "challenge"],
  ]) {
    const wrap = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = report[key] || "";
    wrap.append(term, detail);
    closingEl.append(wrap);
  }
  openSheetBtn.hidden = false;
  setSheetOpen(true);
}

async function loadTopic() {
  const response = await fetch("/api/topic");
  const body = await response.json();
  topicEl.value = body.topic;
}

function markWorking(name) {
  const seat = seats.get(name);
  if (!seat || seat.classList.contains("done")) return;
  for (const [agent, other] of seats) {
    const working = agent === name;
    other.classList.toggle("active", working);
    setPose(other, working);
  }
  const note = seat.querySelector(".note");
  note.hidden = false;
  note.textContent = name === "Evaluator" ? "Writing the sheet." : "Listening.";
}

function handleEvent(eventName, payload) {
  if (eventName === "status") {
    statusEl.textContent = payload.phase === "transcribing"
      ? "Transcribing the recording."
      : "The club is listening, one seat at a time.";
    return;
  }
  if (eventName === "transcript") {
    session.transcript = payload.transcript || "";
    session.elapsed = payload.elapsed_seconds || 0;
    session.pace = payload.pace || null;
    showTranscript(payload.transcript);
    paintClock(payload.elapsed_seconds || 0);
    return;
  }
  if (eventName === "working") {
    markWorking(payload.name);
    statusEl.textContent = payload.name === "Evaluator"
      ? "The evaluator is writing the sheet."
      : "The club is listening, one seat at a time.";
    return;
  }
  if (eventName === "agent") {
    const seat = seats.get(payload.name);
    if (!seat) return;
    for (const other of seats.values()) other.classList.remove("active");
    seat.classList.add("active", "done");
    showSeat(seat, payload.report);
    session.seats.push({
      name: payload.name === "AhCounter" ? "Ah-Counter" : payload.name,
      lines: payload.report.lines,
      note: payload.report.note || (payload.report.categories ? "Sheet is on the podium." : ""),
    });
    if (payload.name === "Evaluator") {
      session.sheet = payload.report;
      showSheet(payload.report);
    }
    return;
  }
  if (eventName === "done") {
    statusEl.textContent = "Evaluation complete.";
    for (const seat of seats.values()) {
      seat.classList.remove("active");
      setPose(seat, false);
    }
    return;
  }
  if (eventName === "error") {
    errorEl.hidden = false;
    errorEl.textContent = payload.message || "The session failed.";
    statusEl.textContent = "Stopped.";
  }
}

async function consume(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop();
    for (const block of blocks) {
      let eventName = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) handleEvent(eventName, JSON.parse(data));
    }
  }
}

async function stopRecording() {
  if (!recorder || recorder.state === "inactive") return;
  const blob = await new Promise((resolve) => {
    recorder.addEventListener("stop", () => resolve(new Blob(chunks, { type: recorder.mimeType })), { once: true });
    recorder.stop();
  });
  clearInterval(tick);
  recordBtn.textContent = "Record";
  recordBtn.classList.remove("recording");
  const timerSeat = seats.get("Timer");
  if (timerSeat && !timerSeat.classList.contains("done")) {
    timerSeat.classList.remove("active");
    setPose(timerSeat, false);
    const note = timerSeat.querySelector(".note");
    note.hidden = false;
    note.textContent = "Waiting";
  }
  recordBtn.disabled = true;
  recorder = null;
  const form = new FormData();
  const extension = blob.type.includes("mp4") ? "m4a" : "webm";
  form.append("audio", blob, `speech.${extension}`);
  form.append("topic", topicEl.value.trim());
  form.append("target_seconds", String(targetSeconds()));
  form.append("model", modelEl.value);
  statusEl.textContent = "Sending the recording.";
  const response = await fetch("/api/session", { method: "POST", body: form });
  if (!response.ok) {
    errorEl.hidden = false;
    errorEl.textContent = "The club could not accept the recording.";
    recordBtn.disabled = false;
    setLocked(false);
    return;
  }
  try {
    await consume(response);
  } finally {
    recordBtn.disabled = false;
    setLocked(false);
  }
}

async function startRecording() {
  resetSeats();
  beginSession();
  paintClock(0);
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const type = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
  recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
  chunks = [];
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size) chunks.push(event.data);
  });
  recorder.addEventListener("stop", () => {
    for (const track of stream.getTracks()) track.stop();
  });
  recorder.start();
  startedAt = performance.now();
  setLocked(true);
  recordBtn.textContent = "Stop";
  recordBtn.classList.add("recording");
  statusEl.textContent = "Recording. The timer on the podium is for you. The Timer seat reports after.";
  const paintRecording = () => {
    const elapsed = (performance.now() - startedAt) / 1000;
    paintClock(elapsed);
    const timerSeat = seats.get("Timer");
    timerSeat.classList.add("active");
    setPose(timerSeat, true);
    const note = timerSeat.querySelector(".note");
    note.hidden = false;
    note.textContent = formatClock(elapsed);
  };
  paintRecording();
  tick = setInterval(paintRecording, 200);
}

async function evaluateText() {
  const transcript = speechEl.value.trim();
  if (!transcript) {
    errorEl.hidden = false;
    errorEl.textContent = "Paste a speech before evaluating.";
    return;
  }
  resetSeats();
  beginSession();
  paintClock(spokenSeconds());
  setLocked(true);
  recordBtn.disabled = true;
  statusEl.textContent = "The club is reading the pasted speech.";
  const response = await fetch("/api/text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic: topicEl.value.trim(),
      transcript,
      target_seconds: targetSeconds(),
      elapsed_seconds: spokenSeconds(),
      model: modelEl.value,
    }),
  });
  if (!response.ok) {
    errorEl.hidden = false;
    errorEl.textContent = "The club could not accept the speech.";
    recordBtn.disabled = false;
    setLocked(false);
    return;
  }
  try {
    await consume(response);
  } finally {
    recordBtn.disabled = false;
    setLocked(false);
  }
}

recordBtn.addEventListener("click", async () => {
  errorEl.hidden = true;
  try {
    if (recorder && recorder.state === "recording") await stopRecording();
    else await startRecording();
  } catch (error) {
    errorEl.hidden = false;
    errorEl.textContent = error.message || "Recording failed.";
    setLocked(false);
  }
});

evaluateBtn.addEventListener("click", async () => {
  errorEl.hidden = true;
  try {
    await evaluateText();
  } catch (error) {
    errorEl.hidden = false;
    errorEl.textContent = error.message || "Evaluation failed.";
    recordBtn.disabled = false;
    setLocked(false);
  }
});

newTopicBtn.addEventListener("click", () => {
  if (!locked) loadTopic();
});

minutesEl.addEventListener("input", paintBand);

paintBand();
loadTopic();
loadModels();
downloadBtn.addEventListener("click", downloadReport);
newRoundBtn.addEventListener("click", newRound);
closeSheetBtn.addEventListener("click", () => setSheetOpen(false));
sheetBackdrop.addEventListener("click", () => setSheetOpen(false));
openSheetBtn.addEventListener("click", () => setSheetOpen(true));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setSheetOpen(false);
});

async function loadModels() {
  try {
    const response = await fetch("/api/models");
    const body = await response.json();
    modelEl.replaceChildren();
    for (const model of body.models || []) {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = model.label;
      option.selected = model.id === body.selected;
      modelEl.append(option);
    }
    if (!modelEl.options.length) {
      const option = document.createElement("option");
      option.value = body.selected || "";
      option.textContent = body.selected || "Foundry";
      modelEl.append(option);
    }
  } catch {
    const option = document.createElement("option");
    option.textContent = "Foundry";
    modelEl.append(option);
  }
}
