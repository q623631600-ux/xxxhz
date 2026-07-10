var fs = require('fs');
var code = fs.readFileSync('./web/static/app.js', 'utf-8');

var lines = code.split('\n');
var balance = 0;
var inString = false;
var inRegex = false;
var stringChar = '';

for (var l = 0; l < lines.length; l++) {
    var line = lines[l];
    var lineOpen = 0;
    var lineClose = 0;
    var escaped = false;

    for (var i = 0; i < line.length; i++) {
        var ch = line[i];

        if (escaped) { escaped = false; continue; }
        if (ch === '\\') { escaped = true; continue; }

        if (inString) {
            if (ch === stringChar) inString = false;
            continue;
        }

        if (ch === "'" || ch === '"' || ch === '`') {
            inString = true; stringChar = ch;
            continue;
        }

        if (ch === '/') {
            // Could be regex - handle roughly
            if (i > 0 && line[i-1].match(/[\s=(,:!&|?{};]/)) {
                inRegex = true;
                continue;
            }
        }

        if (inRegex) {
            if (ch === '/' && !escaped) {
                // End of regex
                inRegex = false;
            }
            continue;
        }

        if (ch === '{') { lineOpen++; balance++; }
        if (ch === '}') { lineClose++; balance--; }
    }

    if (lineOpen !== lineClose || lineOpen > 0 || lineClose > 0) {
        // Check if line has context prefixes
        var trim = line.trim();
        if (trim.startsWith('//') || trim.startsWith('/*')) continue;
        if (lineOpen !== lineClose) {
            console.log('Line ' + (l+1) + ': {' + lineOpen + ' }' + lineClose + ' bal=' + balance + ' ' + trim.substring(0, 60));
        }
    }
}

console.log('\nFinal brace balance:', balance);
