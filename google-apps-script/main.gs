// ── Constants ──
const SHEET_DATA = "Cases total value";
const SHEET_HISTORY = "Cases value history";

const ROW_TOTALS = 4;
const ROW_START = 6;

const COL_NAME = 2; // B
const COL_JSON_URL = 7; // G
const COL_CURRENT_PRICE = 9; // I
const COL_BUY_VALUE = 11; // K
const COL_PROFIT = 12; // L

const PRICES_URL =
  "https://raw.githubusercontent.com/Bl4ckspell7/steam-prices/data/prices.json";

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("Steam Tracker")
    .addItem("Fetch prices", "updateFromGitHub")
    .addSeparator()
    .addItem("Save snapshot", "saveSnapshotToHistory")
    .addToUi();

  updateFromGitHub();
}

function updateFromGitHub() {
  const resp = UrlFetchApp.fetch(PRICES_URL, { muteHttpExceptions: true });
  const data = JSON.parse(resp.getContentText());
  const sheet =
    SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_DATA);
  const lastRow = sheet.getLastRow();
  const numRows = lastRow - ROW_START + 1;

  // Build lookup: encoded name → price
  const lookup = {};
  for (const item of data.prices) {
    lookup[decodeURIComponent(item.name).toLowerCase()] =
      item.median_price ?? item.lowest_price ?? null;
  }

  // Match by JSON URL column (extract market_hash_name)
  const urls = sheet.getRange(ROW_START, COL_JSON_URL, numRows).getValues();
  for (let i = 0; i < urls.length; i++) {
    const url = urls[i][0];
    if (!url) continue;

    const match = url.match(/market_hash_name=(.+)/);
    if (!match) continue;

    const name = decodeURIComponent(match[1]).toLowerCase();
    const cell = sheet.getRange(ROW_START + i, COL_CURRENT_PRICE);
    const price = lookup[name];

    cell.setValue(price ?? "Not Found");
  }

  SpreadsheetApp.getActiveSpreadsheet().toast(
    `Updated from ${data.updated_at}`,
    "Steam Tracker",
    5,
  );
}

function saveSnapshotToHistory() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const data = ss.getSheetByName(SHEET_DATA);
  const hist = ss.getSheetByName(SHEET_HISTORY);

  hist.appendRow([
    data.getRange(ROW_TOTALS, COL_BUY_VALUE).getValue(),
    data.getRange(ROW_TOTALS, COL_PROFIT).getValue(),
    new Date(),
  ]);
}

function installDailyTriggers() {
  // Clear any existing daily triggers
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getEventType() === ScriptApp.EventType.CLOCK)
    .forEach((t) => ScriptApp.deleteTrigger(t));

  ScriptApp.newTrigger("updateFromGitHub")
    .timeBased()
    .atHour(5)
    .everyDays(1)
    .create();

  ScriptApp.newTrigger("saveSnapshotToHistory")
    .timeBased()
    .atHour(6)
    .everyDays(1)
    .create();
}
