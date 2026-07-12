// ── Constants ──
const SHEET_DATA = "Skins"; // adjust if the tab is named differently

const ROW_START = 6;

const COL_NAME = 1; // A  — skin name (layout reference)
const COL_JSON_URL = 11; // K  — steam priceoverview URL (price matching)
const COL_CURRENT_PRICE = 12; // L  — current unit price (written by fetch)

const PRICES_URL =
  "https://raw.githubusercontent.com/Bl4ckspell7/steam-prices/data/prices.json";

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("Steam Tracker")
    .addItem("Fetch prices", "updateFromGitHub")
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

  // Match by JSON URL column (extract market_hash_name);
  // rows without a URL are collection headers / blanks / sold items
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
}
