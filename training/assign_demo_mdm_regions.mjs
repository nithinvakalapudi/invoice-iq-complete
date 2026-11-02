// One-time repair for the synthetic 100-account demonstration master.
// Refuses other input shapes so real MDM mappings cannot be invented.
import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook } from '@oai/artifact-tool';

const master = path.resolve(process.argv[2] || 'local_data/MDM/vendor_accounts.csv');
const destination = path.resolve(process.argv[3] || master);
const csv = await fs.readFile(master, 'utf8');
const book = await Workbook.fromCSV(csv.replace(/^\uFEFF/, ''), { sheetName: 'Vendor Accounts' });
const sheet = book.worksheets.getItemAt(0);
const rows = sheet.getRange('A1:N101').values.map(row => row.map(value => String(value ?? '')));
const headers = rows[0];
const expected = ['Account', 'Description', 'Vendor', 'Last Invoiced', 'Billing Period',
  'Restricted To', 'Security Cost Code', 'Parent', 'Status', 'Default Currency',
  'Vendor Region', 'Vendor Address', 'Service Specification', 'Vendor Email'];
if (rows.length !== 101 || headers.join('|') !== expected.join('|') ||
    rows.slice(1).some(row => !/^CON-2026-\d{4}$/.test(row[0]))) {
  throw new Error('This is not the expected 100-row synthetic Vendor Accounts master; no changes made.');
}
const regions = ['APAC', 'EMEA', 'North America', 'LATAM', 'Africa'];
const location = {
  APAC: ['Singapore', '10 Market Street, Singapore 048940'],
  EMEA: ['London, United Kingdom', '10 Market Street, London, United Kingdom'],
  'North America': ['New York, NY', '10 Market Street, New York, NY 10001'],
  LATAM: ['Sao Paulo, Brazil', '10 Market Street, Sao Paulo, Brazil'],
  Africa: ['Johannesburg, South Africa', '10 Market Street, Johannesburg, South Africa'],
};
const groups = new Map();
for (const [index, row] of rows.slice(1).entries()) {
  const canonical = row[1].replace(/ Managed Services Agreement$/, '');
  if (!groups.has(canonical)) groups.set(canonical, []);
  groups.get(canonical).push({ index: index + 1, row });
}
if (groups.size !== 20 || [...groups.values()].some(group => group.length !== 5)) {
  throw new Error('Synthetic vendor groups changed; no changes made.');
}
rows[0].push('Vendor Alias');
for (const [canonical, group] of groups) {
  const firstRegion = group[0].row[5];
  if (!regions.includes(firstRegion)) throw new Error(`Unexpected original region: ${firstRegion}`);
  const assignments = [firstRegion, ...regions.filter(region => region !== firstRegion)];
  for (const [position, { row }] of group.entries()) {
    const region = assignments[position];
    row[5] = region;
    if (position > 0) {
      row[10] = location[region][0];
      row[11] = location[region][1];
    }
    row.push(row[2] === canonical ? '' : canonical);
  }
}
sheet.getRange('A1:O101').values = rows;
book.recalculate();
const check = await book.inspect({ kind: 'region', sheetId: sheet.name,
  range: 'A1:O6', maxChars: 2000 });
console.log(check.ndjson);
const escape = value => /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
const output = '\uFEFF' + rows.map(row => row.map(escape).join(',')).join('\r\n') + '\r\n';
await fs.writeFile(destination, output, 'utf8');
console.log(`Updated ${rows.length - 1} demo rows; ${groups.size} vendors; five distinct regions each.`);
