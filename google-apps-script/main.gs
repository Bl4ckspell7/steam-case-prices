// ── Constants ──
const SHEET_DATA = "Cases total value";
const SHEET_HISTORY = "Cases value history";

const ROW_TOTALS = 4;
const ROW_START = 6;

const COL_NAME = 2; // B  — case name (layout reference)
const COL_JSON_URL = 7; // G  — steam priceoverview URL (price matching)
const COL_CURRENT_PRICE = 9; // I  — current unit price (written by fetch)

// Snapshot source columns (totals row) — updated for sales tracking:
const COL_HELD_VALUE = 11; // K  — held value  (bought-still-held × current price)
const COL_INV_CASH = 15; // O  — investment cash  (realized proceeds, invest-tagged)
const COL_INVESTMENT = 17; // Q  — investment P/L  (unrealized + realized)
const COL_HOLD_VALUE = 20; // T  — if-never-sold value  (all bought × current price)

const PRICES_URL =
  "https://raw.githubusercontent.com/Bl4ckspell7/steam-prices/data/prices.json";

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("Steam Tracker")
    .addItem("Fetch prices", "updateFromGitHub")
    .addSeparator()
    .addItem("Save snapshot", "saveSnapshotToHistory")
    .addToUi();
}

function updateFromGitHub() {
  const resp = UrlFetchApp.fetch(PRICES_URL, { muteHttpExceptions: true });
  const data = JSON.parse(resp.getContentText());
  const sheet =
    SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_DATA);
  const lastRow = sheet.getLastRow();
  const numRows = lastRow - ROW_START + 1;

  // Build lookup: name and market ID → price
  const lookup = {};
  for (const item of data.prices) {
    const price = item.median_price ?? item.lowest_price ?? null;
    lookup[decodeURIComponent(item.name).toLowerCase()] = price;
    if (item.id) lookup[item.id.toLowerCase()] = price;
  }

  // Match by JSON URL column (extract market_hash_name)
  const urls = sheet.getRange(ROW_START, COL_JSON_URL, numRows).getValues();
  for (let i = 0; i < urls.length; i++) {
    const url = urls[i][0];
    if (!url) continue;

    const match = url.match(/market_hash_name=([^#]+)/);
    if (!match) continue;

    const name = decodeURIComponent(match[1]).toLowerCase();
    const cell = sheet.getRange(ROW_START + i, COL_CURRENT_PRICE);

    if (!(name in lookup)) {
      // Item missing from prices.json entirely → URL/name mismatch, surface it
      cell.setValue("Not Found");
      continue;
    }

    const price = lookup[name];
    // null price = item matched but momentarily has no listings/sales on
    // Steam — keep the cell's last known price instead of wiping it
    if (price !== null) {
      cell.setValue(price);
    }
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

  const heldValue = data.getRange(ROW_TOTALS, COL_HELD_VALUE).getValue(); // K4
  const invCash = data.getRange(ROW_TOTALS, COL_INV_CASH).getValue(); // O4
  const profit = data.getRange(ROW_TOTALS, COL_INVESTMENT).getValue(); // Q4
  const holdValue = data.getRange(ROW_TOTALS, COL_HOLD_VALUE).getValue(); // T4

  hist.appendRow([
    heldValue + invCash, // A: Value      (held value + cash pulled out)
    profit, // B: Profit     (unrealized + realized)
    new Date(), // C: Date
    invCash, // D: Realized   (cash locked in — the floor)
    holdValue, // E: If never sold (all bought × current price)
  ]);
}

function installDailyTriggers() {
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getEventType() === ScriptApp.EventType.CLOCK)
    .forEach((t) => ScriptApp.deleteTrigger(t));

  // Fetch on spreadsheet open (installable — has auth)
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getEventType() === ScriptApp.EventType.ON_OPEN)
    .forEach((t) => ScriptApp.deleteTrigger(t));

  ScriptApp.newTrigger("updateFromGitHub")
    .forSpreadsheet(SpreadsheetApp.getActive())
    .onOpen()
    .create();

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
