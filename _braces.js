var fs = require('fs');
var code = fs.readFileSync('./web/static/app.js', 'utf-8');

// Count brace balance
var openers = 0;
var closers = 0;
var inString = false;
var stringChar = '';
var escaped = false;

for (var i = 0; i < code.length; i++) {
    var ch = code[i];

    if (escaped) {
        escaped = false;
        continue;
    }

    if (ch === '\\') {
        escaped = true;
        continue;
    }

    if (inString) {
        if (ch === stringChar) {
            inString = false;
        }
        continue;
    }

    if (ch === "'" || ch === '"' || ch === '`') {
        inString = true;
        stringChar = ch;
        continue;
    }

    if (ch === '{') openers++;
    if (ch === '}') closers++;
}

console.log('Open braces:', openers);
console.log('Close braces:', closers);
console.log('Balanced:', openers === closers);

// Also count ALL function scopes
var fnCount = (code.match(/function\s+\w+\s*\(/g) || []).length;
var arrowCount = (code.match(/=>\s*\{/g) || []).length;
console.log('Functions:', fnCount);
console.log('Arrows:', arrowCount);
