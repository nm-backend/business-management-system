const fs = require('fs');
const path = require('path');

const uzPath = path.join(__dirname, '..', 'locale', 'uz_cyrl.json');
const ruPath = path.join(__dirname, '..', 'locale', 'ru.json');

const uz = JSON.parse(fs.readFileSync(uzPath, 'utf8'));
const ru = JSON.parse(fs.readFileSync(ruPath, 'utf8'));

function flatten(obj, prefix = '') {
  let keys = [];
  for (const [k, v] of Object.entries(obj)) {
    const full = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      keys = keys.concat(flatten(v, full));
    } else {
      keys.push(full);
    }
  }
  return keys;
}

const uzKeys = new Set(flatten(uz));
const ruKeys = new Set(flatten(ru));

console.log(`Uzbek keys count: ${uzKeys.size}`);
console.log(`Russian keys count: ${ruKeys.size}`);

const missingInRu = [];
for (const k of uzKeys) {
  if (!ruKeys.has(k)) {
    missingInRu.push(k);
  }
}

const missingInUz = [];
for (const k of ruKeys) {
  if (!uzKeys.has(k)) {
    missingInUz.push(k);
  }
}

console.log(`Keys in Uzbek missing in Russian: ${missingInRu.length}`);
if (missingInRu.length > 0) {
  console.log('Sample missing in Russian (first 10):', missingInRu.slice(0, 10));
}

console.log(`Keys in Russian missing in Uzbek: ${missingInUz.length}`);
if (missingInUz.length > 0) {
  console.log('Sample missing in Uzbek (first 10):', missingInUz.slice(0, 10));
}

// Now search for all data-i18n in templates and static/js
function walkDir(dir, filter) {
  let results = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== 'node_modules' && entry.name !== '.git' && entry.name !== 'venv') {
        results = results.concat(walkDir(full, filter));
      }
    } else if (filter(full)) {
      results.push(full);
    }
  }
  return results;
}

const files = walkDir(path.join(__dirname, '..', 'static', 'js'), f => f.endsWith('.js'))
  .concat(walkDir(path.join(__dirname, '..', 'templates'), f => f.endsWith('.html')));

const usedKeys = new Set();
const regexes = [
  /data-i18n="([^"]+)"/g,
  /data-i18n='([^']+)'/g,
  /\bui\.t\(['"]([^'"]+)['"]\)/g,
  /\bwindow\.ui\.t\(['"]([^'"]+)['"]\)/g,
  /\bi18n\.translate\(['"]([^'"]+)['"]\)/g,
  /\bwindow\.i18n\.translate\(['"]([^'"]+)['"]\)/g,
];

for (const file of files) {
  const content = fs.readFileSync(file, 'utf8');
  for (const re of regexes) {
    let match;
    while ((match = re.exec(content)) !== null) {
      const key = match[1];
      if (!key.includes('${') && !key.includes('+')) {
        usedKeys.add(key);
      }
    }
  }
}

console.log(`Total static i18n keys extracted from code: ${usedKeys.size}`);

const missingFromDictionaries = [];
for (const k of usedKeys) {
  if (!uzKeys.has(k) && !ruKeys.has(k)) {
    missingFromDictionaries.push(k);
  }
}

console.log(`Used keys missing in both uz and ru: ${missingFromDictionaries.length}`);
if (missingFromDictionaries.length > 0) {
  console.log('Missing keys from dictionaries:', missingFromDictionaries);
}
